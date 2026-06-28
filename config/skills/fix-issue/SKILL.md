---
name: fix-issue
description: Implement a GitHub issue through a verifier-first, self-correcting loop in an isolated worktree. Produces ship-ready code. Usage: /fix-issue <github-issue-number>
user_invocable: true
argument-hint: "<issue-number>"
---

## Live Context (loaded at invocation)

- **Issue**: !`gh issue view "$ARGUMENTS" --json number,title,body,labels,comments 2>/dev/null`
- **Repo remote**: !`git remote get-url origin 2>/dev/null`
- **Current branch**: !`git branch --show-current 2>/dev/null`
- **Working tree**: !`git status --short 2>/dev/null`
- **Project type**: !`ls Cargo.toml build.sbt package.json go.mod pyproject.toml 2>/dev/null || true`

---

# Fix Issue — Verifier-First Loop

**Guiding principle:** *A loop does not satisfy your goal — it satisfies the gate you wrote.*
A loop will cheerfully ship work that passes a weak gate and misses the intent (Goodhart's Law).
So the gate is designed **first**, **from** the acceptance criteria, and the failing tests are
written **before** any implementation. The objective verify pipeline — not a review agent's
opinion — is the source of truth for "done."

Work through the phases **in order**. After every Verify failure or Review blocker, enter the
**Fix Phase** and return to Phase 5. The durable **run-log** is updated at the end of every
phase and every fix cycle, so the loop survives context compaction and stays auditable.
**Hard cap: 3 fix cycles.** If you exhaust them, emit the Remaining Blockers Report and stop —
never ship code that doesn't pass the gate.

---

## Phase 0 — Understand & Init Run-Log

Parse the issue from the Live Context above. Derive:

1. **Change required** — one sentence, no more scope than stated
2. **Acceptance criteria** — enumerated; if the issue doesn't state them, derive from the description
3. **Out of scope** — adjacent issues you spotted but will NOT touch

Then **initialize the run-log** at `<scratchpad>/fix-issue-<N>.md` (template at the end of this
file), recording the issue summary and acceptance criteria. `<scratchpad>` is the session
scratchpad directory. Update this file at the end of every phase and every fix cycle — it is the
loop's durable spine.

If the issue is ambiguous on any acceptance criterion, ask one targeted question before
continuing.

---

## Phase 1 — Isolate (Worktree Setup)

Run the loop in a dedicated git worktree so changes never touch the user's current working tree:

```bash
git worktree add .claude/worktrees/issue-<N> -b fix/issue-<N>
```

- Choose the branch prefix from the issue labels per convention (`feat/`, `fix/`, `refactor/`,
  `test/`); default to `fix/`.
- Record the worktree path and branch name in the run-log.
- **All** subsequent file edits, builds, tests, and git commands run with the worktree as the
  working directory. Prefer `git -C .claude/worktrees/issue-<N> ...` and run `cargo`/`sbt`/`npm`
  with that directory as the working directory — avoid bare `cd` (it can trigger a permission
  prompt).
- **Graceful fallback:** if this is not a git repo, or `worktree add` fails (e.g. branch
  exists), fall back to the current working tree and note the degraded isolation in the run-log.
  Do not hard-fail.

---

## Phase 2 — Locate

Before writing code, find the exact targets:

```bash
git grep -n "<relevant symbol>"   # find existing code
```

Identify and record in the run-log:
- Files to modify (be specific; list them)
- Existing utilities/functions to reuse — do not introduce abstractions when something already exists
- Test file(s) to add or extend

If a file is not in that list, do not touch it.

---

## Phase 3 — Gate Spec (Verifier-First)

**This is the core of the loop. Design the verifier before the implementation.**

For **each** acceptance criterion, define a concrete, machine-checkable check:
- a **named test** to write (preferred), or
- a command whose output objectively proves the criterion.

Record the criterion → check map in the run-log. This is the contract the implementation must satisfy.

**Then write the tests first** — before any production code:
- Unit tests: `#[cfg(test)] mod tests` in the same file (Rust) or `object XSpec extends ZIOSpecDefault` (Scala)
- Integration tests: `tests/` directory when end-to-end behaviour must be verified
- Cover the happy path and the key failure/edge cases from the issue

Run the new tests and confirm they **fail for the right reason** (red) — a test that passes
before you've implemented anything is not exercising the criterion. Record the red result in the
run-log.

Production rules (from CLAUDE.md) that govern everything you write from here:
- No comments unless the WHY is non-obvious (a hidden constraint, surprising invariant, workaround)
- No `.unwrap()` / `panic!` / `todo!` in production code paths (Rust)
- No error swallowing — failures must propagate or be explicitly handled
- No over-engineering — solve the stated problem, not hypothetical future requirements

---

## Phase 4 — Implement

Write the **minimal** production code to turn the Phase 3 tests green. Do not add scope beyond
what the gate requires.

---

## Phase 5 — Verify (objective gate = source of truth)

Auto-detect project type and run the **full** pipeline, with the worktree as the working
directory. Do not skip steps.

**Rust** (`Cargo.toml` present):
```bash
cargo fmt                        # auto-fix; never block on fmt alone
cargo clippy -- -D warnings      # must produce zero warnings
cargo test                       # all tests pass, including the Phase 3 gate tests
cargo deny check                 # run only if deny.toml exists
```

**Scala** (`build.sbt` present):
```bash
sbt compile
sbt scalafmtCheckAll
sbt test
```

**Node / TypeScript** (`package.json` present):
```bash
npm run lint 2>/dev/null || npx tsc --noEmit
npm test
```

The Phase 3 gate tests must now be green. Record the result in the run-log.

**Outcome:**
- All steps pass → **Phase 6 (Review)**
- Any step fails → note every failure → **Fix Phase** → return to Phase 5

---

## Phase 6 — Review (advisory checker layer)

Spawn these agents with the Agent tool, **in parallel** (one message, multiple Agent calls).
Each agent needs the worktree `git diff` of changed files as context.

1. **`pr-review-toolkit:code-reviewer`** — changed files, CLAUDE.md compliance, correctness bugs.
2. **`pr-review-toolkit:silent-failure-hunter`** — catch blocks, fallback logic, `unwrap_or`,
   `getOrElse`, error-swallowing patterns. Skip if the diff contains no error handling code.
3. **`pr-review-toolkit:pr-test-analyzer`** — do the gate tests actually cover every acceptance
   criterion? Are edge cases tested?

The verify pipeline is the objective gate; review findings are **advisory**. Classify:

| Class | Criteria | Action |
|-------|----------|--------|
| **Blocker** | Confidence ≥ 80 (Important or Critical) from any agent | Must fix |
| **Blocker** | An acceptance criterion has no covering test | Must fix |
| **Non-blocker** | Confidence < 80 (Suggestion) | Log; apply only if trivially safe |

**Gate check:**
- Zero Blockers → **Phase 7 (Simplify)**
- Any Blocker → **Fix Phase** → return to Phase 5

---

## Fix Phase

Triggered by: Phase 5 failure or Phase 6 Blocker.

1. Append a cycle entry to the run-log: `cycle N — <blockers found> → <fixes applied>`, one line
   per fix (`fixed: <what> in <file>`).
2. Fix **all** open blockers (verify failures + review blockers) in one pass — no partial fix
   followed by re-verify.
3. **No scope expansion**: fix the gate's failures, do not broaden the change.
4. Increment the cycle counter (you started at 0). Return to **Phase 5**.

**If this was the 3rd failed cycle** (counter = 3): stop. Do not enter Phase 7. Emit the
Remaining Blockers Report (end of file) and stop.

---

## Phase 7 — Simplify

Spawn **`pr-review-toolkit:code-simplifier`** on the diff. Apply suggestions that:
- Reduce lines without changing behaviour
- Improve naming clarity
- Remove duplication

After applying, re-run the verify pipeline (Phase 5) to confirm no regression.

---

## Phase 8 — Ship Report

Output this block when the gate passes:

```
## Ship-Ready: Issue #<N> — <title>

### Worktree
- Path: .claude/worktrees/issue-<N>
- Branch: fix/issue-<N>

### What changed
- <bullet — one line per meaningful change>

### Acceptance criteria → gate
- [x] <criterion 1> — covered by test `<test_name>`
- [x] <criterion 2> — covered by test `<test_name>`

### Verification
| Check               | Result                        |
|---------------------|-------------------------------|
| fmt / scalafmt      | PASS (auto-fixed if needed)   |
| clippy / compile    | PASS — zero warnings          |
| tests               | PASS — N total, M new         |
| code-reviewer       | PASS — no blockers            |
| silent-failures     | PASS / SKIPPED (no error code)|
| test coverage       | PASS — all criteria covered   |

### Fix cycles used: N / 3
### Run-log: <scratchpad>/fix-issue-<N>.md

### Next step
Run /commit-commands:commit-push-pr from the worktree (.claude/worktrees/issue-<N>).
After merge, clean up: git worktree remove .claude/worktrees/issue-<N>
```

---

## Remaining Blockers Report (when 3 cycles exhausted)

```
## Blocked After 3 Fix Cycles — Issue #<N>

### Unresolved issues
1. [source: clippy/test/code-reviewer/...] <description> — <file:line>
2. ...

### Cycle history (from run-log)
- Cycle 1: <summary>
- Cycle 2: <summary>
- Cycle 3: <summary>

### Worktree (left in place for inspection)
- Path: .claude/worktrees/issue-<N>   Branch: fix/issue-<N>

### Recommended next step
Manual investigation required. The blockers above need human judgement
before this change is ship-ready.
```

---

## Run-Log Template

Write this to `<scratchpad>/fix-issue-<N>.md` in Phase 0 and update it every phase / cycle:

```markdown
# Run-Log: Issue #<N> — <title>
worktree: .claude/worktrees/issue-<N>   branch: fix/issue-<N>

## Acceptance criteria → gate
- [ ] <criterion> → test `<name>` (red confirmed: <yes/no>)

## Targets
- files: <list>
- reuse: <existing utilities>

## Cycles (budget 3)
- cycle 0: verify=<pass/fail> review=<blockers>  fixes: <...>

## Status: <in-progress | ship-ready | blocked>
```

---

## Hard Constraints

- **Do not create a PR** and **do not push** — the ship report is the handoff; the user runs
  `/commit-commands:commit-push-pr` from the worktree.
- **All work happens in the worktree** (or the noted fallback tree); update the run-log every
  phase and every cycle.
- **Do not modify** files outside the Phase 2 list.
- **Do not add features** beyond what the issue states.
- **Stop at 3 cycles** — surface blockers instead of shipping a failing gate.
- **One issue at a time** — note adjacent issues found; do not fix them.
