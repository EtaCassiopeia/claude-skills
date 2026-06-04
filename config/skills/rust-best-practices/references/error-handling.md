# Error Handling — Deep Reference

## The Two-Library Model

| Context | Library | Why |
|---------|---------|-----|
| Library crate | `thiserror` | Typed errors; callers can match variants |
| Binary / application | `anyhow` | Rich context; no need to expose variants |
| Both | Both | `anyhow` wraps `thiserror` errors seamlessly |

## thiserror Patterns

```rust
use thiserror::Error;

#[derive(Debug, Error)]
pub enum StorageError {
    // Transparent: delegates Display to inner error
    #[error(transparent)]
    Io(#[from] std::io::Error),

    // Custom message with field interpolation
    #[error("key not found: {key}")]
    NotFound { key: String },

    // Wrapping another typed error
    #[error("serialization failed")]
    Serialize(#[from] serde_json::Error),

    // Catch-all for internal errors (use sparingly)
    #[error("internal error: {0}")]
    Internal(String),
}
```

## anyhow Patterns

```rust
use anyhow::{Context, Result, bail, ensure};

fn load_config(path: &str) -> Result<Config> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("reading config from {path}"))?;

    let cfg: Config = serde_json::from_str(&raw)
        .context("parsing config as JSON")?;

    // bail! returns Err(anyhow!(...))
    ensure!(cfg.port > 1024, "port must be > 1024, got {}", cfg.port);

    Ok(cfg)
}
```

## Error Layering (library consumed by binary)

```rust
// lib.rs — typed error
#[derive(Debug, thiserror::Error)]
pub enum DbError {
    #[error("connection refused")]
    ConnectionRefused,
}

// main.rs — anyhow wraps it
fn main() -> anyhow::Result<()> {
    let db = connect().context("initializing database")?;
    // DbError is automatically converted to anyhow::Error
    Ok(())
}
```

## Propagation Rules

- Always use `?` over manual `match` for propagation
- Add `.context()` at module boundaries to preserve stack narrative
- Never silently swallow errors with `let _ = op();` in non-trivial code
- For truly expected failures (e.g., cache miss), use `Option` not `Result`

## When to Panic vs Return Error

| Situation | Use |
|-----------|-----|
| Programming bug (invariant violated) | `panic!` / `unreachable!` |
| External input failure | `Result` |
| Missing config that can't continue | `Result` propagated to `main` |
| Index out of bounds in safe loop | `.get(i).ok_or(...)` |

## Converting Between Error Types

```rust
// From trait (automatic with #[from])
let io_err: std::io::Error = ...;
let my_err: MyError = io_err.into(); // works if #[from] declared

// map_err for one-off conversions
let val = op().map_err(|e| MyError::Wrapped(e.to_string()))?;
```
