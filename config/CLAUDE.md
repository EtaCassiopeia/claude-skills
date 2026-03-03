# Global Claude Code Instructions

## Coding Philosophy

- Prefer simplicity over cleverness — code is read far more than written
- No over-engineering: solve the problem at hand, not hypothetical future ones
- Make invalid states unrepresentable through types
- Errors are values — handle them explicitly, don't swallow or log-and-ignore
- Write tests for behavior, not implementation details
- Every public API should have a clear contract

## Language-Specific Rules

Detailed rules are in `~/.claude/rules/`:
- **Rust**: `rust.md` — error handling, ownership, async patterns, clippy config
- **Scala 3 / ZIO 2**: `scala-zio.md` — Scala 3 syntax, Service Pattern 2.0, typed errors

## Available Agents

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `architect` | System design & architecture | Design decisions, module organization, dependency graphs |
| `developer` | Implementation | Writing idiomatic code, feature implementation |
| `reviewer` | Code review | Quality checks, security review, idiom compliance |
| `tester` | Test engineering | Writing tests, coverage analysis, property-based testing |

## Available Skills

- `/rust-check` — Run full Rust verification pipeline (fmt, clippy, test, deny)
- `/scala-check` — Run full Scala verification pipeline (compile, scalafmt, test)

## Build & Verify Commands

### Rust Projects

```sh
cargo fmt
cargo clippy -- -D warnings
cargo test
cargo deny check  # if configured
```

### Scala / ZIO Projects

```sh
sbt compile
sbt scalafmtCheckAll
sbt test
```

Always run the appropriate verification pipeline before declaring implementation work complete.

## MCP Servers

### Rust

- `rust-analyzer-lsp` — Rust code intelligence (installed as plugin)
- `cargo-mcp` — Cargo commands as MCP tools (check, clippy, test, fmt, build, bench)
- `rust-analyzer-mcp` — Code intelligence: symbols, definitions, references, hover, diagnostics

### Scala: Metals MCP (Per-Project Setup)

Metals v1.6.5+ has a built-in MCP server using streamable HTTP transport.

**Option A — IDE already running (VS Code, Neovim):**

Configure in your Metals settings:
```json
{
  "metals.startMcpServer": true,
  "metals.defaultBspToBuildTool": true,
  "metals.mcpClient": "claude"
}
```
Metals auto-generates `.mcp.json` at project root. Claude Code discovers it on startup.

**Option B — Headless (no IDE):**

Use [jpablo/metals-standalone-client](https://github.com/jpablo/metals-standalone-client):
```sh
# Download pre-built macOS executable
curl -L -o metals-standalone-client \
  https://github.com/jpablo/metals-standalone-client/releases/latest/download/metals-standalone-client-macos-executable
chmod +x metals-standalone-client
./metals-standalone-client /path/to/your/scala/project
```
Keep running in background. It writes `.mcp.json` at project root for Claude Code.

**Requirements:** Java 11+, Metals v1.6.5+ (for streamable HTTP, not SSE).

## Conventions

- Commit messages: imperative mood, concise, explain "why" not "what"
- Branch naming: `feat/`, `fix/`, `refactor/`, `test/` prefixes
- Never commit secrets, `.env` files, or credentials
- The global git hook at `~/.git-hooks/pre-push` blocks pushes with "Claude" in commit messages — respect this by not including Claude attribution in commit message bodies (Co-Authored-By trailers are fine when explicitly requested)
