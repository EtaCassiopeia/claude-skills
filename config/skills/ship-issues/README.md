# `/ship-issues` — issue-to-merge orchestrator

Drives a set of GitHub issues all the way to **merged**, unattended, by composing the existing
single-issue skills in a resumable serial loop:

```
triage-issue  →  fix-issue  →  commit-push-pr  →  babysit-prs  →  merge
```

It is a *conductor* — it writes no product code itself. Each phase is an existing skill that
already runs its own self-correcting loop; `ship-issues` picks and orders the worklist, routes each
phase to the right model, respects the repo's base-branch rules, isolates failures, and reports.

---

## Prerequisites

- The sibling skills must be installed: `triage-issue`, `fix-issue`, `commit-push-pr`, `babysit-prs`.
- `gh` authenticated for the repo; the project's build/test toolchain available (e.g. `cargo`).
- `CLAUDE.local.md` present for the repo (milestone → base-branch map, branch/commit conventions).
- **Launch the session on Opus** (see *Model policy*).

New skills register at session start — **restart Claude Code after installing before first use.**

## Using it in any repo (portability)

`ship-issues` and its sibling skills are installed **globally** (`~/.claude/skills/` → `claude-skills`
repo), so they're available in **every** repository — rift, zio-bdd, rift-enterprise,
zio-bdd-toolings, etc. — with no per-repo install. The pipeline is language-agnostic: `fix-issue`
detects the project type (Cargo / sbt / …) and adapts its verify gate, and `commit-push-pr` /
`babysit-prs` are pure GitHub/git.

Two things vary by repo, and both are handled without per-repo setup:

- **Toolchain** — `cargo *` (Rust) and `sbt *` (Scala) are both allowed **globally**, so Rust and
  Scala repos both work out of the box.
- **Base-branch convention** — `ship-issues` reads the target repo's base-branch rule from its
  `CLAUDE.md` / `CLAUDE.local.md` if present (e.g. rift's milestone → epic-branch map); if a repo has
  no such rule, it defaults to that repo's default branch (`main`/`master`).

So to run in another repo: just `cd` there and invoke `/ship-issues …`. Nothing else to configure.

## Permissions for unattended runs

Rather than `--dangerously-skip-permissions` (blanket, no guardrail, covers all subagents), the
routine commands are pre-approved in **global** `~/.claude/settings.json` so they don't pause — and
this covers every repo at once:

- **Allowed** (already global): `gh:*`, `cargo *`, `sbt *`, `git:*`, `caffeinate:*`, `Edit`, `Write`,
  and the usual read tools.
- **Denied backstop** (deny overrides allow, in any settings file): `rm -rf`, `git push --force`/`-f`,
  `git reset --hard`, `git clean -f`. So even unattended, an irreversible data-loss command is
  blocked rather than auto-run.

This is a deliberate trust increase — `Edit`/`Write` and `git push` are auto-approved in **all**
sessions, not just `ship-issues`. The deny list is the guardrail. To scope tighter, move the
`Edit`/`Write`/`git:*` allows out of global and into a per-repo `.claude/settings.local.json` for
only the repos you run unattended.

### Alternative: `--dangerously-skip-permissions`

For a fully hands-off run you can launch Claude Code with:

```sh
caffeinate -dimsu claude --dangerously-skip-permissions
```

This skips **all** permission prompts — no allowlist needed. Use it **only** in a repo where the
work is recoverable (everything committed; `fix-issue`'s worktrees are isolated) and the remote is
yours. Caveats to be honest about:

- **It's blanket and covers every subagent** — the Haiku babysit/commit/file-finding agents and all
  `fix-issue` internal agents run ungated too.
- **Treat the `deny` backstop as best-effort here.** `--dangerously-skip-permissions` is *designed*
  to bypass the permission layer, so don't rely on the `settings.local.json` deny-list to stop a
  destructive command in this mode. The real safety net is: everything is in git (recoverable),
  worktrees are isolated, and the `PreToolUse` hook (`rtk hook claude`) still runs and can veto.
- **Prefer the scoped allowlist above** for routine unattended runs; reach for
  `--dangerously-skip-permissions` only when you knowingly accept the risk in a disposable/recoverable
  checkout.

A `deny`-list is nonetheless configured in `rift`'s `.claude/settings.local.json` (and globally) as a
thin net for the *normal* (non-bypass) permission mode: `rm -rf`, `git push --force`/`-f`,
`git reset --hard`, `git clean -f`.

---

## Quick start

```sh
/ship-issues --all              # every open issue → implemented, PR'd, merged
/ship-issues 316 317 318        # just those three, in that order, to merged
/ship-issues --all --no-merge   # stop at green-CI PRs for your review (no auto-merge)
/ship-issues --label ready      # only issues carrying the "ready" label
/ship-issues --all --force-model # implement Fable-recommended issues on the session model too
```

Recommended first run: a single safe issue with `--no-merge` to watch the pipeline end-to-end
before turning it loose on `--all`.

---

## Model policy — why you launch on Opus

**Hard constraint:** `fix-issue` runs its entire main loop on whatever model the *session* was
launched on, and a skill cannot switch the session's top-level model mid-run. Everything invoked
*inline* therefore shares the session model. So the split is:

| Phase | Model | How |
|-------|-------|-----|
| Orchestrator glue | session model | inline; cheap (tool calls + short reasoning) |
| **`fix-issue`** (implementation) | **session model** | inline → must be the model you want it on |
| `triage-issue` | **haiku** | `Agent(model: 'haiku')` subagent |
| `commit-push-pr` | **haiku** | `Agent(model: 'haiku')` subagent |
| `babysit-prs` | **haiku** | `Agent(model: 'haiku')` subagent |

**⇒ Launch on Opus.** That puts the one expensive phase (`fix-issue`) on Opus while the three
mechanical phases run on Haiku subagents (billed at Haiku regardless of the session model).
`fix-issue`'s *own* internal subagents still drop to haiku/sonnet as designed. The
subagent→skill hop is verified to work; triage's model recommendation is read from its normal
prose output ("Recommended top-level model: X").

### Design-heavy issues → Fable (deferral)

Since the session model is fixed, triage's per-issue recommendation is handled by **routing**:

- **Session model covers the pick → run inline.** An Opus session covers Opus/Sonnet/Haiku picks,
  so those are implemented now. (Trivial issues are never deferred just to save a little.)
- **Peer-model pick the session can't cover → defer.** Triage recommends **Fable** for design-heavy
  issues as a capability preference, not a downgrade. Such an issue is *not* implemented; it's
  marked `deferred(fable)` and, at the end, listed with an exact relaunch command:

  ```
  Deferred (design-heavy → Fable): run  /ship-issues 14 22  in a Fable session
  ```

  Pass `--force-model` to implement them on the session model instead (one-shot, no second session).

---

## Umbrella / epic / tracking issues

An umbrella issue describes a *plan enacted by other issues* — it is **never** handed to
`fix-issue` (that would produce a monster PR and blow the fix cap). Detection fires on any of:
an `epic`/`umbrella`/`tracking`/`meta` label, native GitHub sub-issues, a `- [ ] #NNN` task-list in
the body or comments, or prose signals ("series of PRs", "tranche", "follow-up to #X").

On a hit it **decomposes** instead of implementing:

- Enumerate children (native sub-issues ∪ task-list refs), keep the **open** ones, preserve tranche
  order, and **enqueue those** into the worklist. Parent → `umbrella-expanded`.
- All children already closed → `umbrella-done` ("dischargeable — consider closing"); builds nothing.
- No machine-enumerable children (pure-prose plan) → `umbrella-manual`; skipped, needs a human to
  split it into issues first.

Issues that merely *reference* an umbrella but aren't in its child list are treated as ordinary
standalone issues.

---

## Merge behaviour

Auto-merge is the **default**: each PR is babysat to green CI and merged, fixing-on-fail in between,
until it merges or hits the cap. If a red CI traces to an implementation defect the Haiku babysit
can't fix, the orchestrator re-runs `fix-issue` on the session model once more before giving up.
Pass `--no-merge` to stop at a green-CI PR for manual review.

Invoking the skill **is** authorization to push, open PRs, and merge the worklist issues (merge
delegates to `babysit-prs`, whose merge-method and mergeability rules apply).

### Required-review blocks (branch protection / rulesets)

If `master` requires an approving review, a green PR shows as `BLOCKED` / `REVIEW_REQUIRED` and can't
be merged by its own author. `babysit-prs` classifies this by reading the branch's **ruleset**
(`gh api …/rules/branches/{branch}`) — not only the legacy branch-protection API, which returns
`404 "Branch not protected"` when a ruleset is in use. Then:

- **Solo repo, you're a bypass actor (admin)** → it admin-overrides (`gh pr merge --admin`)
  automatically — green CI still required.
- **Other collaborators exist** → it will **not** override unless you pass `--admin-merge`; otherwise
  it leaves the PR green-and-ready and reports "needs approval".
- **You can't bypass** → reports "needs approval" and stops.

So on a solo repo, green PRs merge unattended; the required-review gate only stops the pipeline when
you're not allowed to bypass it.

---

## Auto-filed findings (feedback loop)

While implementing an issue or diagnosing CI, the sub-skills routinely surface *out-of-scope*
defects worth a fix (e.g. #310's racy FSM transition and stuck-pending leak were found this way).
The orchestrator captures each via the reusable **`file-finding`** skill (run on a Haiku subagent):

- **Quality bar** — files only a concrete, actionable, worth-fixing defect that's out of the current
  scope. Style nits and speculative refactors are dropped.
- **Deduped** — searches open issues first; a duplicate is commented/linked, never re-filed.
- **`/fix-issue`-ready** — the filed issue carries provenance (source PR/issue), evidence, and a
  proposed fix.
- **Held for triage** — labeled `agent-found` + `needs-triage`. Phase 0 **excludes** `needs-triage`
  issues from `--all`, so a finding is never auto-implemented in the same or next run. Promote it
  (remove `needs-triage`, or name it explicitly) to make it eligible. This prevents a runaway
  find→fix→find loop while still capturing everything.

`file-finding` is also usable standalone: `/file-finding "stuck-pending leak on failed upstream in proxy recording"`.

## Failure isolation & caps

- One issue at a time (serial) — `fix-issue` isolates each in its own git worktree; serial keeps
  merges on shared base branches conflict-free.
- **Fresh base per issue** — before implementing, the base is `git fetch`ed and fast-forwarded to
  the remote tip, so each new worktree includes every previously-merged PR. With serial +
  merge-before-next, each issue builds on the latest code, so conflicts are avoided rather than
  resolved. (This freshness needs the default merge mode; under `--no-merge` earlier PRs stay open
  and won't be in a later issue's base.)
- A failed issue is recorded and skipped — never fatal to the batch, never merged red.
- Per-issue: sub-skills' own **3-cycle caps**, plus at most **one** extra `fix-issue` re-run when
  babysit traces a red CI to an implementation defect.
- **Circuit breaker:** 3 consecutive `blocked`/`pr-red` issues halts the loop (signals a systemic
  problem — broken base branch, CI outage, bad environment).

---

## Resume after an interruption (token-out, crash, new session)

The loop is built so a dead session is a **pause, not a loss**:

- **Nothing merged or pushed is lost.** Merged PRs stay merged, open PRs stay open. Progress is
  re-derived from **live GitHub state** (open PRs, merged/closed issues) plus the run-log
  `.rift-ship/worklist.md`, checkpointed after every phase — not from conversation memory.
- **To resume:** re-invoke the *same* command in a fresh session once tokens recharge. Phase 0
  re-prunes against GitHub, skips anything already PR'd or merged, and continues from the first
  non-terminal issue. Re-running is idempotent — never re-implements a PR'd issue, never re-merges.
- **Only rework:** an issue whose `fix-issue` was interrupted *before* its PR was opened is re-run
  from scratch (its worktree persists on disk — redo, not corruption).
- **Minimise blast radius:** when token-outs are likely, run smaller explicit batches
  (`/ship-issues 316 317 318`) rather than `--all`, so an interruption lands on a clean boundary.

> **Note on unattended resume:** this is *local* resume — it only advances while your local session
> is alive and un-throttled, so it does **not** make progress *during* a throttle window. A cloud
> `/schedule` routine was considered for that but rejected: cloud sessions are isolated checkouts
> that don't have these local skills or `CLAUDE.local.md`. If you later want progress-while-throttled,
> that requires a self-contained cloud-native rebuild of the pipeline.

---

## Unattended runs — keep the laptop awake (macOS)

An unattended `--all` run needs the machine awake for the whole time. In a **separate terminal tab**
(leave it running; `Ctrl-C` when the batch is done):

```sh
caffeinate -dimsu
```

`-d` no display sleep · `-i` no idle sleep · `-m` no disk sleep · `-s` no system sleep ·
`-u` declare user active. Time-box it if you prefer: `caffeinate -dimsu -t 28800` (8 h).

Or bind it to the run so it stops on its own when Claude Code exits:

```sh
caffeinate -dimsu -w $(pgrep -n -f 'claude')
```

Two caveats that actually bite:

- **Keep the lid open.** `caffeinate` blocks *idle* sleep but **not lid-close** sleep — closing the
  lid sleeps the machine anyway unless you're in clamshell mode (external display + power + external
  keyboard). For truly unattended, lid open on a desk.
- **Stay plugged in.** `-s` only holds on AC power; on battery macOS can still sleep.

GUI alternative: **System Settings → Battery → Power Adapter → "Prevent automatic sleeping when the
display is off."**

> Keeping the machine awake is necessary but not sufficient across a token throttle: an awake machine
> with an idle Claude session still won't advance until you re-invoke after tokens recharge (see
> *Resume* above). `caffeinate` ensures the run keeps going while it *has* tokens and is ready the
> moment you resume.

## Flags

| Flag | Effect |
|------|--------|
| *(bare issue numbers)* | Explicit worklist, in the given order (overrides `--all`). |
| `--all` | Every open issue (default when no numbers given). |
| `--label <name>` | Restrict to open issues carrying that label. |
| `--no-merge` | Stop at green-CI PR instead of auto-merging. |
| `--force-model` | Implement every issue on the session model, even Fable-recommended ones. |
| `--admin-merge` | Forwarded to `babysit-prs`: admin-override a required-*review* block when you're a ruleset bypass actor, even with other collaborators (CI must still be green). Solo repos already override by default. |

## Terminal statuses (in the final report)

`merged` · `pr-open` · `deferred(<model>)` · `umbrella-expanded` · `umbrella-done` ·
`umbrella-manual` · `needs-design` · `blocked` · `pr-red`
