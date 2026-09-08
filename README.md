# Claude Code Config

Reproducible Claude Code configuration for Rust and Scala 3 / ZIO 2 development.
Skills, agents, and language rules are version-controlled here and symlinked into `~/.claude/`.

Includes library-specific skills for [zio-openfeature](config/skills/zio-openfeature/SKILL.md) and [Optimizely Feature Experimentation](config/skills/optimizely/SKILL.md).

## What's Inside

| Component | Path | Purpose |
|-----------|------|---------|
| CLAUDE.md | `config/CLAUDE.md` | Global instructions — coding philosophy, build commands, conventions |
| Rules | `config/rules/` | Language-specific rules (Rust, Scala 3 / ZIO 2, Scala type-level) |
| Agents | `config/agents/` | Specialized agents (architect, developer, reviewer, tester, bulk-reader) |
| Skills | `config/skills/` | Slash commands and best-practice reference skills |
| Settings | `config/settings.json` | Plugins, hooks, permissions, and status line |
| Status line | `config/statusline.sh` | Always-visible powerline bar: folder, git status, model, context usage |
| Hooks | `config/hooks/` | Standalone PreToolUse hooks (bulk-read-guard) |
| MCP Servers | `config/mcp-servers.json` | MCP server registrations (cargo-mcp, rust-analyzer-mcp) |
| graphify | `config/graphify/` | Knowledge-graph git hooks, worktree seeding, design-drift report ([guide](config/graphify/README.md)) |
| Global gitignore | `config/gitignore_global` | Ignore rules applied to every repo — keeps agent and knowledge-graph artifacts out of `git status` |

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and run at least once (`~/.claude/` must exist)
- [Rust toolchain](https://rustup.rs) (`cargo`, `rustc`)
- `python3` (ships with macOS)
- `jq` (used by the status line; `brew install jq` if missing)
- A [Nerd Font](https://www.nerdfonts.com) as the terminal font, for the status line icons (`brew install --cask font-jetbrains-mono-nerd-font`)
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
3. **Symlink files** — links `~/.claude/{CLAUDE.md, rules, agents, skills, statusline.sh}` to files in this repo, `~/.claude/graphify` to `config/graphify/`, and `~/.gitignore_global` to `config/gitignore_global` (also setting `git config --global core.excludesFile`, since the symlink alone does nothing). If a regular file or directory exists, it's backed up first. Correct symlinks are skipped.
4. **Merge settings.json** — deep-merges `config/settings.json` into `~/.claude/settings.json`. Repo values win on conflicts; any extra user-added entries are preserved. Backs up before writing.
5. **Register MCP servers** — patches `~/.claude.json` to add MCP server entries. Only touches the `mcpServers` key; all other data (telemetry, state) is untouched. Backs up before writing.
6. **Install MCP binaries** — runs `cargo install` for `cargo-mcp` and `rust-analyzer-mcp` (skips if already installed)
7. **Verify** — confirms all symlinks, settings keys (including `statusLine`), MCP registrations, and binaries

## Agents

Agents are specialized Claude Code modes with constrained tool access.

| Agent | Role | Tools |
|-------|------|-------|
| **architect** | System design, module organization, dependency analysis | Read-only |
| **developer** | Write code, fix bugs, refactor | Read + Write + Bash |
| **reviewer** | Code review, security scan, idiom compliance | Read-only + clippy/compile |
| **tester** | Write tests, coverage analysis, property-based testing | Read + Write + Bash |
| **bulk-reader** | Reads large files in an isolated context, returns bullets not contents (Haiku) | Read + Grep + Glob + Bash |

Use them with `@architect`, `@developer`, `@reviewer`, `@tester` in Claude Code.
`bulk-reader` is not @-mentioned — the bulk-read guard routes blocked reads to it.

## Rules

Rules are always-on guidance files loaded automatically based on file path. They steer every code generation and review decision without needing to invoke a skill.

| File | Scope | Covers |
|------|-------|--------|
| `rules/rust.md` | `**/*.rs`, `Cargo.toml` | Error handling (`thiserror`/`anyhow`), ownership, async patterns, preferred crates, clippy config |
| `rules/scala-zio.md` | `**/*.scala`, `build.sbt` | Scala 3 syntax, ZIO 2 Service Pattern, effect types, error model, ZLayer composition, ZIO Prelude, Cause/Exit, Schedule, testing |
| `rules/scala-typelevel.md` | `**/*.scala`, `build.sbt` | Variance (covariant/contravariant/invariant rules), GADTs, type lambdas, generic derivation choices (Magnolia vs Mirror vs Shapeless 3), `compiletime` guardrails |

Rules are loaded by Claude Code's harness whenever you edit a matching file — no invocation needed. They complement the on-demand skills by providing always-available baseline guidance.

## Skills

Skills are either executable slash-command workflows or reference guides Claude consults automatically.

### Workflow skills

- `/fix-issue <issue-number>` — implement a GitHub issue end-to-end through a verifier-first,
  self-correcting loop. It runs in an isolated git worktree, writes the failing gate tests
  **before** implementing (so the loop optimizes a real target, not a hollow one), verifies
  against the full project pipeline, runs the `pr-review-toolkit` review agents as an advisory
  layer, and self-corrects for up to 3 fix cycles. On success it prints a ship-ready report and
  hands off to `/commit-commands:commit-push-pr`; it never pushes or opens a PR itself.

  Usage: `/fix-issue 194` from inside the target repo (requires an authenticated `gh`). A durable
  run-log is written to the session scratchpad so the loop survives context compaction. The
  guiding principle — *a loop satisfies the gate you wrote, not your goal* — and the full
  rationale are documented in [`config/skills/fix-issue/DESIGN.md`](config/skills/fix-issue/DESIGN.md);
  the phase-by-phase spec lives in [`SKILL.md`](config/skills/fix-issue/SKILL.md).

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

### Bulk-read guard (PreToolUse)

`config/hooks/bulk-read-guard.py` blocks whole-file reads of large files and redirects them
to the `bulk-reader` Haiku subagent, so file contents never enter the main context. It is
registered on both `Read` and `Bash` — in bypass-permissions mode Claude reads with `cat`,
so a `Read`-only guard would be bypassed most of the time.

Bash detection is deliberately narrow: unpiped `cat FILE`, plus `head`/`tail` with an
explicit `-n` above the threshold. Anything piped or redirected, bare `head`/`tail`, and
ranged `sed -n '1,120p'` pass through untouched.

Escape hatches, because a gate with no exit deadlocks editing and would trap the subagent
reading the very files it was handed:

- `Read` with `offset`/`limit` is always allowed — a targeted read is already scoped
- **The second request for the same path is allowed.** The first denial delivers the nudge;
  a repeat means the content is genuinely needed. This is what breaks subagent recursion.
- `BULKREAD_OFF=1` disables it entirely

| Variable | Default | Meaning |
|----------|---------|---------|
| `BULKREAD_MIN_LINES` | 800 | Line count above which a whole-file read is blocked |
| `BULKREAD_MAX_BYTES` | 60000 | Byte size above which it is blocked (catches minified files) |
| `BULKREAD_TTL` | 3600 | Seconds the second-attempt escape hatch stays open, per path |
| `BULKREAD_OFF` | unset | Set to any value to disable the guard |

## Status Line
`config/statusline.sh` is symlinked to `~/.claude/statusline.sh` and wired in via the
`statusLine` key of `settings.json`. Every session shows an always-visible powerline bar in
the style of powerlevel10k: rounded, coloured segments with Nerd Font icons.
```
( ~/Projects/foo ) ( feat/x ⇡2 ●3 ) ( 󰚩 Opus 5.5 ) ( 󰧑 ▰▰▰▰▰▰▱▱▱▱ 63% )
```
| Segment | Shows | Colour |
|---------|-------|--------|
| Directory | Working folder, `~`-relative, truncated to the last 3 parts | blue |
| Worktree | Name of the linked git worktree (e.g. a `claude --worktree` session). Hidden in the main checkout | sky blue |
| Git | Branch (or `@sha` if detached), a `rebasing`/`merging` marker while one is in progress (the branch being rebased is still named), `⇡`/`⇣` ahead/behind, `●n` changed files. Hidden outside a repo | green when clean, yellow when dirty |
| Model | Model display name | purple |
| Context | 10-cell bar and percentage of the context window used | teal under 50%, orange from 50%, red from 80% |
With several sessions open, you can tell them apart at a glance.
**Needs** a [Nerd Font](https://www.nerdfonts.com) set as the terminal font (e.g. JetBrainsMono
Nerd Font, which powerlevel10k also uses) and a truecolor terminal (Ghostty, iTerm2,
WezTerm, Kitty). Without a Nerd Font, the icons and segment edges render as boxes.
**abtop compatibility:** `abtop --setup` points `statusLine` at its own
`~/.claude/abtop-statusline.sh`, which only records rate limits and prints nothing, so the
bar goes blank. `statusline.sh` calls that hook itself when it exists, so abtop keeps working.
If the bar goes blank after running `abtop --setup`, re-run `./setup.sh` (repo settings win
on merge) or set `statusLine.command` back to `$HOME/.claude/statusline.sh`.
To customize it, edit `config/statusline.sh`. It reads the session JSON on stdin
(`workspace.current_dir`, `model.display_name`, `context_window.used_percentage`, …)
and prints one line. You can test it without a session:
```sh
echo '{"model":{"display_name":"Opus"},"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":42}}' \
  | ~/.claude/statusline.sh
```
## graphify Knowledge Graph

Makes Claude navigate a knowledge graph instead of grepping raw files, keeps that graph fresh
automatically, and reports drift between design docs and implementation.

Opt-in **per repo** — sibling repos are unaffected:

```sh
cd <repo>
/graphify . --mode deep                       # build the graph (semantic pass included)
graphify claude install                       # CLAUDE.md + PreToolUse hook
git config core.hooksPath ~/.claude/graphify/hooks
```

What you get:

| | |
|---|---|
| `post-commit` / `post-checkout` | graph refreshes itself (~6s, AST-only, no API cost) |
| `git worktree add` | new worktree inherits the base graph and extends it — no manual step |
| `bin/graph-sync.sh` | refresh the main checkout after a PR merges on the remote |
| `bin/design-sync.py` | advisory design ↔ implementation drift report |

Two traps worth knowing before you enable it:

- **`core.hooksPath` disables `~/.git-hooks` entirely.** If you keep a global `pre-push` guard
  there, it is silently disarmed. `hooks/pre-push` delegates back to it — keep that delegation.
- **AST extraction produces zero doc↔code edges.** A graph can look healthy (large node count,
  docs indexed) while being unable to answer a single design-drift question. Only the semantic
  pass creates those edges — verify it landed rather than assuming.
- **graphify ignores your global gitignore.** Without a per-repo `.graphifyignore`, it indexes
  `.claude/`, `node_modules/` and `target/` and the graph fills with noise — silently.

Full guide, including verification steps: **[config/graphify/README.md](config/graphify/README.md)**

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

**Status line blank:** Another tool (e.g. `abtop --setup`) replaced `statusLine` in `~/.claude/settings.json`. Re-run `./setup.sh`. Also make sure `jq` is installed. **Boxes instead of icons:** set a Nerd Font as the terminal font.

**Backup files:** Backups are created as `<filename>.backup.<timestamp>` next to the original file. Safe to delete old ones.

## Uninstalling

```sh
# Remove symlinks and restore backups (or just delete symlinks)
for f in ~/.claude/CLAUDE.md ~/.claude/rules/rust.md ~/.claude/rules/scala-zio.md \
         ~/.claude/agents/*/AGENT.md ~/.claude/agents/*.md \
         ~/.claude/hooks/* ~/.claude/skills/*/SKILL.md ~/.claude/statusline.sh; do
    [ -L "$f" ] && rm "$f"
done

# Optionally remove MCP binaries
cargo uninstall cargo-mcp rust-analyzer-mcp
```
