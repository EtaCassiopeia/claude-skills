---
name: triage-issue
description: "Pre-flight for /fix-issue — read a GitHub issue and recommend which top-level model to launch /fix-issue on (Opus default, Fable for design-heavy, Sonnet for trivial). Cheap; run it BEFORE /fix-issue. Usage: /triage-issue <github-issue-number>"
user_invocable: true
argument-hint: "<issue-number>"
allowed-tools:
  - Bash(gh issue view:*)
  - Bash(git remote get-url:*)
  - Bash(ls:*)
  - Bash(git grep:*)
---

## Live Context (loaded at invocation)

- **Issue**: !`gh issue view "$ARGUMENTS" --json number,title,body,labels,comments 2>/dev/null`
- **Repo remote**: !`git remote get-url origin 2>/dev/null`
- **Project type**: !`ls Cargo.toml build.sbt package.json go.mod pyproject.toml 2>/dev/null || true`

---

# Triage Issue — Model Pre-Flight for /fix-issue

**Why this exists:** `/fix-issue` runs its whole main loop (design the gate, write/integrate
code, diagnose, triage, fix) on whatever top-level model you launched it on, and a skill cannot
change the top-level model mid-run. So the model choice must be made *before* launch. This skill
reads the issue, scores it against a fixed rubric, and tells you which model to start on — and
the exact command to run. It is intentionally cheap: a short read, no worktree, no agents, no
code. Run it on any model (even Haiku); the verdict is the same.

**The recommendation picks the top-level model only.** `/fix-issue` already pins its sub-agents
(review → opus/sonnet, simplify/exploration → haiku, optional implementation → sonnet), so this
choice does not cascade into them.

---

## Step 1 — Read the issue

From the Live Context, extract: the stated **goal**, whether **acceptance criteria** are given
or must be derived, the **proposed solution shape** (is an exact API/spec supplied, or just a
problem?), and the **blast radius** (how many files/subsystems, new abstraction vs. localized
edit). If the body is thin, do ONE cheap `git grep` for the central symbol to gauge blast radius
— do not open a worktree or read broadly. This is a 30-second read, not Phase 2 of `/fix-issue`.

---

## Step 2 — Score against the rubric

Evaluate the three tiers **top-down**; take the first that matches.

### → Fable (design-first) — if ANY strong design signal is present
The deliverable is a *decision*, not just code; the main loop's own reasoning is the value.
- Acceptance criteria are absent or ambiguous — the issue states a **problem**, not a solution.
- **Multiple viable approaches with real trade-offs** (performance vs. faithfulness, simplicity
  vs. generality) and no clear winner — the #313 LocalSequencer "zero-overhead hybrid vs. literal
  spec" fork is the canonical case.
- Introduces a **new public abstraction / trait / API whose shape is a judgment call**, not
  dictated by the issue.
- **Cross-cutting**: changes a core data structure or ripples through many modules/signatures.
- An explicit **constraint in tension** ("no regression budget", strict back-compat, invariant
  preservation) that forces a design choice.
- Language like *redesign / rethink / architecture / how should we…*.

### → Sonnet (trivial) — only if ALL mechanical signals hold
- A **verbatim spec or exact API** is supplied (the issue hands you the signatures), OR it is a
  **bug with a clear repro and a stated fix direction**.
- **Localized**: one or two files, a clear target, no new abstraction.
- No cross-cutting change, no open design question.
- (#314 — full trait spec given — and #308 — bug with repro + fix direction — sit at the
  Sonnet/Opus boundary; when in doubt between these two, pick Opus.)

### → Opus (default) — everything else
Real implementation with non-trivial logic, moderate scope, or careful verification needed, but
the **goal and approach are clear enough** that no upfront design decision is required. This is
the common case; when a signal is genuinely borderline, prefer Opus over Fable (don't pay the
Fable premium unless a design decision is actually open) and prefer Opus over Sonnet (don't
under-power real logic).

---

## Step 3 — Output the verdict

Emit exactly this block:

```
## Triage: Issue #<N> — <title>

**Recommended top-level model: <Opus | Fable | Sonnet>**

Why:
- <signal 1, citing a specific from THIS issue — e.g. "exact RequestJournal API supplied → mechanical">
- <signal 2>
- <the deciding factor, if it was close>

Scope: <1-line blast-radius read — files/subsystems, new abstraction? y/n>
Open design question: <the fork the main loop must resolve, or "none — approach is dictated">

### Next step
Set the model (/model → <model>), then run:  /fix-issue <N>
```

Keep it to that block. Do not start implementing, do not create a worktree, do not spawn agents
— this is advice only. If the issue number was invalid or the body empty, say so and stop.

---

## Notes

- **Bias:** Opus is the floor for real work; reserve Fable for a genuinely *open* design decision,
  not merely a "hard" implementation (hard-but-clear is Opus). Sonnet only for genuinely trivial,
  fully-specified work.
- If the issue bundles both a design fork AND mechanical follow-through, recommend **Fable** — the
  design decision gates everything downstream, and you can't upgrade the top-level model mid-loop.
- This mirrors the model policy documented in `/fix-issue`'s SKILL.md; keep the two in sync.
