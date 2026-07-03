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
- **Every issue starts from a fresh base.** Before implementing an issue, the base is fetched and
  fast-forwarded to the remote tip (Phase 1c), so the new worktree includes every previously-merged
  PR. Combined with serial + merge-before-next, each issue builds on the latest code and conflicts
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
   columns `issue | title | base | status | pr | notes`, all `status=pending`. This file is the
   durable source of truth for resume; update it after every phase transition.
7. **Announce the plan**: print the ordered worklist (noting any umbrella expansions) and the mode
   (merge vs `--no-merge`). Then begin the loop.

---

## Phase 1 — Per-issue pipeline (loop over the worklist, serial)

For each issue **N** with a non-terminal status, run steps a–g. On any hard failure, set the
issue's status, write the run-log, and `continue` to the next issue — never abort the whole loop.

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

**First, pull the base up to the remote tip so the new work is cut from the latest code.** Because
the loop is serial and (by default) merges each PR before the next issue starts, every
previously-shipped PR is already on the remote base by now — bring it in so `fix-issue` branches
from it, not a stale local copy. This is what keeps each issue building on all prior merged work and
avoids conflicts:

- `git fetch origin` so `origin/<base>` is current (this is the remote tip that includes every
  merged PR).
- Ensure `fix-issue` cuts its **isolated worktree directly from `origin/<base>`** — e.g.
  `git worktree add <path> -b <branch> origin/<base>`. Branching from the remote ref sidesteps any
  stale local base entirely; never branch a new issue off a stale local base or off another issue's
  branch.
- Optionally fast-forward the local base for cleanliness: `git switch <base> && git merge --ff-only
  origin/<base>` (only if `<base>` is checked out and fast-forwards). Do **not** `git reset --hard`
  the base — it's unnecessary (you branch from `origin/<base>` directly) and is denied by the safety
  backstop; there's nothing to reset since ship-issues never commits to a base branch.

> Freshness holds only when PRs actually merge before the next issue — i.e. the default merge mode.
> Under `--no-merge`, earlier PRs stay open, so a later issue's base won't include them; that's
> inherent to `--no-merge`, not a bug.

Then invoke the **`fix-issue`** skill for N **inline** (so it runs on the Opus session model). It
runs verifier-first in an isolated worktree with a hard cap of 3 fix cycles.
- **Success** (verify gate green, no unresolved review blockers) → proceed to 1d.
- **Failure** (cap exhausted / Remaining Blockers Report) → set `status=blocked`, copy the blockers
  summary into the run-log notes, and `continue`. Do **not** open a PR for broken work.

### 1d — Commit, push, open the PR (Haiku subagent)
Delegate **`commit-push-pr`** for N's worktree/branch to a **Haiku subagent**, targeting the base
from 1b. It must follow `CLAUDE.local.md`: branch name `<type>/rift-<issue>-<slug>`, conventional-
commit message (no Claude attribution in the body), PR title = issue title, body with `Closes #N` +
milestone. Record the PR number/URL in the run-log; set `status=pr-open`.

### 1e — Babysit to merged (Haiku subagent) — default
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

### 1g — Checkpoint
Update `.rift-ship/worklist.md`. This run-log + live GitHub state is enough to resume after
compaction: a re-invoke re-reads it, re-prunes against open PRs/merged issues, and picks up the
first non-terminal issue.

---

## Phase 2 — Final report

When every issue is in a terminal status (`merged` / `pr-open` / `deferred(<model>)` /
`needs-design` / `blocked` / `pr-red` / `umbrella-expanded` / `umbrella-done` / `umbrella-manual`),
print a summary table:

| Issue | Title | Base | Status | PR | Notes |
|-------|-------|------|--------|----|-------|

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

State counts plainly (e.g. "7 issues: 4 merged, 2 deferred (Fable), 1 needs-design; 3 findings
filed (#331-#333, held for triage)"). Never report an issue as merged that `babysit-prs` didn't
actually merge; never report `pr-open` as done.

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
