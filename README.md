# Claude Code Config

Reproducible Claude Code configuration for Rust and Scala 3 / ZIO 2 development.
Skills, agents, and language rules are version-controlled here and symlinked into `~/.claude/`.

Includes library-specific skills for [zio-openfeature](config/skills/zio-openfeature/SKILL.md) and [Optimizely Feature Experimentation](config/skills/optimizely/SKILL.md).

## What's Inside

| Component | Path | Purpose |
|-----------|------|---------|
| CLAUDE.md | `config/CLAUDE.md` | Global instructions — coding philosophy, build commands, conventions |
| Rules | `config/rules/` | Language-specific rules (Rust, Scala 3 / ZIO 2, Scala type-level) |
| Agents | `config/agents/` | Specialized agents (architect, developer, reviewer, tester) |
| Skills | `config/skills/` | Slash commands and best-practice reference skills |
| Settings | `config/settings.json` | Plugins, hooks, and permissions |
| MCP Servers | `config/mcp-servers.json` | MCP server registrations (cargo-mcp, rust-analyzer-mcp) |

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and run at least once (`~/.claude/` must exist)
- [Rust toolchain](https://rustup.rs) (`cargo`, `rustc`)
- `python3` (ships with macOS)
- Optional: Java 11+ and [sbt](https://www.scala-sbt.org/) for Scala development

## Quick Start

```sh
git clone https://github.com/EtaCassiopeia/claude-skills ~/Projects/claude-skills
cd ~/Projects/claude-skills
./setup.sh
```

Then start a new Claude Code session to pick up the changes.

## What Setup Does

The `setup.sh` script is idempotent — safe to re-run anytime (e.g., after `git pull`).

1. **Preflight** — verifies `claude`, `cargo`, `python3` are available and `~/.claude/` exists
2. **Create directories** — ensures all required directories exist under `~/.claude/`
3. **Symlink files** — links `~/.claude/{CLAUDE.md, rules, agents, skills}` to files in this repo. If a regular file exists, it's backed up first. Correct symlinks are skipped.
4. **Merge settings.json** — deep-merges `config/settings.json` into `~/.claude/settings.json`. Repo values win on conflicts; any extra user-added entries are preserved. Backs up before writing.
5. **Register MCP servers** — patches `~/.claude.json` to add MCP server entries. Only touches the `mcpServers` key; all other data (telemetry, state) is untouched. Backs up before writing.
6. **Install MCP binaries** — runs `cargo install` for `cargo-mcp` and `rust-analyzer-mcp` (skips if already installed)
7. **Verify** — confirms all symlinks, settings keys, MCP registrations, and binaries

## Agents

Agents are specialized Claude Code modes with constrained tool access.

| Agent | Role | Tools |
|-------|------|-------|
| **architect** | System design, module organization, dependency analysis | Read-only |
| **developer** | Write code, fix bugs, refactor | Read + Write + Bash |
| **reviewer** | Code review, security scan, idiom compliance | Read-only + clippy/compile |
| **tester** | Write tests, coverage analysis, property-based testing | Read + Write + Bash |

Use them with `@architect`, `@developer`, `@reviewer`, `@tester` in Claude Code.

## Skills

Skills are either executable slash-command workflows or reference guides Claude consults automatically.

### Verification pipelines

- `/rust-check` — runs `cargo fmt --check` → `cargo clippy` → `cargo test` → `cargo deny check`
- `/scala-check` — runs `sbt compile` → `sbt scalafmtCheckAll` → `sbt test`

Both stop on first failure and report results in a summary table.

### Best-practice reference skills

These activate automatically based on context (file type, imports, topic) and inform every code generation and review decision.

| Skill | Triggers on | Covers |
|-------|-------------|--------|
| `scala3-best-practices` | `.scala` files, Scala 3 syntax questions | `enum`, `opaque type`, `given`/`using`, `extension`, `derives`, type design, metaprogramming, anti-patterns |
| `zio-best-practices` | ZIO/zio.* imports, ZLayer, zio-test, ZIO Prelude, Cause/Exit, ZSchedule | Service Pattern 2.0, effect type algebra, error model, Cause/Exit semantics, ZIO Prelude (Validation/ZPure), ZSchedule retry composition, advanced ZLayer wiring, fiber patterns (interruption masks, Semaphore, Supervisor) |
| `fp-patterns` | ADT design, typeclass questions, monad composition | Algebraic design, typeclass definition/derivation, effect composition, tagless final vs concrete ZIO, anti-patterns |
| `fp-advanced` | Category theory, ZIO Prelude typeclasses, optics, Kleisli, natural transformations | Covariant/Contravariant/ForEach/Associative, Kleisli pipelines, F ~> G, Bifunctor/Profunctor, Monocle optics, recursive schemes, Free monad / ZPure, typeclass laws |
| `scala-typelevel` | Variance design, GADTs, type lambdas, Mirror/Magnolia/Shapeless, compiletime ops | Variance rules, GADTs for typed ASTs, type lambdas (`[X] =>> F[X,E]`), match types, Mirror-based derivation, Magnolia typeclass derivation, Shapeless 3, `compiletime` operations, phantom types |
| `cats-ecosystem` | `cats.*`, `cats.effect.*`, `fs2.*`, `doobie.*`, `http4s.*` imports | Cats Core typeclass hierarchy (Functor→Monad→Traverse), Validated/ValidatedNel, Kleisli, Cats Effect 3 (IO/Resource/Ref/Deferred), FS2 streams, Doobie (transactor/Fragment), Http4s routes, Kyo, tagless final patterns |
| `zio-openfeature` | `zio.openfeature.*` imports, FeatureFlags service, provider wiring | ZLayer factories, sync vs async init, EvaluationContext (5-level hierarchy), FeatureFlagError ADT, hooks, events, transactions, multi-provider, testing, observability, internals |
| `optimizely` | Optimizely flag evaluation, Optimizely provider config, Optimizely + OpenFeature wiring | Flag key case sensitivity, user ID semantics, targeting rules, variables, decision reasons, graceful degradation, environment management, anti-patterns |

These can also be invoked manually: `/scala3-best-practices`, `/zio-best-practices`, `/fp-patterns`, `/fp-advanced`, `/scala-typelevel`, `/cats-ecosystem`, `/zio-openfeature`, `/optimizely`.

> **Note:** A `rust-best-practices` skill is also available but installed separately via the Claude Code marketplace — it is not managed by this repo.

## MCP Servers

| Server | Purpose |
|--------|---------|
| `cargo-mcp` | Cargo commands as MCP tools (check, clippy, test, fmt, build, bench) |
| `rust-analyzer-mcp` | Code intelligence: symbols, definitions, references, hover, diagnostics |

These are user-scope MCP servers registered in `~/.claude.json`. The `rust-analyzer-lsp` plugin is configured via `settings.json`.

## Hooks

The `settings.json` includes PostToolUse hooks that run automatically:

- **Rust**: After any `Edit` or `Write` to a `.rs` file → `cargo check` runs automatically
- **Scala**: After any `Edit` or `Write` to a `.scala` file → `sbt compile` runs automatically

This gives instant compilation feedback as Claude Code edits your code.

## Per-Project Scala/Metals Setup

Metals v1.6.5+ has a built-in MCP server. Two options:

**With an IDE (VS Code, Neovim):** Add to Metals settings:
```json
{
  "metals.startMcpServer": true,
  "metals.defaultBspToBuildTool": true,
  "metals.mcpClient": "claude"
}
```
Metals auto-generates `.mcp.json` at project root.

**Headless:** Use [metals-standalone-client](https://github.com/jpablo/metals-standalone-client):
```sh
curl -L -o metals-standalone-client \
  https://github.com/jpablo/metals-standalone-client/releases/latest/download/metals-standalone-client-macos-executable
chmod +x metals-standalone-client
./metals-standalone-client /path/to/your/scala/project
```

## Making Changes

Edit files in `config/` — changes are instantly reflected in `~/.claude/` via symlinks.

For `settings.json` or `mcp-servers.json` changes, re-run `./setup.sh` to merge them.

Typical workflow:
```sh
# Edit a config file
vim config/rules/rust.md

# Changes are live immediately (symlinked)
# Start a new Claude Code session to pick them up

# For settings/MCP changes:
./setup.sh

# Commit
git add -A && git commit -m "Update rust rules"
```

## Troubleshooting

**Skills don't appear:** Start a new Claude Code session. Skills are loaded at startup.

**MCP servers not connecting:** Check that the binaries are installed (`which cargo-mcp rust-analyzer-mcp`). If missing, run `./setup.sh` or `cargo install cargo-mcp rust-analyzer-mcp`.

**Settings not applied:** Run `./setup.sh` to re-merge. Check `~/.claude/settings.json` to verify.

**Symlink broken:** Run `./setup.sh` — it will detect and fix broken symlinks.

**Backup files:** Backups are created as `<filename>.backup.<timestamp>` next to the original file. Safe to delete old ones.

## Uninstalling

```sh
# Remove symlinks and restore backups (or just delete symlinks)
for f in ~/.claude/CLAUDE.md ~/.claude/rules/rust.md ~/.claude/rules/scala-zio.md \
         ~/.claude/agents/*/AGENT.md ~/.claude/skills/*/SKILL.md; do
    [ -L "$f" ] && rm "$f"
done

# Optionally remove MCP binaries
cargo uninstall cargo-mcp rust-analyzer-mcp
```
