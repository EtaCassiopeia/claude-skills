#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Claude Code Config — Idempotent Setup Script
#
# Symlinks config files into ~/.claude/, merges settings, registers MCP servers,
# and installs required binaries. Safe to re-run after git pull.
# ==============================================================================

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$REPO_DIR/config"
CLAUDE_DIR="$HOME/.claude"
CLAUDE_JSON="$HOME/.claude.json"

# Colors (only if terminal supports them)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    GREEN='' YELLOW='' RED='' BOLD='' RESET=''
fi

ok()   { printf "${GREEN}[OK]${RESET}    %s\n" "$1"; }
skip() { printf "${YELLOW}[SKIP]${RESET}  %s\n" "$1"; }
fail() { printf "${RED}[FAIL]${RESET}  %s\n" "$1"; }
info() { printf "${BOLD}[INFO]${RESET}  %s\n" "$1"; }
step() { printf "\n${BOLD}==> %s${RESET}\n" "$1"; }

ERRORS=0

# ==============================================================================
# 1. Preflight checks
# ==============================================================================
step "Preflight checks"

check_cmd() {
    if command -v "$1" &>/dev/null; then
        ok "$1 found: $(command -v "$1")"
    else
        fail "$1 not found — $2"
        ERRORS=$((ERRORS + 1))
    fi
}

check_cmd claude "Install Claude Code first: https://docs.anthropic.com/en/docs/claude-code"
check_cmd cargo  "Install Rust toolchain: https://rustup.rs"
check_cmd python3 "python3 is required for JSON merging"

if [ ! -d "$CLAUDE_DIR" ]; then
    fail "~/.claude/ does not exist — run Claude Code at least once first"
    ERRORS=$((ERRORS + 1))
else
    ok "~/.claude/ exists"
fi

if [ "$ERRORS" -gt 0 ]; then
    printf "\n${RED}Preflight failed with %d error(s). Fix the above and re-run.${RESET}\n" "$ERRORS"
    exit 1
fi

# ==============================================================================
# 2. Create directories
# ==============================================================================
step "Creating directories"

dirs=(
    "$CLAUDE_DIR/rules"
    "$CLAUDE_DIR/agents/architect"
    "$CLAUDE_DIR/agents/developer"
    "$CLAUDE_DIR/agents/reviewer"
    "$CLAUDE_DIR/agents/tester"
    "$CLAUDE_DIR/skills/rust-check"
    "$CLAUDE_DIR/skills/scala-check"
    "$CLAUDE_DIR/skills/scala3-best-practices"
    "$CLAUDE_DIR/skills/zio-best-practices"
    "$CLAUDE_DIR/skills/fp-patterns"
    "$CLAUDE_DIR/skills/fp-advanced"
    "$CLAUDE_DIR/skills/scala-typelevel"
    "$CLAUDE_DIR/skills/cats-ecosystem"
)

for dir in "${dirs[@]}"; do
    mkdir -p "$dir"
done
ok "All directories ensured"

# ==============================================================================
# 3. Symlink config files
# ==============================================================================
step "Symlinking config files"

# symlink_file <source_in_repo> <target_under_home>
symlink_file() {
    local src="$1"
    local dst="$2"

    if [ ! -f "$src" ]; then
        fail "Source missing: $src"
        ERRORS=$((ERRORS + 1))
        return
    fi

    # Already correct symlink
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
        skip "Already linked: $dst"
        return
    fi

    # Existing regular file — back up
    if [ -f "$dst" ] && [ ! -L "$dst" ]; then
        local backup="${dst}.backup.$(date +%s)"
        mv "$dst" "$backup"
        info "Backed up: $dst -> $backup"
    fi

    # Wrong symlink — remove
    if [ -L "$dst" ]; then
        rm "$dst"
    fi

    ln -s "$src" "$dst"
    ok "Linked: $dst -> $src"
}

symlink_file "$CONFIG_DIR/CLAUDE.md"                         "$CLAUDE_DIR/CLAUDE.md"
symlink_file "$CONFIG_DIR/rules/rust.md"                     "$CLAUDE_DIR/rules/rust.md"
symlink_file "$CONFIG_DIR/rules/scala-zio.md"                "$CLAUDE_DIR/rules/scala-zio.md"
symlink_file "$CONFIG_DIR/agents/architect/AGENT.md"         "$CLAUDE_DIR/agents/architect/AGENT.md"
symlink_file "$CONFIG_DIR/agents/developer/AGENT.md"         "$CLAUDE_DIR/agents/developer/AGENT.md"
symlink_file "$CONFIG_DIR/agents/reviewer/AGENT.md"          "$CLAUDE_DIR/agents/reviewer/AGENT.md"
symlink_file "$CONFIG_DIR/agents/tester/AGENT.md"            "$CLAUDE_DIR/agents/tester/AGENT.md"
symlink_file "$CONFIG_DIR/skills/rust-check/SKILL.md"              "$CLAUDE_DIR/skills/rust-check/SKILL.md"
symlink_file "$CONFIG_DIR/skills/scala-check/SKILL.md"             "$CLAUDE_DIR/skills/scala-check/SKILL.md"
symlink_file "$CONFIG_DIR/skills/scala3-best-practices/SKILL.md"   "$CLAUDE_DIR/skills/scala3-best-practices/SKILL.md"
symlink_file "$CONFIG_DIR/skills/zio-best-practices/SKILL.md"      "$CLAUDE_DIR/skills/zio-best-practices/SKILL.md"
symlink_file "$CONFIG_DIR/skills/fp-patterns/SKILL.md"             "$CLAUDE_DIR/skills/fp-patterns/SKILL.md"
symlink_file "$CONFIG_DIR/skills/fp-advanced/SKILL.md"             "$CLAUDE_DIR/skills/fp-advanced/SKILL.md"
symlink_file "$CONFIG_DIR/skills/scala-typelevel/SKILL.md"         "$CLAUDE_DIR/skills/scala-typelevel/SKILL.md"
symlink_file "$CONFIG_DIR/skills/cats-ecosystem/SKILL.md"          "$CLAUDE_DIR/skills/cats-ecosystem/SKILL.md"
symlink_file "$CONFIG_DIR/rules/scala-typelevel.md"                "$CLAUDE_DIR/rules/scala-typelevel.md"

# ==============================================================================
# 4. Merge settings.json (deep merge — repo values win, extras preserved)
# ==============================================================================
step "Merging settings.json"

python3 - "$CONFIG_DIR/settings.json" "$CLAUDE_DIR/settings.json" <<'PYEOF'
import json, sys, shutil, time
from pathlib import Path

def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. Override values win for conflicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # For lists, union them (preserving order, deduplicating)
            seen = set()
            merged = []
            for item in value + result[key]:
                item_key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item)
                if item_key not in seen:
                    seen.add(item_key)
                    merged.append(item)
            result[key] = merged
        else:
            result[key] = value
    return result

repo_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])

repo_settings = json.loads(repo_path.read_text())

if target_path.exists():
    target_settings = json.loads(target_path.read_text())
    merged = deep_merge(target_settings, repo_settings)
    if merged == target_settings:
        print("[SKIP]  settings.json already up to date")
        sys.exit(0)
    # Back up before overwriting
    backup = target_path.with_suffix(f".json.backup.{int(time.time())}")
    shutil.copy2(target_path, backup)
    print(f"[INFO]  Backed up: {target_path} -> {backup}")
else:
    merged = repo_settings

target_path.write_text(json.dumps(merged, indent=2) + "\n")
print(f"[OK]    Merged settings.json ({len(merged)} top-level keys)")
PYEOF

# ==============================================================================
# 5. Register MCP servers in ~/.claude.json
# ==============================================================================
step "Registering MCP servers"

python3 - "$CONFIG_DIR/mcp-servers.json" "$CLAUDE_JSON" <<'PYEOF'
import json, sys, shutil, time
from pathlib import Path

repo_mcp_path = Path(sys.argv[1])
claude_json_path = Path(sys.argv[2])

repo_mcp = json.loads(repo_mcp_path.read_text())

if not claude_json_path.exists():
    print("[FAIL]  ~/.claude.json not found — run Claude Code at least once first")
    sys.exit(1)

data = json.loads(claude_json_path.read_text())
existing_mcp = data.get("mcpServers", {})

# Check if all entries already present and identical
needs_update = False
for name, config in repo_mcp.items():
    if name not in existing_mcp or existing_mcp[name] != config:
        needs_update = True
        break

if not needs_update:
    print("[SKIP]  MCP servers already registered")
    sys.exit(0)

# Back up
backup = claude_json_path.with_suffix(f".json.backup.{int(time.time())}")
shutil.copy2(claude_json_path, backup)
print(f"[INFO]  Backed up: {claude_json_path} -> {backup}")

# Merge — only touch mcpServers key
existing_mcp.update(repo_mcp)
data["mcpServers"] = existing_mcp

claude_json_path.write_text(json.dumps(data, indent=2) + "\n")
print(f"[OK]    Registered {len(repo_mcp)} MCP server(s): {', '.join(repo_mcp.keys())}")
PYEOF

# ==============================================================================
# 6. Install MCP binaries
# ==============================================================================
step "Installing MCP binaries"

install_cargo_bin() {
    local crate="$1"
    if command -v "$crate" &>/dev/null; then
        skip "$crate already installed: $(command -v "$crate")"
    else
        info "Installing $crate (this may take a few minutes)..."
        if cargo install "$crate" 2>&1 | tail -3; then
            ok "$crate installed"
        else
            fail "Failed to install $crate"
            ERRORS=$((ERRORS + 1))
        fi
    fi
}

install_cargo_bin cargo-mcp
install_cargo_bin rust-analyzer-mcp

# ==============================================================================
# 7. Verification
# ==============================================================================
step "Verification"

verify_symlink() {
    local path="$1"
    local expected="$2"
    if [ -L "$path" ] && [ "$(readlink "$path")" = "$expected" ]; then
        ok "Symlink OK: $path"
    else
        fail "Symlink broken: $path"
        ERRORS=$((ERRORS + 1))
    fi
}

verify_symlink "$CLAUDE_DIR/CLAUDE.md"                        "$CONFIG_DIR/CLAUDE.md"
verify_symlink "$CLAUDE_DIR/rules/rust.md"                    "$CONFIG_DIR/rules/rust.md"
verify_symlink "$CLAUDE_DIR/rules/scala-zio.md"               "$CONFIG_DIR/rules/scala-zio.md"
verify_symlink "$CLAUDE_DIR/agents/architect/AGENT.md"        "$CONFIG_DIR/agents/architect/AGENT.md"
verify_symlink "$CLAUDE_DIR/agents/developer/AGENT.md"        "$CONFIG_DIR/agents/developer/AGENT.md"
verify_symlink "$CLAUDE_DIR/agents/reviewer/AGENT.md"         "$CONFIG_DIR/agents/reviewer/AGENT.md"
verify_symlink "$CLAUDE_DIR/agents/tester/AGENT.md"           "$CONFIG_DIR/agents/tester/AGENT.md"
verify_symlink "$CLAUDE_DIR/skills/rust-check/SKILL.md"              "$CONFIG_DIR/skills/rust-check/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/scala-check/SKILL.md"             "$CONFIG_DIR/skills/scala-check/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/scala3-best-practices/SKILL.md"   "$CONFIG_DIR/skills/scala3-best-practices/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/zio-best-practices/SKILL.md"      "$CONFIG_DIR/skills/zio-best-practices/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/fp-patterns/SKILL.md"             "$CONFIG_DIR/skills/fp-patterns/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/fp-advanced/SKILL.md"             "$CONFIG_DIR/skills/fp-advanced/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/scala-typelevel/SKILL.md"         "$CONFIG_DIR/skills/scala-typelevel/SKILL.md"
verify_symlink "$CLAUDE_DIR/skills/cats-ecosystem/SKILL.md"          "$CONFIG_DIR/skills/cats-ecosystem/SKILL.md"
verify_symlink "$CLAUDE_DIR/rules/scala-typelevel.md"                "$CONFIG_DIR/rules/scala-typelevel.md"

# Verify settings keys
python3 -c "
import json, sys
s = json.load(open('$CLAUDE_DIR/settings.json'))
required = ['enabledPlugins', 'hooks', 'permissions']
missing = [k for k in required if k not in s]
if missing:
    print(f'[FAIL]  settings.json missing keys: {missing}')
    sys.exit(1)
print(f'[OK]    settings.json has all required keys: {required}')
"

# Verify MCP registrations
python3 -c "
import json, sys
d = json.load(open('$CLAUDE_JSON'))
mcp = d.get('mcpServers', {})
required = ['cargo-mcp', 'rust-analyzer-mcp']
missing = [k for k in required if k not in mcp]
if missing:
    print(f'[FAIL]  MCP servers missing: {missing}')
    sys.exit(1)
print(f'[OK]    MCP servers registered: {required}')
"

# Verify binaries
for bin in cargo-mcp rust-analyzer-mcp; do
    if command -v "$bin" &>/dev/null; then
        ok "Binary found: $bin"
    else
        fail "Binary not found: $bin"
        ERRORS=$((ERRORS + 1))
    fi
done

# ==============================================================================
# Summary
# ==============================================================================
printf "\n"
if [ "$ERRORS" -gt 0 ]; then
    printf "${RED}${BOLD}Setup completed with %d error(s). Review the output above.${RESET}\n" "$ERRORS"
    exit 1
else
    printf "${GREEN}${BOLD}Setup complete! All checks passed.${RESET}\n"
    printf "\nStart a new Claude Code session to pick up the changes.\n"
fi
