# fix-issue — Design Notes

The underlying design of the `/fix-issue` skill, and why it is shaped the way it is.
For the operational phase-by-phase spec, see [`SKILL.md`](./SKILL.md). This document explains
the *why*; `SKILL.md` is the *what*.

## What it is

`/fix-issue <N>` takes a GitHub issue number and drives it to ship-ready code through a
self-correcting loop: understand → isolate → locate → **write the gate** → implement → verify →
review → (fix and re-verify) → simplify → ship report. It is **on-demand** and **single-issue** —
the user invokes it for one issue at a time. It deliberately does *not* schedule itself or run
unattended; cadence and autonomy are the job of `/loop` and `/schedule`.

The skill stops at a hard cap of **3 fix cycles**. It never opens a PR or pushes — the ship
report is the handoff, and the user runs `/commit-commands:commit-push-pr` from the worktree.

## The governing principle

> **A loop does not satisfy your goal — it satisfies the gate you wrote.**

This is Goodhart's Law applied to agentic loops: a loop will cheerfully ship work that passes a
weak or vague gate while missing the actual intent. Every design decision below follows from
taking that seriously — if the gate is the thing the loop optimizes, then the gate must be
written **first**, written **from the acceptance criteria**, and must be **machine-checkable**.

## Influences

The design adapts "loop engineering" principles (André Lindenberg's *From Prompts to Loops* and
Cobus Greyling's [`loop-engineering`](https://github.com/cobusgreyling/loop-engineering) pattern
registry) to a single-issue, interactive skill. The five-plus-one loop primitives from that work
— scheduling, worktrees, skills, MCP tools, maker/checker sub-agents, and durable state — map
onto this skill as: a user trigger (in place of scheduling), a git worktree, this skill file,
the GitHub CLI, the `pr-review-toolkit` review agents, and a scratchpad run-log.

## The four gaps it closes

The skill is a rewrite of an earlier implement→verify→review loop. Four concrete weaknesses in
that earlier version motivated the redesign:

| Gap in the old loop | Fix |
|---------------------|-----|
| **Gate defined after implementation, generically.** Acceptance criteria were derived up front, but the actual gate was a fixed fmt/clippy/test pipeline not tied to those criteria. | **Verifier-first (Phase 3).** Each acceptance criterion maps to a named test or a checkable command; the failing tests are written and confirmed *red* before any production code. |
| **No durable state.** The iteration counter and blocker list lived only in conversation context and were lost on compaction. | **Durable run-log** at `<scratchpad>/fix-issue-<N>.md`, updated every phase and every cycle. It is the loop's spine across context loss and makes the run auditable. |
| **No work isolation.** Changes landed directly in the user's current working tree. | **Worktree isolation (Phase 1).** The loop runs in a dedicated `.claude/worktrees/issue-<N>` worktree on a `fix/issue-<N>` branch, with a graceful fallback to the current tree. |
| **Review agents treated as co-equal blockers** with the objective pipeline. | **Gate-as-truth (Phase 6).** The verify pipeline is the objective source of truth; review findings are advisory and only block at ≥80 confidence or for an uncovered acceptance criterion. |

## Key design decisions

- **Verifier-first / TDD by default.** Writing the gate before the implementation is the whole
  point — it is what prevents the loop from optimizing a hollow target. Confirming the tests are
  *red for the right reason* proves the gate actually exercises the criterion before any code
  exists to make it pass.
- **Single issue, on-demand.** Autonomy multiplies both judgment and mistakes. Keeping the skill
  user-triggered and scoped to one issue keeps a human at the decision points that matter
  (architecture, scope, the final commit). Recurrence is delegated to `/loop` / `/schedule`.
- **Worktree, not the live tree.** Isolation means a failed or abandoned run leaves the user's
  working tree untouched; the branch + worktree are a clean, inspectable artifact.
- **Durable run-log over in-context counters.** State is the element most easily lost across the
  human → prompt → context → agent handoffs ("continuity problem"). Persisting it to disk lets
  the loop resume coherently after compaction and gives a reviewable trail.
- **Hard budget, no scope creep.** A 3-cycle cap plus an explicit "no scope expansion across
  cycles" rule keeps a stuck loop from grinding tokens or quietly broadening the change. On
  exhaustion it surfaces a Remaining Blockers Report instead of shipping a failing gate.
- **Objective gate vs. advisory review.** Conflating a linter-grade pipeline with subjective
  agent opinions makes "done" ambiguous. The split keeps the success condition crisp while still
  benefiting from review signal.

## How to use it

```
/fix-issue 194
```

Requirements and behavior:

- Run from inside the target git repository. The skill reads the issue via `gh`, so the GitHub
  CLI must be authenticated and the issue must exist.
- It creates `.claude/worktrees/issue-<N>` and branch `fix/issue-<N>`, and does all work there.
- It writes/updates a run-log at `<scratchpad>/fix-issue-<N>.md` you can inspect at any time.
- When the gate passes it prints a **Ship-Ready** report with the acceptance-criterion→test
  mapping, the verification table, cycles used, and the worktree path.
- **Handoff:** run `/commit-commands:commit-push-pr` from the worktree. After the PR merges,
  clean up with `git worktree remove .claude/worktrees/issue-<N>`.
- If it can't pass within 3 cycles, it prints a **Blocked** report with the cycle history and
  leaves the worktree in place for manual investigation.

## What it will not do

- Open a PR or push (the ship report is the handoff).
- Modify files outside the located target set, or add features beyond the issue.
- Continue past 3 fix cycles.
- Fix adjacent issues it notices (it notes them instead).
