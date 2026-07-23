#!/usr/bin/env python3
"""Report how much graphify is actually being used, and whether the feedback loop is closing.

    graphify-stats.py [project-dir]

Reads three sources, all local:

  graphify-out/telemetry/usage.jsonl  written by hook-usage.py on every search/read
  graphify-out/memory/*.md            written by `graphify save-result`
  graphify-out/cost.json              written by extraction runs

The usage log is the only source with a real denominator: graph queries measured
against the raw greps and reads that happened anyway. `graphify benchmark` models
savings against reading the whole corpus, which nothing ever does — treat that as
an upper bound and this as the floor.
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# save-result and reflect write to the graph rather than read from it; they are
# feedback, not retrieval, so they stay out of the graph-vs-raw ratio.
READ_SUBCOMMANDS = {"query", "explain", "path", "affected", "god-nodes"}

FRONTMATTER_FIELD = re.compile(r'^(\w+):\s*"?([^"\n]*)"?\s*$', re.MULTILINE)


def load_usage(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn concurrent append; skip the line, keep the rest
        if isinstance(record, dict):
            records.append(record)
    return records


def load_memory(memory_dir: Path) -> list[dict]:
    if not memory_dir.is_dir():
        return []
    out = []
    for md in sorted(memory_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = text.split("---", 2)
        fields = dict(FRONTMATTER_FIELD.findall(head[1] if len(head) > 2 else text))
        out.append(fields)
    return out


def pct(numerator: int, denominator: int) -> str:
    return f"{100.0 * numerator / denominator:.0f}%" if denominator else "n/a"


def bar(value: int, total: int, width: int = 24) -> str:
    filled = round(width * value / total) if total else 0
    return "█" * filled + "·" * (width - filled)


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    out = root / "graphify-out"
    if not out.is_dir():
        print(f"no graphify-out/ under {root}", file=sys.stderr)
        return 1

    usage = load_usage(out / "telemetry" / "usage.jsonl")
    memory = load_memory(out / "memory")

    print(f"graphify usage — {root.name}")
    print("─" * 52)

    if not usage:
        print("  no usage logged yet (hook-usage.py records on each search/read)")
    else:
        classes = Counter(r.get("cls", "") for r in usage)
        subs = Counter(r.get("sub", "") for r in usage if r.get("cls") == "graph")
        sessions = {r.get("session") for r in usage if r.get("session")}
        stamps = sorted(r["ts"] for r in usage if r.get("ts"))

        graph_reads = sum(subs[s] for s in READ_SUBCOMMANDS)
        raw_search = classes["raw_search"]
        raw_read = classes["raw_read"]
        raw_glob = classes["raw_glob"]
        contested = graph_reads + raw_search

        span = f"{stamps[0][:10]} → {stamps[-1][:10]}" if stamps else "n/a"
        print(f"  window:        {span}   ({len(sessions)} sessions, {len(usage)} calls)")
        print()
        print(f"  graph reads    {bar(graph_reads, contested)}  {graph_reads}")
        print(f"  raw searches   {bar(raw_search, contested)}  {raw_search}")
        print(f"  → graph-first share of searches: {pct(graph_reads, contested)}")
        print()
        print(f"  raw file reads {raw_read}    raw globs {raw_glob}")
        nudges = sum(1 for r in usage if r.get("nudged") and r.get("cls") != "graph")
        print(f"  guard nudges issued: {nudges}")

        if subs:
            breakdown = "  ".join(
                f"{name} {count}" for name, count in subs.most_common() if name
            )
            print(f"  by subcommand: {breakdown}")

        hot = Counter(
            r.get("target", "") for r in usage if r.get("cls") == "raw_read"
        ).most_common(8)
        if hot:
            print()
            print("  most-read raw files (repeat reads = candidate graph gaps):")
            for target, count in hot:
                print(f"    {count:>3}x  {target}")

    print()
    print("feedback loop")
    print("─" * 52)
    if not memory:
        print("  no outcomes recorded — `graphify reflect` has nothing to aggregate")
    else:
        outcomes = Counter(f.get("outcome", "unset") for f in memory)
        for name in ("useful", "dead_end", "corrected", "unset"):
            if outcomes.get(name):
                print(f"  {name:<10} {outcomes[name]}")
        graph_reads = sum(
            1 for r in usage
            if r.get("cls") == "graph" and r.get("sub") in READ_SUBCOMMANDS
        )
        if graph_reads:
            print(f"  coverage: {len(memory)} outcomes / {graph_reads} graph reads "
                  f"= {pct(len(memory), graph_reads)}")
        corrective = outcomes.get("dead_end", 0) + outcomes.get("corrected", 0)
        if corrective == 0 and len(memory) >= 5:
            print("  note: no dead_end/corrected records — a graph that only hears")
            print("        about its wins never improves. Record the misses too.")

    cost_file = out / "cost.json"
    if cost_file.is_file():
        try:
            cost = json.loads(cost_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cost = None
        if isinstance(cost, dict):
            runs = cost.get("runs") or []
            total_in = cost.get("total_input_tokens", 0)
            print()
            print("build cost")
            print("─" * 52)
            print(f"  {len(runs)} extraction run(s), {total_in:,} input tokens")
            if runs and isinstance(runs[-1], dict):
                last = runs[-1]
                print(f"  last: {str(last.get('date', ''))[:10]}  "
                      f"{last.get('files', '?')} files")
    print()
    print("  `graphify benchmark` models savings vs reading the whole corpus.")
    print("  The share above is the honest floor: graph vs the greps you still ran.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
