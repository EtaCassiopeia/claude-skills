---
path_scope:
  - "**/*.rs"
  - "**/Cargo.toml"
---

# Rust Development Rules

## Error Handling

- Libraries: use `thiserror` for structured error types
- Applications: use `anyhow` for ergonomic error propagation
- Never use `.unwrap()` in production code — use `?`, `.expect("reason")`, or match
- Prefer `?` operator over manual match for error propagation

### Silent-fallback (swallow) taxonomy

`.ok()` / `unwrap_or_else(|_| default)` / `unwrap_or_default()` on a `Result` silences the
failure. Before writing one, name which category it is — and when reviewing, flag any that
can't be named (this exact shape shipped as rift #606/#608/#610/#611: serde failure → `200 OK`
`{}`; a config block silently dropped; a security gate failing open; a 200-status "error"
fallback):

- **Domain-optional parse (OK):** the input may legitimately not be that type — absence is a
  domain value, not an error (e.g. "is this request body JSON?"). Comment it if non-obvious.
- **Terminal last-resort (OK only if BOTH hold):** the final fallback of an error path, where
  (1) the fallback payload is infallible by construction AND (2) status/severity stays correct —
  a fallback that answers `200` for a failure is a bug even at the last resort (`Response::new`
  defaults to 200).
- **Data-path swallow (NEVER):** config, user payload, or response data whose parse/serialize
  failure becomes a silent default. Propagate, map to a correct error response, or at minimum
  log at error level. Wrong-but-quiet is worse than loud failure: it surfaces in the *client's*
  decoder with nothing server-side to correlate.
- **Security classifiers fail closed:** a gate that cannot parse what it is classifying treats
  it as the dangerous class, never the safe one.
- Define domain error enums: one per module/crate boundary
- Use `#[from]` for automatic conversions in thiserror enums

## Ownership & Borrowing

- Prefer borrowing (`&T`, `&mut T`) over owned values in function signatures
- Minimize `.clone()` — if cloning, add a comment explaining why
- Use `Cow<'_, T>` when a function might or might not need to own data
- Prefer `&str` over `String` in function parameters
- Use `Arc` for shared ownership across threads, not `Rc`

## Type Design

- Use newtypes for domain concepts: `struct UserId(Uuid)`, not bare `Uuid`
- Model state machines with enums — invalid states should be unrepresentable
- Default to `pub(crate)` visibility; only `pub` what's part of the API
- Derive `Debug` on all types; derive `Clone`, `PartialEq`, `Eq` where appropriate
- Use `#[must_use]` on functions that return important values

## Async

- Runtime: `tokio` (multi-threaded by default)
- Use `spawn_blocking` for CPU-bound or blocking I/O work
- Be aware of `Send`/`Sync` bounds — avoid holding non-Send types across `.await`
- Prefer `tokio::select!` for concurrent operations
- Use structured concurrency: `JoinSet` over loose `spawn` calls

## Testing

- Unit tests: `#[cfg(test)] mod tests` in the same file
- Integration tests: `tests/` directory at crate root
- Use `proptest` for property-based testing of pure logic
- Use `criterion` for benchmarks in `benches/`
- Use `mockall` or trait objects for mocking external dependencies
- Test error paths, not just happy paths

## Clippy Configuration

Recommend this in `Cargo.toml` or `clippy.toml`:

```toml
[lints.clippy]
unwrap_used = "deny"
panic = "deny"
todo = "deny"
dbg_macro = "deny"
print_stdout = "deny"
print_stderr = "deny"
expect_used = "warn"
pedantic = { level = "warn", priority = -1 }
```

## Preferred Crates

| Purpose | Crate |
|---------|-------|
| Serialization | `serde` + `serde_json` |
| Async runtime | `tokio` |
| Logging | `tracing` + `tracing-subscriber` |
| CLI | `clap` (derive) |
| HTTP server | `axum` |
| HTTP client | `reqwest` |
| Database | `sqlx` |
| Date/time | `chrono` or `time` |
| Testing | `proptest`, `criterion`, `mockall` |
| Dependencies audit | `cargo-deny` |

## Build Workflow

Always run in this order before declaring work complete:

```sh
cargo fmt
cargo clippy -- -D warnings
cargo test
cargo deny check  # if configured
```
