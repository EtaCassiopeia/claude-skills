#!/bin/sh
# Refresh the MAIN checkout's knowledge graph after work has landed on the remote.
#
# Why this exists: PRs merge on GitHub, so nothing happens locally — the main
# checkout's HEAD never moves and no git hook ever fires. This is the one point in
# the loop that hooks genuinely cannot cover, so it is an explicit command.
#
# Run it after a PR merges (i.e. after /ship-issues 1g or /fix-issue Phase 8), or
# any time the graph feels behind.
#
# Usage: graph-sync.sh [repo-path]      (defaults to the current repo)

set -u

. "${GRAPHIFY_HOME:-$HOME/.claude/graphify}/lib/common.sh"

if ! graphify_enabled; then
    echo "graphify unavailable or disabled (GRAPHIFY_DISABLE=1) — nothing to do." >&2
    exit 0
fi

if [ $# -gt 0 ]; then
    cd "$1" || exit 1
fi

MAIN=$(graphify_main_checkout) || { echo "not a git repository" >&2; exit 1; }
cd "$MAIN" || exit 1

if [ ! -d "$MAIN/graphify-out" ]; then
    echo "No graphify-out/ in $MAIN — run /graphify to build the graph first." >&2
    exit 0
fi

echo "Syncing knowledge graph for $MAIN"

# Pick up merged work. Fetch only: never move the user's HEAD or touch their branch.
git fetch --quiet --all --prune 2>/dev/null || true

graphify update . || echo "graph update failed — see $GRAPHIFY_LOG" >&2

# Merged work adds nodes, which shifts community membership. Name only the new
# communities; --missing-only keeps every existing curated label intact.
graphify label . --missing-only || echo "community labeling skipped" >&2

echo "Graph synced. Report: $MAIN/graphify-out/GRAPH_REPORT.md"
