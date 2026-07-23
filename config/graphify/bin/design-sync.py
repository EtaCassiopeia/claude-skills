#!/usr/bin/env python3
"""Advisory design <-> implementation drift report, read off the graphify graph.

Three questions, none of which the code or the docs can answer alone:

  --diff        I changed this code. Which design docs describe it, and therefore
                which ones might now be lying?
  (default)     Which design docs describe something nobody has built?
                Which built subsystems has nobody written down?

Advisory by construction: always exits 0. It reports drift; deciding what to do
about it is a judgement call that belongs to a person, not a script.

Two independent linkage sources, because each fails in a different direction:

  1. Graph edges from graphify's semantic pass (rationale_for, implements,
     conceptually_related_to, ...). Rich, but only as good as the extraction.
  2. Literal crate-name mentions in the doc text. Coarse, but deterministic and
     always available — so the report degrades to "useful" rather than "empty"
     when semantic edges are thin.

Usage:
  design-sync.py                          # drift report for the current repo
  design-sync.py --diff                   # docs affected by uncommitted changes
  design-sync.py --diff <ref>             # ... by changes since <ref>
  design-sync.py --diff <worktree-path>   # ... by that worktree's branch
  design-sync.py --all                    # include vendored code (noisy)
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

# Relations that carry design intent. Structural relations (contains, calls) are
# traversed too, but only to get from a changed FILE to its symbols.
SEMANTIC_RELATIONS = {
    "rationale_for",
    "implements",
    "conceptually_related_to",
    "semantically_similar_to",
    "cites",
    "references",
    "shares_data_with",
}

DOC_DIRS = ("docs/",)
FIRST_PARTY = ("crates/", "docs/", "tests/", "scripts/", "deploy/")

# Hub nodes (Vec, String, Result, ...) connect everything to everything. Expanding
# through them turns any traversal into "the whole graph is related", which is the
# same as saying nothing.
HUB_DEGREE = 60


def sh(args, cwd=None):
    try:
        out = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, check=False
        )
        return out.stdout.strip()
    except Exception:
        return ""


def load_graph(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def norm(src):
    """Graph source_file values may be absolute or relative depending on which pass
    produced them; compare on a repo-relative basis."""
    if not src:
        return ""
    src = src.replace("\\", "/")
    for marker in ("/rift-enterprise/", "/.claude/worktrees/"):
        if marker in src:
            src = src.split(marker, 1)[1]
            if marker == "/.claude/worktrees/" and "/" in src:
                src = src.split("/", 1)[1]
    return src.lstrip("./")


def is_doc(src):
    return src.endswith(".md") and any(src.startswith(d) for d in DOC_DIRS)


def is_code(node, src):
    return node.get("file_type") == "code" or src.endswith((".rs", ".py", ".ts", ".go"))


def first_party(src):
    return src and not src.startswith("vendor/")


def crate_of(src):
    m = re.match(r"(?:vendor/rift/)?crates/([a-z0-9-]+)/", src)
    return m.group(1) if m else None


def build_index(graph):
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    for n in nodes.values():
        n["_src"] = norm(n.get("source_file"))
    adj = defaultdict(list)
    for link in graph.get("links", graph.get("edges", [])):
        s, t, rel = link.get("source"), link.get("target"), link.get("relation")
        if s in nodes and t in nodes:
            adj[s].append((t, rel))
            adj[t].append((s, rel))
    return nodes, adj


def docs_reachable(start_ids, nodes, adj, max_depth=3):
    """BFS out to design docs, refusing to expand through hub nodes."""
    seen = set(start_ids)
    frontier = deque((i, 0) for i in start_ids)
    hits = defaultdict(set)  # doc file -> {relation}
    while frontier:
        nid, depth = frontier.popleft()
        if depth >= max_depth:
            continue
        if depth > 0 and len(adj[nid]) > HUB_DEGREE:
            continue
        for nxt, rel in adj[nid]:
            node = nodes.get(nxt)
            if node is None:
                continue
            src = node["_src"]
            if is_doc(src):
                hits[src].add(rel or "?")
                continue
            if nxt not in seen:
                seen.add(nxt)
                frontier.append((nxt, depth + 1))
    return hits


def changed_files(repo, ref):
    """Files changed in `repo`. With no ref, compare against the merge-base with the
    upstream default branch so a worktree reports its whole branch, not just what is
    still uncommitted."""
    if ref and not Path(ref).is_dir():
        base = ref
    else:
        base = ""
        for cand in ("origin/master", "origin/main"):
            mb = sh(["git", "merge-base", "HEAD", cand], cwd=repo)
            if mb:
                base = mb
                break
    files = set()
    if base:
        files |= set(sh(["git", "diff", "--name-only", base], cwd=repo).splitlines())
    files |= set(sh(["git", "diff", "--name-only", "HEAD"], cwd=repo).splitlines())
    files |= set(
        sh(["git", "diff", "--name-only", "--cached"], cwd=repo).splitlines()
    )
    return sorted(f for f in files if f)


def doc_crate_mentions(repo):
    """Literal `rift-*` crate mentions per doc file — the deterministic fallback."""
    out = defaultdict(set)
    docs_dir = Path(repo) / "docs"
    if not docs_dir.is_dir():
        return out
    for md in docs_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(md.relative_to(repo))
        for crate in set(re.findall(r"\brift-[a-z][a-z0-9-]*\b", text)):
            out[rel].add(crate)
    return out


def report_diff(repo, ref, nodes, adj):
    files = changed_files(repo, ref)
    code_files = [f for f in files if f.endswith((".rs", ".py", ".ts", ".go"))]
    if not files:
        print("No changes detected.")
        return

    print(f"Changed files: {len(files)} ({len(code_files)} code)\n")

    by_file = defaultdict(list)
    for nid, n in nodes.items():
        if n["_src"]:
            by_file[n["_src"]].append(nid)

    mentions = doc_crate_mentions(repo)
    crates_touched = {c for f in code_files if (c := crate_of(f))}

    all_docs = defaultdict(set)
    for f in code_files:
        starts = by_file.get(f, [])
        hits = docs_reachable(starts, nodes, adj) if starts else {}
        for doc, rels in hits.items():
            all_docs[doc] |= rels
        print(f"  {f}")
        if not starts:
            print("      (not in graph — run graph-sync.sh to refresh)")
        elif not hits:
            print("      no linked design docs")
        else:
            for doc, rels in sorted(hits.items(), key=lambda kv: -len(kv[1])):
                print(f"      -> {doc}  [{', '.join(sorted(rels))}]")
        print()

    # Deterministic layer: docs that name a crate we touched but which the graph
    # traversal did not surface.
    extra = {
        doc: crates & crates_touched
        for doc, crates in mentions.items()
        if crates & crates_touched and doc not in all_docs
    }
    if extra:
        print("Also mention a crate you touched (name match, no graph edge):")
        for doc, crates in sorted(extra.items()):
            print(f"  {doc}  [{', '.join(sorted(crates))}]")
        print()

    total = len(all_docs) + len(extra)
    if total:
        print(f"REVIEW {total} design doc(s) above for drift before shipping.")
    else:
        print("No design docs linked to these changes.")


def report_drift(repo, nodes, adj, labels, include_vendor):
    doc_files = defaultdict(list)
    code_by_comm = defaultdict(list)
    doc_comms = set()

    for nid, n in nodes.items():
        src = n["_src"]
        if not src:
            continue
        if not include_vendor and not first_party(src):
            continue
        if is_doc(src):
            doc_files[src].append(nid)
            if n.get("community") is not None:
                doc_comms.add(n["community"])
        elif is_code(n, src):
            if n.get("community") is not None:
                code_by_comm[n["community"]].append(nid)

    print("=== UNIMPLEMENTED — design docs with no reachable code ===\n")
    unimpl = []
    for doc, ids in sorted(doc_files.items()):
        reached = False
        seen = set(ids)
        frontier = deque((i, 0) for i in ids)
        while frontier and not reached:
            nid, depth = frontier.popleft()
            if depth >= 3:
                continue
            if depth > 0 and len(adj[nid]) > HUB_DEGREE:
                continue
            for nxt, _rel in adj[nid]:
                node = nodes.get(nxt)
                if node is None:
                    continue
                if is_code(node, node["_src"]) and (
                    include_vendor or first_party(node["_src"])
                ):
                    reached = True
                    break
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append((nxt, depth + 1))
        if not reached:
            unimpl.append(doc)
    if unimpl:
        for doc in unimpl:
            print(f"  {doc}")
        print(f"\n  {len(unimpl)} doc(s) describe nothing the graph can find in code.")
        print("  Either the design is unbuilt, or the extraction missed the link.")
    else:
        print("  none — every design doc reaches code.")

    print("\n=== UNDOCUMENTED — code communities with no design doc ===\n")
    undoc = [
        (cid, ids) for cid, ids in code_by_comm.items()
        if cid not in doc_comms and len(ids) >= 8
    ]
    undoc.sort(key=lambda kv: -len(kv[1]))
    if undoc:
        for cid, ids in undoc[:15]:
            label = labels.get(str(cid), f"Community {cid}")
            example = nodes[ids[0]]["_src"]
            print(f"  [{len(ids):4d} nodes] {label}")
            print(f"               e.g. {example}")
        if len(undoc) > 15:
            print(f"\n  ... and {len(undoc) - 15} more (showing the 15 largest).")
    else:
        print("  none — every sizeable code community has a linked design doc.")

    if not include_vendor:
        print("\n(First-party only. Use --all to include vendor/.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diff", nargs="?", const="", metavar="REF|WORKTREE",
                    help="report design docs linked to changed code")
    ap.add_argument("--graph", help="path to graph.json")
    ap.add_argument("--all", action="store_true", help="include vendor/ code")
    args = ap.parse_args()

    repo = args.diff if (args.diff and Path(args.diff).is_dir()) else "."
    repo = sh(["git", "rev-parse", "--show-toplevel"], cwd=repo) or repo
    graph_path = Path(args.graph) if args.graph else Path(repo) / "graphify-out" / "graph.json"

    # An unseeded worktree has no graph of its own; the main checkout's graph still
    # describes the same code well enough to answer "which docs cover this file?".
    if not graph_path.exists() and not args.graph:
        common = sh(["git", "rev-parse", "--git-common-dir"], cwd=repo)
        if common:
            main = Path(common).resolve().parent
            if (main / "graphify-out" / "graph.json").exists():
                graph_path = main / "graphify-out" / "graph.json"

    if not graph_path.exists():
        print(f"No graph at {graph_path}", file=sys.stderr)
        print("Run /graphify to build one, or graph-sync.sh to refresh.", file=sys.stderr)
        return 0

    graph = load_graph(graph_path)
    nodes, adj = build_index(graph)

    labels = {}
    lp = graph_path.parent / ".graphify_labels.json"
    if lp.exists():
        try:
            labels = json.loads(lp.read_text(encoding="utf-8"))
        except ValueError:
            pass

    print(f"design-sync — {len(nodes)} nodes from {graph_path}\n")

    if args.diff is not None:
        report_diff(repo, args.diff, nodes, adj)
    else:
        report_drift(repo, nodes, adj, labels, args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
