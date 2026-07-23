#!/bin/sh
# Shared helpers for the graphify git hooks and scripts.
#
# Repo-agnostic on purpose: enabling this for another repo (rift, rift-java,
# rift-node, rift-scala, ...) is one command and nothing is copied per repo:
#
#   git -C <repo> config core.hooksPath /Users/gangof3/.claude/graphify/hooks
#
# Nothing here ever writes into the repository working tree except graphify-out/,
# which is generated output and stays gitignored.

GRAPHIFY_HOME="${GRAPHIFY_HOME:-$HOME/.claude/graphify}"

# Every hook that sources this file must survive graphify being absent, being
# disabled, or failing outright. A knowledge-graph problem must never fail a
# commit, a checkout, or a push.
graphify_enabled() {
    [ "${GRAPHIFY_DISABLE:-0}" = "1" ] && return 1
    command -v graphify >/dev/null 2>&1 || return 1
    return 0
}

# Absolute path of the working tree this hook is running in. For a worktree this
# is the worktree, not the main checkout.
graphify_repo_root() {
    git rev-parse --show-toplevel 2>/dev/null
}

# Absolute path of the MAIN checkout, derived from the common git dir that every
# worktree shares. In the main checkout this equals graphify_repo_root.
graphify_main_checkout() {
    common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
    case "$common" in
        /*) ;;
        *) common="$(pwd)/$common" ;;
    esac
    # .../<main>/.git -> <main>
    (cd "$(dirname "$common")" 2>/dev/null && pwd)
}

graphify_is_worktree() {
    root=$(graphify_repo_root) || return 1
    main=$(graphify_main_checkout) || return 1
    [ "$root" != "$main" ]
}

# Where hook runs leave their trace. Hooks must never fail a git operation, but
# "never fail" must not become "fail silently": a broken graphify invocation would
# otherwise look exactly like a healthy one forever. Failures land here.
#
# Deliberately OUTSIDE $GRAPHIFY_HOME: that directory is a symlink into the
# claude-skills repo, and a hook must never write into a git working tree.
GRAPHIFY_LOG="${GRAPHIFY_LOG:-$HOME/.claude/graphify-hook.log}"

graphify_log() {
    mkdir -p "$(dirname "$GRAPHIFY_LOG")" 2>/dev/null
    printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" >> "$GRAPHIFY_LOG" 2>/dev/null
}

# Refresh the graph for the working tree we are standing in. AST-only, no LLM,
# measured at ~6s on rift-enterprise (435 files) with a warm cache.
#
# No --no-viz here: `graphify update` rejects that flag (it belongs to cluster-only),
# and above 5000 nodes graphify skips graph.html on its own anyway.
graphify_refresh() {
    root=$(graphify_repo_root) || return 0
    [ -d "$root/graphify-out" ] || return 0
    out=$( cd "$root" && graphify update . 2>&1 )
    if [ $? -ne 0 ]; then
        graphify_log "refresh FAILED in $root: $(printf '%s' "$out" | tail -3 | tr '\n' ' ')"
    fi
    return 0
}
