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
- `/scala3-best-practices` — Scala 3 syntax, type design, metaprogramming, anti-patterns (TRIGGER on .scala files)
- `/zio-best-practices` — ZIO 2 Service Pattern, error handling, concurrency, resources, testing (TRIGGER on ZIO imports)
- `/fp-patterns` — Algebraic design, typeclasses, effect composition, FP anti-patterns
- `/fp-advanced` — Category theory applied: ZIO Prelude typeclasses, Kleisli, natural transformations, Bifunctor/Contravariant/Profunctor, optics (Monocle), recursive schemes, Free monad / ZPure, typeclass laws
- `/scala-typelevel` — Advanced Scala 3 type system for library authors: variance, GADTs, type lambdas, match types, Mirror-based derivation, Magnolia, Shapeless 3, compiletime ops
- `/cats-ecosystem` — Cats Core typeclasses, Cats Effect 3 (IO/Resource/Ref/Deferred), FS2, Doobie, Http4s, Kyo, tagless final patterns

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

@RTK.md


# Sidecar — Running Blocked or Long Commands

When the sandbox blocks a Bash command, **do not ask the user to run it
manually** — route it through the local `claude-sidecar` instead.

## Decision tree

1. **Is it a long-running command** (`sbt`, `cargo`, `pytest`, `go test`, `mvn`,
   `gradle`)? → POST `http://localhost:8765/jobs` (job API — returns a job ID,
   then poll for lines).
2. **Is it any other allowlisted command** (`gh`, `git`, `go`, `npm`, `python3`,
   `curl`, `grep`, `find`, `jq`, `security`, …)? → POST `http://localhost:8765/exec` — buffered JSON response, 60s
   timeout.
3. **Is it a web page WebFetch can't read** (paywall, login wall, Cloudflare
   block) that the user's own browser can? → POST
   `http://localhost:8765/browser/fetch` (browser bridge — see below).
4. **Is the sidecar not running?** → start it with `claude-sidecar &`.

Allowed: gh, git, go, sbt, cargo, mvn, gradle, npm, node, python3, pytest, curl, docker, docker-compose, grep, rg, find, ls, cat, head, tail, wc, diff, sed, awk, sort, uniq, cut, tr, xargs, cp, mv, rm, mkdir, touch, chmod, jq, yq, which, env, printenv, echo, printf, date, uname, security

## POST /exec — short commands (< 60s)

```bash
curl -s -X POST http://localhost:8765/exec \
  -H 'Content-Type: application/json' \
  -d '{"cmd":"git","args":["status"],"cwd":"/path/to/repo"}'
# → {"stdout":"...","stderr":"...","exit_code":0}
```

## POST /jobs — long commands (create-then-poll)

```bash
# 1. Start job — returns immediately with a job ID
JOB=$(curl -s -X POST http://localhost:8765/jobs \
  -H 'Content-Type: application/json' \
  -d "{\"cmd\":\"sbt\",\"args\":[\"validate\"],\"cwd\":\"$PWD\",\"timeout_secs\":3600}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 2. Poll every 15s — print new lines, stop when done
FROM=0
for i in $(seq 1 40); do
  sleep 15
  POLL="$TMPDIR/sidecar-poll-$$.json"
  curl -s "http://localhost:8765/jobs/$JOB/lines?from=$FROM" > "$POLL"
  python3 - "$POLL" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
for l in d['lines']: print(l['text'])
open('/tmp/sc-from', 'w').write(str(d['next_from']))
sys.exit(0 if d['running'] else 1)
PYEOF
  RET=$?; FROM=$(cat /tmp/sc-from 2>/dev/null || echo 0)
  rm -f "$POLL" /tmp/sc-from
  [ $RET -ne 0 ] && break
done

# 3. Final status
curl -s "http://localhost:8765/jobs/$JOB/status"
```

## Browser bridge — pages behind paywalls/logins (macOS)

Fetches a page through the user's real Chrome (real profile + cookies) via
AppleScript. Use when WebFetch returns truncated/paywalled content the user
says their browser can see.

```bash
# Open URL in a new Chrome tab, wait for load, return rendered text, close tab
curl -s -X POST http://localhost:8765/browser/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://medium.com/some-article"}'
# → {"url":"…","title":"…","content":"rendered page text"}

# Read whatever tab the user currently has focused ("read this page")
curl -s http://localhost:8765/browser/tab
```

Options for `/browser/fetch`: `wait_secs` (default 20, cap 120), `format`
(`"text"` default | `"html"`), `keep_tab` (bool). Only `http(s)` URLs.
If it errors mentioning "Allow JavaScript from Apple Events" or Automation
permission, relay the fix from the error message to the user — both are
one-time manual Chrome/macOS settings.

## Health check

```bash
curl -s http://localhost:8765/health 2>/dev/null | grep -q ok && echo "up" || echo "down"
```
# graphify
- **graphify** (`~/.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.
