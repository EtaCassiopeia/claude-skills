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

---

## Failure isolation & caps

- One issue at a time (serial) — `fix-issue` isolates each in its own git worktree; serial keeps
  merges on shared base branches conflict-free.
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

## Flags

| Flag | Effect |
|------|--------|
| *(bare issue numbers)* | Explicit worklist, in the given order (overrides `--all`). |
| `--all` | Every open issue (default when no numbers given). |
| `--label <name>` | Restrict to open issues carrying that label. |
| `--no-merge` | Stop at green-CI PR instead of auto-merging. |
| `--force-model` | Implement every issue on the session model, even Fable-recommended ones. |

## Terminal statuses (in the final report)

`merged` · `pr-open` · `deferred(<model>)` · `umbrella-expanded` · `umbrella-done` ·
`umbrella-manual` · `needs-design` · `blocked` · `pr-red`
