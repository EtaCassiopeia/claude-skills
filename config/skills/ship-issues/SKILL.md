---
name: ship-issues
description: "Orchestrate the full per-issue pipeline over a set of GitHub issues — triage -> fix-issue -> commit-push-pr -> babysit-prs -> merge — in a resumable serial loop that fixes-on-fail until each issue is merged. Cheap phases run on Haiku subagents; fix-issue runs on the session model. Issues triage routes to a model the session can't cover (e.g. design-heavy -> Fable) are deferred with a relaunch command. Usage: /ship-issues [<issue-number>...] [--all] [--label <name>] [--no-merge] [--force-model] [--admin-merge]"
user_invocable: true
argument-hint: "[<issue-number>...] | --all | --label <name> [--no-merge] [--force-model] [--admin-merge]"
allowed-tools:
  - Bash(gh issue view:*)
  - Bash(gh issue list:*)
  - Bash(gh pr list:*)
  - Bash(gh pr view:*)
  - Bash(git remote get-url:*)
  - Bash(git branch:*)
  - Bash(git status:*)
  - Bash(git worktree list:*)
---

## Live Context (loaded at invocation)

- **Args**: `$ARGUMENTS` (issue numbers and/or flags; empty → treat as `--all`)
- **Repo remote**: !`git remote get-url origin 2>/dev/null`
- **Current branch**: !`git branch --show-current 2>/dev/null`
- **My login**: !`gh api user --jq .login 2>/dev/null`
- **Open issues**: !`gh issue list --state open --json number,title,labels --limit 100 2>/dev/null`
- **My open PRs**: !`gh pr list --author @me --state open --json number,title,headRefName,baseRefName 2>/dev/null`

(The body fetches per-issue detail, per-PR state, and milestone/base rules itself — keep the
Live Context free of shell expansions and jq templates the permission checker rejects at preload.)

---

# Ship Issues — Orchestrator Loop

**Goal:** drive each issue in the worklist all the way to **merged**, unattended — implement it,
open a PR, watch CI, and when CI is green **merge**; when CI is red, fix and repeat until it merges
or a hard cap is hit. Do this for every issue in the worklist, one at a time, resumably.

This skill is a *conductor*. It writes no product code and diagnoses no build itself — it invokes
`triage-issue`, `fix-issue`, `commit-push-pr`, and `babysit-prs`, each of which already runs its
own verifier-first / watch-fix self-correcting loop. The conductor's jobs are: pick and order the
worklist, run the pipeline per issue, route each phase to the right model, respect the base-branch
rules, isolate failures so one bad issue never blocks the rest, and produce an auditable report.

## Guiding principles

- **Merge is the goal, not the PR.** By default the loop does not stop at "PR opened" — it babysits
  each PR to green CI and merges it, fixing-on-fail in between. `--no-merge` stops at green-CI PR.
- **Serial, not parallel.** One issue at a time. `fix-issue` isolates each in its own git worktree,
  but PRs land on shared base branches; serial keeps merges conflict-free and the run legible. Do
  **not** fan out issues to parallel subagents.
- **The user's checkout is never touched.** Every issue is implemented in its own worktree under
  `.claude/worktrees/`, cut from `origin/<base>`. The loop never runs `git switch`/`checkout`/
  `reset`/`merge` in the main working directory: it stays on whatever branch the user left it on,
  with their uncommitted work intact. `git fetch` is the only git write the main repo needs.
- **Every issue starts from a fresh base.** Before implementing an issue, `origin/<base>` is fetched
  and the worktree is cut **from that remote ref** (Phase 1c), so it includes every previously-merged
  PR — and so it does NOT inherit whatever the user's checkout happens to be on. Combined with
  serial + merge-before-next, each issue builds on the latest code and conflicts
  are avoided rather than fought.
- **Failure is isolated, never fatal to the batch.** If an issue's `fix-issue` exhausts its 3-cycle
  cap, or its PR can't be driven green by `babysit-prs`, record the blocker and **move to the next
  issue**. Never merge red work; never abandon the remaining worklist because one issue failed.
- **The base branch is chosen, never defaulted.** Follow the repo's milestone → base-branch map
  (*Phase 1b*). Defaulting every PR to `master` is a bug.
- **Authorization.** Invoking this skill **is** authorization to push, open PRs, **and merge** the
  worklist issues (merge delegates to `babysit-prs`, whose own merge-method and mergeability rules
  apply). Pass `--no-merge` if you want to review before merging.
- **Resumable & idempotent.** Progress is re-derived from GitHub each iteration (open PRs, merged/
  closed issues) plus a durable run-log, so the loop survives context compaction and a re-invoke
  simply continues where it left off — it never re-implements an issue that already has a PR, and
  never re-merges a merged one.

---

## Model policy — READ FIRST, it dictates how you launch this skill

There is one hard mechanical constraint: **`fix-issue` runs its entire main loop on whatever
top-level model this session was launched on, and a skill cannot switch the session's top-level
model.** Everything this orchestrator invokes *inline* (via the Skill tool) therefore shares the
session model. So the split is:

| Phase | Model | Mechanism |
|-------|-------|-----------|
| Orchestrator glue (this loop) | **session model** | runs inline; cheap (tool calls + short reasoning) |
| `fix-issue` (implementation) | **session model** | invoked **inline** → must be the session model |
| `triage-issue` | **haiku** | `Agent(model: 'haiku')` subagent |
| `commit-push-pr` | **haiku** | `Agent(model: 'haiku')` subagent |
| `babysit-prs` (watch-fix-merge) | **haiku** | `Agent(model: 'haiku')` subagent |

**⇒ Launch this skill on Opus.** That puts `fix-issue` (the only expensive phase, and the one you
want on Opus) on Opus, while the three cheap phases are delegated to **Haiku subagents** so they
bill at Haiku regardless of the session model. The orchestrator glue also rides on Opus, but it is
light — the saving that matters (heavy implementation on a strong model, everything mechanical on a
cheap one) is preserved. `fix-issue`'s *own* internal subagents still drop to haiku/sonnet as it
designs; this policy does not change that.

### Model routing & deferral (what happens when triage wants a different model)

`fix-issue` runs on the session model and cannot be switched per issue, so triage's per-issue model
recommendation is handled by **routing**, not by switching:

- **Session model *covers* the recommendation → run inline now.** A stronger session model is a safe
  substitute for a cheaper pick: an Opus session covers Opus / Sonnet / Haiku-recommended issues, so
  those are implemented in this run. (Never defer a trivial issue just to save a little on a cheaper
  model — the capability is already there.)
- **Recommendation is a *peer* model the session can't stand in for → defer.** Triage recommends
  **Fable** for design-heavy issues as a deliberate capability preference, not a downgrade; an Opus
  session is not a substitute for that intent. Such an issue is **not implemented** in this run: set
  `status=deferred(<model>)`, record it, and `continue`. At the end, deferred issues are grouped by
  model with an exact relaunch command (e.g. run `/ship-issues 14 22` in a **Fable** session).

  Concretely: `session=opus` defers `fable` picks; `session=fable` defers `opus` picks; a session
  defers any recommendation it does not itself cover. You (the running model) know your own identity —
  compare triage's pick against it.

- **`--force-model` overrides deferral:** implement every issue on the session model regardless of
  triage's pick (one-shot, no second session). Use when you'd rather run a design-heavy issue on Opus
  than launch a separate Fable batch.

**Delegating a phase to a Haiku subagent:** spawn `Agent` with `model: 'haiku'` and a prompt that
tells it to **invoke the named skill** for the given issue/PR and report back the result (PR number,
merged y/n, blocker). If a subagent cannot invoke skills in this harness, instruct it in the same
prompt to instead perform the phase's concrete steps directly (for commit-push-pr: commit per
`CLAUDE.local.md`, push, `gh pr create` against the chosen base; for babysit: `gh pr checks` watch,
fix-on-fail on the PR's own head, merge with the method matching the branch shape). Either path
bills at Haiku. Have the subagent return a compact structured result, not a transcript.

---

## Phase 0 — Parse args & resolve the worklist

1. **Flags** (parse from `$ARGUMENTS`):
   - `--all` — every open issue (the default when no issue numbers are given).
   - `--label <name>` — restrict to open issues carrying that label.
   - `--no-merge` — stop at green-CI PR instead of merging (merge is otherwise the default).
   - `--admin-merge` — legacy no-op, forwarded to `babysit-prs` (1e). Babysit now admin-overrides a
     required-*review*-only block by default whenever you're a ruleset bypass actor (repo admin),
     even with other collaborators, so this flag no longer changes anything. CI must still be green
     and the PR MERGEABLE; the override never bypasses a red required check.
   - `--force-model` — defer nothing; implement every issue on the session model (see routing above).
   - Bare integers — an explicit issue list (overrides `--all`).
2. **Build the candidate set** from the Live Context *Open issues* (or an explicit list), applying
   `--label` if present.
3. **Prune already-in-flight / done issues:**
   - Skip an issue that already has an open PR that closes it (match *My open PRs* head branches
     against the `<type>/rift-<issue>-<slug>` convention, and `gh pr list --search "<issue> in:body"`).
     If such a PR exists and merge is enabled, hand it straight to Phase 1e (babysit) — don't
     re-implement.
   - Skip issues labeled `blocked`, `wontfix`, `needs-design`, or `question` unless named explicitly.
   - Skip issues labeled `needs-triage` (this is the hold-for-triage label the auto-filer applies —
     agent-found findings are not implemented until a human promotes them by removing that label)
     unless the issue is named explicitly in the args.
4. **Expand umbrella / tracking / epic issues — never implement them directly.** An umbrella issue
   describes a *plan enacted by other issues*, not a unit of work; handing its body to `fix-issue`
   would produce a monster PR and blow the fix cap. Detect an umbrella by **any** of:
   - a label like `epic`, `umbrella`, `tracking`, or `meta`;
   - native GitHub sub-issues (`gh api repos/{owner}/{repo}/issues/{n}/sub_issues`);
   - a task-list of issue refs (`- [ ] #NNN`) in the body **or comments**;
   - prose signals: "umbrella", "series of (small/additive) PRs", "tranche", "follow-up to #X",
     "will link each PR here", "one per item".

   On a hit, **decompose instead of implement**:
   - Enumerate children = native sub-issues ∪ task-list `#NNN` refs. Keep only the **open** ones
     (closed children are already done). Preserve the umbrella's stated order/tranches (e.g.
     "#316/#317/#318 first"; "depends on #X" first).
   - **Enqueue the open children** into the worklist (each runs the normal per-issue pipeline), and
     set the parent's `status=umbrella-expanded` — it is not implemented; it closes when its
     children do. Do not enqueue issues that merely *reference* the umbrella but aren't in its
     child list (those are related follow-ups → treated as ordinary standalone issues).
   - If **all** children are already closed → set `status=umbrella-done` and note "dischargeable —
     consider closing"; build nothing.
   - If an umbrella has **no machine-enumerable children** (pure-prose plan) → set
     `status=umbrella-manual` and skip; it needs a human to split it into issues first.
5. **Order** the worklist: explicit arg order if given; else ascending issue number. If an issue
   body says "depends on #X", put #X earlier. Keep expanded-umbrella children in their tranche order.
6. **Write the run-log** at `.rift-ship/worklist.md` (create the dir): one row per issue with
   columns `issue | title | base | status | pr | docs | notes` (fill `docs` at 1c-docs), all
   `status=pending`. This file is the
   durable source of truth for resume; update it after every phase transition.
7. **Announce the plan**: print the ordered worklist (noting any umbrella expansions) and the mode
   (merge vs `--no-merge`). Then begin the loop.

---

## Phase 1 — Per-issue pipeline (loop over the worklist, serial)

For each issue **N** with a non-terminal status, run steps a–g. On any hard failure, set the
issue's status, write the run-log, and `continue` to the next issue — never abort the whole loop.

### 1·coord — Coordinator: pipeline the CI waits (repo-aware, decide ONCE up front)

Implementation is **always serial** — `fix-issue` runs inline on the session model, one issue at a
time. But the ~per-PR **CI wait** in step 1e is dead time in a strictly-serial loop: on a repo whose
CI takes 15+ min, blocking on each merge before starting the next issue wastes that window. The win
is to overlap it — implement issue N+1 *while* N's CI runs — but only when it actually pays off and
won't trigger a rebase cascade. So before the loop, the coordinator makes **one** decision:

**Measure two facts about the target repo:**
1. **CI duration** — recent successful run wall-clock: `gh run list --limit 10 --json name,conclusion,startedAt,updatedAt` (or observe the *first* PR you open this run). Call it long if the required checks take **≳ 8–10 min**, short if **≲ a few min**.
2. **Does merging require an up-to-date branch / required status checks?** Check both classic protection (`gh api repos/{o}/{r}/branches/{base}/protection` → `required_status_checks.strict`) and **rulesets** (`gh api repos/{o}/{r}/rulesets` then the ruleset detail → any `required_status_checks` rule with `strict_required_status_checks_policy`). "Strict/up-to-date required" means every merge invalidates the other open PRs' mergeability → forced rebase + CI re-run for each.

**Choose the mode:**
- **Strictly serial** (default; the safe choice) when CI is **short**, OR the repo **requires
  up-to-date branches / required status checks**. Run 1a–1e inline per issue, babysit each PR to
  merged **before** starting the next (as written below). Short CI ⇒ the coordination isn't worth
  the complexity; strict-branch ⇒ pipelining just moves the wait into a rebase cascade. Say so in
  the run-log (`pipeline: off — CI ~3m` / `pipeline: off — strict branches`).
- **Pipelined fan-out** when CI is **long** AND up-to-date is **not** required AND required status
  checks are absent/bypassable (you're an admin). Then:
  1. Run **1a–1d serial and inline** per issue (triage → base → implement → commit-push-pr). Opening
     the PR starts its CI. Do **not** run 1e yet — move straight to the next issue so the CIs stack
     up and run concurrently.
  2. After the last issue's PR is open, do a **merge sweep**: merge the PRs one at a time in worklist
     order (1e per PR). Because up-to-date isn't required, merging one does **not** invalidate the
     others — no rebase cascade. The only cross-PR conflict is a **shared file**, almost always
     `CHANGELOG.md`: resolve it by rebasing that one PR onto the new base and keeping *both* entries
     (place each issue's entry under a distinct changelog subsection — `Fixed`/`Security`/`Changed` —
     so git 3-way usually auto-merges them and no rebase is even needed). Since CI isn't merge-
     required here, a CHANGELOG-only rebase can merge as soon as it's mergeable without re-waiting a
     full CI re-run (the code was already green pre-rebase).
  3. Keep the merge sweep **serial** — never fan out concurrent background merges that rebase onto a
     moving base (they race). Record `pipeline: on — CI ~15m, fan-out N PRs, merge sweep`.

Never pipeline the *implementation* (fix-issue is inline/serial by construction), and never merge a
red or unmergeable PR. When in doubt, stay strictly serial — it is always correct, just slower.

### 1a — Triage & route (Haiku subagent)
Delegate `triage-issue` for N to a **Haiku subagent**. Use its verdict to:
1. **Screen out non-implementable issues** — if triage says the issue needs human design or is a
   question/underspecified, set `status=needs-design` and `continue`.
2. **Route by model** per *Model routing & deferral* above: if the session model covers triage's
   recommendation (or `--force-model` is set), proceed on the session model. If triage recommends a
   peer model the session can't cover (e.g. **Fable** for a design-heavy issue on an Opus session),
   set `status=deferred(<model>)`, record it, and `continue` — do not implement it in this run.
3. **Note complexity** in the run-log.

### 1b — Choose the PR base branch
Determine the base **before** implementing, from the **target repo's** convention (this skill runs
in any repo, so don't hardcode rift's rules):
- Read the repo's `CLAUDE.local.md` / `CLAUDE.md` for a base-branch rule. Some repos map
  issue → milestone → base branch (e.g. rift: "PR base branch — do NOT default to master", with
  per-milestone epic branches). If such a rule exists, follow it.
- If the repo has **no** such rule, default to the repo's **default branch** (`main`/`master`, via
  `gh repo view --json defaultBranchRef`).
- Epic-branch targets (when the rule requires one): if the epic branch doesn't exist yet it must be
  created off the default branch and pushed first. If that setup can't be done safely unattended,
  record it as a blocker and `continue` rather than opening a PR against the wrong base.
- Record the chosen base in the run-log.

### 1c — Sync the base, then implement (Opus, inline)

**Fetch the remote tip so the new work is cut from the latest code — but never touch the user's
checkout.** Because the loop is serial and (by default) merges each PR before the next issue starts,
every previously-shipped PR is already on the remote base by now; branching from `origin/<base>` is
what picks it up, and it is also what keeps the user's working directory out of the blast radius:

- `git fetch origin` so `origin/<base>` is current (this is the remote tip that includes every
  merged PR). Fetch is read-only — it updates remote refs and nothing else.
- Ensure `fix-issue` cuts its **isolated worktree directly from `origin/<base>`**:
  `git worktree add <path> -b <branch> origin/<base>`. The explicit `origin/<base>` is mandatory —
  without it the worktree branches from whatever the user's checkout has checked out, so a leftover
  feature branch silently becomes the base and its commits ride along into the PR.
- **Never `git switch` / `git checkout` / `git reset` / `git merge` in the user's checkout.** It
  stays on whatever branch they left it on — the loop has no business moving it. Do not
  "fast-forward the local base for cleanliness": it is not needed (you branch from `origin/<base>`,
  never from the local base), it silently changes the branch under the user's editor, and it fails
  outright the moment their tree is dirty. A stale local base is harmless because nothing ever
  reads it.
- The **only** writable working directories this loop has are the per-issue worktrees under
  `.claude/worktrees/`. If a step seems to require editing the user's checkout, that step is wrong.

> Freshness holds only when PRs actually merge before the next issue — i.e. the default merge mode.
> Under `--no-merge`, earlier PRs stay open, so a later issue's base won't include them; that's
> inherent to `--no-merge`, not a bug.

Then invoke the **`fix-issue`** skill for N **inline** (so it runs on the Opus session model). It
runs verifier-first in an isolated worktree with a hard cap of 3 fix cycles.
- **Success** (verify gate green, no unresolved review blockers) → proceed to 1c-docs.
- **Failure** (cap exhausted / Remaining Blockers Report) → set `status=blocked`, copy the blockers
  summary into the run-log notes, and `continue`. Do **not** open a PR for broken work.

**1c-docs — Documentation is part of "done" (before you leave 1c).** A change that ships new or
changed behaviour is not complete until the docs a user or maintainer would consult are updated **in
the same worktree, so the docs land in the same PR** as the code. `fix-issue` often does this when
the issue's acceptance criteria name it, but its coverage is issue-dependent — so treat docs as an
explicit gate here, not an afterthought. In the worktree, before 1d:

- **Decide what's relevant.** Map the change to the docs that describe it: user-facing docs
  (`docs/`, `README`, guides, a DSL/API reference), the public API's own doc comments/Scaladoc, a
  `CHANGELOG`/release notes if the repo keeps one, `--help`/usage text for a CLI, and config/env
  references for new knobs or flags. Look at how *sibling* features are documented and match that
  home and depth (e.g. a new combinator gets an entry alongside the existing ones, a new env var
  joins the existing table) rather than inventing a new location.
- **Update or add it**, then re-run the verify pipeline (docs can break a docs-build/link-check or a
  fenced code sample that's compiled) so the docs change is covered by the same green gate as the
  code. Keep examples runnable and consistent with the shipped API.
- **Exempt** only genuinely doc-less changes — a pure-internal refactor, a test-only fix, a CI/build
  tweak with no user-facing surface. When you exempt, say so in the run-log (`docs: n/a — <why>`);
  don't skip silently.
- Record what you touched in the run-log (`docs: <files>`), and include the doc change in the 1d PR
  body so a reviewer sees the behaviour and its documentation together.

### 1d — Commit, push, open the PR (Haiku subagent)
Delegate **`commit-push-pr`** for N's worktree/branch to a **Haiku subagent**, targeting the base
from 1b. It must follow `CLAUDE.local.md`: branch name `<type>/rift-<issue>-<slug>`, conventional-
commit message (no Claude attribution in the body), PR title = issue title, body with `Closes #N` +
milestone. Record the PR number/URL in the run-log; set `status=pr-open`.

### 1e — Babysit to merged (Haiku subagent) — default
**In pipelined mode (1·coord), 1e is deferred:** don't babysit here — move to the next issue and run
all the 1e merges together in the end-of-run merge sweep. In strictly-serial mode, run 1e inline now.

Unless `--no-merge`, delegate **`babysit-prs`** for this PR to a **Haiku subagent** (forwarding
`--admin-merge` if it was passed). It watches CI, fixes-on-fail on the PR's own head up to its own
3-cycle cap, and merges when green using the merge method matching the branch shape. babysit reads
the branch's **ruleset** (not just legacy branch protection) to classify a `BLOCKED` PR, and —
whenever you are a ruleset **bypass actor** (repo admin), regardless of other collaborators —
admin-overrides a required *review* it can't self-satisfy (green CI is still required).
- Merged → `status=merged`.
- babysit hard-stops (still red after its cap, or unmergeable) → `status=pr-red`, note why, `continue`.

If a CI failure roots in an implementation defect the Haiku babysit can't diagnose, it should say so
in its result; the orchestrator may then re-run `fix-issue` (1c) **inline on Opus** for that issue
once more before giving up (this counts against the issue's overall attempts — see caps below).

With `--no-merge`, skip 1e and leave the green-CI PR for review; `status` stays `pr-open`.

### 1f — Harvest & file findings (out-of-scope discoveries)
While implementing (1c) and diagnosing CI (1e), the sub-skills routinely surface **concrete,
out-of-scope defects or gaps** that are worth a fix but must not derail the issue in hand — the
racy FSM transition and the stuck-pending leak in #310 are exactly this kind of discovery. For each
such finding, delegate to the **`file-finding`** skill (a **Haiku subagent**), passing the finding,
its evidence, a proposed fix, and the source (this issue / the PR). It dedups against open issues,
files with `agent-found` + `needs-triage`, and returns `filed #<n>` / `duplicate of #<n>` /
`no finding worth filing`.

Findings are **held for triage**: they carry `needs-triage`, so Phase 0 excludes them from a later
`--all` run until you promote them. This prevents a runaway find→fix→find loop while still capturing
everything. Record filed/duplicate finding numbers in the run-log notes for this issue.

### 1f-cross — Downstream-consumer impact (only when the repo declares consumers)

An engine/library repo is rarely the last stop: SDKs, conformance suites, sample corpora and
example harnesses consume its wire schemas, ABI, config format and CLI. A change can be perfectly
green here and still leave those repos stale — or leave its own value unrealized. **Skip this step
entirely when the repo declares no downstream consumers** (see discovery below); do not invent them.

**Discovery.** Read the repo's `CLAUDE.local.md` / `CLAUDE.md` for a *Downstream consumers* section
listing consumer repos and the surfaces each one consumes. No section → skip, silently.

**Cheap gate first.** Most issues touch nothing a consumer sees. Compare the merged diff's files
against the declared surfaces; if none match, record `downstream: none — no consumed surface
touched` and move on. Only on a match do the deeper analysis below (delegate it to a **Haiku
subagent**: give it the diff, the declared consumer map, and these rules).

**The trap this exists to catch: "additive" is not "nothing to do".** A backward-compatible
addition breaks no consumer *and* is invisible to every one of them until they adopt it — so the
feature ships and nobody uses it. Judge each consumer on two separate questions:

- **Compatibility** — does anything there *break* or silently misbehave? (A schema gaining a field
  under `deny_unknown_fields` means a new-SDK-on-old-engine call is a hard error, so adoption must
  be version-gated. A new error code/status a consumer maps. A changed response body.)
- **Adoption** — where does this change's *value* actually land? If the point of the work is that a
  consumer can now delete a workaround, that deletion is the deliverable, and it lives over there.

For each real item, file an issue **in that repo** (`gh issue create --repo <owner>/<name>`), with
the same discipline as 1f: dedup first, state the engine version/PR that introduced it, say plainly
whether it is *required* (compat) or *optional* (adoption), and label it for human triage. Never
implement it in this run — different repo, different gate, different review.

Record one line per consumer in the run-log (`downstream: rift-java #12 (adoption), rift-go none`),
and surface it in the Phase 2 report.

### 1g — Checkpoint
Update `.rift-ship/worklist.md`. This run-log + live GitHub state is enough to resume after
compaction: a re-invoke re-reads it, re-prunes against open PRs/merged issues, and picks up the
first non-terminal issue.

---

## Phase 2 — Final report

When every issue is in a terminal status (`merged` / `pr-open` / `deferred(<model>)` /
`needs-design` / `blocked` / `pr-red` / `umbrella-expanded` / `umbrella-done` / `umbrella-manual`),
print a summary table:

| Issue | Title | Base | Status | PR | Docs | Downstream | Notes |
|-------|-------|------|--------|----|------|------------|-------|

The **Docs** column records the doc outcome from 1c-docs for each implemented issue — the files
touched, or `n/a — <why>` when genuinely exempt. It makes the "docs are part of done" gate auditable
at a glance; a merged issue with a blank Docs cell is a smell to flag, not to hide.

The **Downstream** column does the same for 1f-cross: the consumer issues filed (`rift-java #12`),
`none — no consumed surface touched`, or `n/a` in a repo that declares no consumers. Same reasoning:
a merged issue that changed a consumed schema and shows a blank cell is a smell.

Then, grouped for action:
- **Merged**: PR links.
- **PR open, CI green** (`--no-merge`): PR links to review & merge (or `/babysit-prs <n>`).
- **Deferred (wrong model)**: grouped by recommended model, with one exact relaunch command per
  group — e.g. "design-heavy → Fable: run `/ship-issues 14 22` in a Fable session".
- **Umbrellas**: `umbrella-expanded` (list the child issues enqueued), `umbrella-done`
  (dischargeable — suggest closing), `umbrella-manual` (needs a human to split into issues).
- **needs-design**: issues triage flagged as underspecified — need human input before implementing.
- **blocked / pr-red**: the one-line blocker per issue and the suggested next step.
- **Findings filed** (`agent-found` + `needs-triage`): the new issue numbers filed during the run,
  noting they are held for your triage — promote (remove `needs-triage`) to make them eligible for a
  future `--all` run.
- **Downstream follow-ups filed** (1f-cross): grouped by consumer repo, each marked *required*
  (compat) or *optional* (adoption). Call out any *required* one explicitly — that is a consumer
  that is broken or version-gated until it lands, not a nice-to-have.

State counts plainly (e.g. "7 issues: 4 merged, 2 deferred (Fable), 1 needs-design; 3 findings
filed (#331-#333, held for triage)"). Never report an issue as merged that `babysit-prs` didn't
actually merge; never report `pr-open` as done.

---

## Phase 2.5 — Refresh the cross-repo delivery dashboard (if one is configured)

Some programs keep a **live cross-repo dependency dashboard** — a folder of one-note-per-issue
records plus a graph/board that answers *"what's next, and what's blocked by what."* When the run
touched such a program, refresh it so it never goes stale. **Skip this phase entirely if no dashboard
is configured** (no `dashboard.path` and no discoverable dashboard note) — do not invent one.

Discover the dashboard from, in order: an explicit `dashboard.path` in the repo's `CLAUDE.local.md`;
else a `.rift-ship/dashboard-path` file; else a note titled *"Delivery Dashboard"* / a `db/` issue
folder already linked from the repo. (For the Rift program the dashboard lives in the user's Obsidian
vault at `tasks/rift-enterprise/issues/` — `delivery-dashboard.md`, `cross-repo-issue-dependency-graph.md`,
and `db/*.md`, one note per issue with `status`/`priority`/`blocked_by`/`unblocks`/`kind` frontmatter.)

Delegate the refresh to a **Haiku subagent** (mechanical; give it the dashboard path + this run's
outcomes). It must:

1. **Add new findings.** For every issue filed in **1f** (`agent-found`), create/refresh its db note
   with `status: blocked|ready` and the `blocked_by`/`unblocks` edges you observed.
2. **Update statuses from this run.** Merged issue → remove its db note **iff** no *open* issue still
   references it in `blocked_by`/`unblocks` (a resolved leaf); if it's still referenced, keep it as
   `status: done` so the edge stays legible. `blocked`/`pr-red` → set `status: blocked` with the
   concrete blocker in `blocked_by`. New PR not yet merged → `status: in-flight`.
3. **Model release/consume gates — a merge is not a delivery.** Shipping an issue often does **not**
   unblock a downstream repo: the library must be **published** and the consumer must **bump its pin**
   (e.g. rift-conformance pins a `zio-bdd` version). Keep these as first-class gate nodes
   (`kind: release` for a publish, `kind: consume` for a pin-bump) between the code node and its
   downstream. When an issue merges but its downstream is still on the old published version, set the
   downstream to `status: awaiting-release` (**not** `ready`) and point its `blocked_by` at the gate.
   Close/remove a gate only when the publish/bump actually happened.
4. **Garbage-collect.** Drop db notes for issues that are closed **and** unreferenced by any open
   issue; leave everything still on someone's critical path.
5. **Stamp it.** Update the `Last updated:` footer (date + one line: e.g. "N merged, M findings, gates
   refreshed") in the dashboard note and the graph note. The Dataview/board views re-render from the
   db frontmatter automatically — only hand-curated mermaid needs a manual nudge if the *spine*
   changed (new cross-repo edge), which you note for the human rather than redrawing blindly.

Report the dashboard delta in the Phase 2 output (e.g. "dashboard: +2 findings, 3 leaves GC'd,
1 release gate opened"). If the dashboard path is unreachable (e.g. a headless run with no vault),
say so and skip — never fail the run over dashboard upkeep.

---

## Resuming after an interruption (token-out, crash, new session)

A session can die mid-run — token/rate-limit exhaustion, a crash, or you simply closing it. The
loop is built to make that a **pause, not a loss**:

- **Nothing merged or pushed is lost.** Merged PRs stay merged, open PRs stay open. Progress is
  re-derived from **live GitHub state** (open PRs, merged/closed issues) plus the run-log
  `.rift-ship/worklist.md`, which is checkpointed after every phase — not from conversation memory.
- **To resume:** re-invoke the *same* command (e.g. `/ship-issues --all`) in a fresh session once
  your tokens recharge. Phase 0 re-prunes against GitHub, re-reads the run-log, skips anything that
  already has a PR or is merged, and continues from the first non-terminal issue. Re-running is
  safe and idempotent — it never re-implements a PR'd issue or re-merges a merged one.
- **The only rework** is an issue whose `fix-issue` was interrupted *before* its PR was opened:
  it has no PR yet, so resume re-runs it from scratch. `fix-issue`'s own worktree and run-log
  persist on disk, so this is redo, never corruption.
- **To minimise blast radius** when token-outs are likely: run smaller explicit batches
  (`/ship-issues 316 317 318`) rather than `--all`, so an interruption lands on a clean boundary.
- **Unattended auto-resume:** because resume is idempotent, a scheduled routine that re-invokes
  `/ship-issues --all` every few hours will continue the batch on its own after a throttle window
  clears — and is a cheap no-op while everything is already merged.

## Hard caps & stop conditions

- Per-issue implementation and CI fixing inherit the sub-skills' **3-cycle caps**. The orchestrator
  allows at most **one** extra `fix-issue` re-run per issue when babysit traces a red CI to an
  implementation defect (1e → 1c). Beyond that, the issue is `pr-red`/`blocked` and skipped.
- **Consecutive-failure circuit breaker:** if **3 issues in a row** end `blocked`/`pr-red`, stop the
  loop and report — this signals a systemic problem (broken base branch, CI outage, bad environment)
  that per-issue retries won't fix. List the remaining `pending` issues.
- Never force-push, never touch a branch that isn't an issue's own head, never merge a PR that isn't
  green and mergeable.
- Never move or dirty the user's checkout: no `git switch`/`checkout`/`reset`/`merge` outside a
  per-issue worktree, and no implementing an issue in the main working directory when its worktree
  cannot be created — stop and report instead.
