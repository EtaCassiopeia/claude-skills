# Decision register

**This file is the only place a design decision (`D-n`) is defined.** RFCs propose, ADRs argue,
the architecture guide explains, issues carry acceptance criteria, the vault holds analyses — but
when any of them disagree about *what was decided*, the entry here wins, and the others have a
bug. `scripts/design-check.py` enforces the parts of that which can be checked mechanically; the
rest is discipline, described in [`docs/process/design-code-sync.md`](../process/design-code-sync.md).

## How to read an entry

```
### D-16 — `redb` for all cluster durability
- **Status:** amended            active | amended | superseded | pending
- **Decided:** 2026-07-21 · ADR-001 · #14
- **Supersedes:** D-1, D-2       decisions this one retires (they get Superseded by: D-16)
- **Superseded by:** —
- **Amends:** RFC-001 §7.4       spec sections this decision changes — each MUST carry a
                                 "> Amended by D-16" callout (checked)
- **Implemented by:** #436       PRs/issues that landed it; an open one means the decision is
                                 ahead of the code, which is allowed but must be visible
- **Code:** crates/…/store.rs    where the decision lives; paths are checked to exist
```

`pending` means decided but not yet built — the code may still do the old thing. A `pending`
decision must list the open issue that builds it.

## Citation grammar (what code, tests and docs may reference)

| Token | Defined in | Resolved by `design-check` |
|---|---|---|
| `D-<n>` | this file | yes — must exist; citing a *superseded* one from code is flagged |
| `RFC-00N §x.y` | `docs/rfc/RFC-00N-*.md`, heading `### x.y …` | yes — the section must exist |
| `ADR-00N` | `docs/adr/ADR-00N-*.md` | yes |
| `U-<n>` | `docs/architecture/11-upstream-boundary.md` (upstream seams) | yes |
| `R1`…`R4` | RFC-001 §1.1 / `docs/architecture/01-overview.md` (the four load-bearing requirements) | no (fixed set) |
| `C<n>` | `docs/architecture/12-testing.md` (chaos scenarios) | no |
| `docs/<path>.md` | the file | yes — path must exist |
| `#<n>` | GitHub issue/PR | no |

Upstream Rift's own RFCs are a different numbering space; cite them as `rift RFC-712`, never bare.

**Pinning a decision in a test.** Any of the tokens above in the doc comment (`///`) or the
comment lines directly above a `#[test]`/`#[tokio::test]` attribute counts as a pin — that test is
then listed as evidence for the decision. Write the *claim* the test discriminates, not just the ID:

```rust
/// Pins D-19: the fan-out quorum is a majority of BOTH the committed and the effective voter
/// configuration — a committed-only majority would commit an op whose blob 2 of 5 nodes hold.
#[tokio::test]
async fn quorum_is_joint_over_committed_and_effective_voters() { … }
```

## Adding or changing a decision

1. A decision reached anywhere else — an issue thread, a review, a session with an agent, the
   vault — **is not made until it has a `D-n` here.** Open the PR that records it; the code PR
   may be the same PR.
2. Never edit a decision's meaning in place. Amend it (add an **Amendment** paragraph, set
   `Status: amended`) or supersede it (new entry, `Supersedes:` / `Superseded by:` on both).
   Superseded text stays, struck through in the title, because code and history cite it.
3. If it changes what an RFC or chapter says, list the section under `Amends:` and put
   `> **Amended by D-n** (date): <one line>` at the top of that section. `design-check` fails
   without it.
4. Cite it from the code that embodies it, and pin it with at least one test.

---

## Register

### ~~D-1 — <the first decision, later replaced>~~
- **Status:** superseded
- **Decided:** <date> · <RFC/ADR/issue>
- **Superseded by:** D-2

<Keep the text; code and history cite it.>

### D-2 — <a live decision>
- **Status:** active
- **Decided:** <date> · <RFC/ADR/issue>
- **Supersedes:** D-1
- **Amends:** RFC-001 §2.1
- **Implemented by:** #<pr>
- **Code:** <path/to/embodying/file.rs>

<What was decided, in one paragraph. Then:>

*Rejected:* <the alternatives and why — so they are not re-proposed.>
