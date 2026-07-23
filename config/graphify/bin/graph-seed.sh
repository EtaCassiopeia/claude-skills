#!/bin/sh
# Seed a freshly created worktree with the main checkout's knowledge graph, then
# extend it for that worktree's own branch.
#
# This is the "keep the base graph and extend it in the new worktree" step. Without
# it every `/fix-issue` and `/ship-issues` worktree would start with no graph at all
# (graphify-out/ is gitignored, so `git worktree add` never materialises it) and the
# first query in that worktree would silently fall back to grepping raw files.
#
# Invoked automatically by the post-checkout hook on `git worktree add`. Safe to run
# by hand and safe to run twice.

set -u

. "${GRAPHIFY_HOME:-$HOME/.claude/graphify}/lib/common.sh"

graphify_enabled || exit 0

ROOT=$(graphify_repo_root) || exit 0
MAIN=$(graphify_main_checkout) || exit 0

# Not a worktree (plain clone, or the main checkout itself): there is no base graph
# to inherit. Building one from scratch is a deliberate, expensive act — never
# something a checkout should trigger behind the user's back.
[ "$ROOT" != "$MAIN" ] || exit 0

# No base graph to inherit — this repo simply isn't using graphify.
[ -d "$MAIN/graphify-out" ] || exit 0

if [ ! -d "$ROOT/graphify-out" ]; then
    # -c asks APFS for a copy-on-write clone: the 41 MB graph + cache costs
    # near-zero time and near-zero disk. Falls back to a real copy elsewhere.
    if ! cp -Rc "$MAIN/graphify-out" "$ROOT/graphify-out" 2>/dev/null; then
        if ! cp -R "$MAIN/graphify-out" "$ROOT/graphify-out" 2>/dev/null; then
            graphify_log "seed FAILED: could not copy $MAIN/graphify-out -> $ROOT"
            exit 0
        fi
    fi

    # Repoint the scan root at THIS worktree. Skipping this is the subtle failure
    # mode: graphify would keep re-extracting the main checkout's files while
    # writing results into the worktree's graph, and the two would drift apart
    # while both looked healthy.
    printf '%s\n' "$ROOT" > "$ROOT/graphify-out/.graphify_root"
fi

# Extend the inherited graph with whatever this branch actually changed. The copied
# cache is content-addressed, so this is close to a no-op on a fresh branch.
graphify_refresh

exit 0
