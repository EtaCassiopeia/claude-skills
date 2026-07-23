#!/usr/bin/env python3
"""PreToolUse wrapper that logs graph-vs-raw tool usage, then delegates to `graphify hook-guard`.

Wiring (project .claude/settings.json):

    PreToolUse  Bash|Grep   -> hook-usage.py search
    PreToolUse  Read|Glob   -> hook-usage.py read

The wrapper reads the tool-call JSON from stdin, runs the real guard with the same
payload, appends one JSONL line to <project>/graphify-out/telemetry/usage.jsonl, and
writes the guard's stdout through verbatim so strict-mode permissionDecision payloads
survive unchanged.

Fails open without exception: any error anywhere still exits 0, and the guard's output
is forwarded even when logging dies. A tool call is never blocked by a bug in here.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Subcommands that read the graph instead of the raw tree. `save-result` is the
# feedback loop, not a read, but it is logged so coverage is measurable.
GRAPH_SUBCOMMANDS = (
    "query", "explain", "path", "affected", "god-nodes", "save-result", "reflect",
)
GRAPH_RE = re.compile(
    r"\bgraphify\s+(" + "|".join(re.escape(s) for s in GRAPH_SUBCOMMANDS) + r")\b"
)
# Same set the guard itself matches on, so `nudged` lines up with `raw_search` lines.
RAW_SEARCH_TOKENS = ("grep", "ripgrep", "rg ", "find ", "fd ", "ack ", "ag ")

MAX_TARGET_CHARS = 160


def graphify_bin() -> str:
    return os.environ.get("GRAPHIFY_BIN") or "/Users/gangof3/.local/bin/graphify"


def project_root(payload: dict) -> Path | None:
    """Nearest ancestor of the tool call's cwd that holds a graphify-out/ directory."""
    start = payload.get("cwd") or os.getcwd()
    try:
        here = Path(start).resolve()
    except Exception:
        return None
    for candidate in (here, *here.parents):
        if (candidate / "graphify-out").is_dir():
            return candidate
    return None


def classify(kind: str, tool: str, tool_input: dict) -> tuple[str, str, str] | None:
    """-> (class, subcommand, target), or None for calls not worth logging."""
    command = str(tool_input.get("command") or "")
    if kind == "search":
        if command:
            match = GRAPH_RE.search(command)
            if match:
                return "graph", match.group(1), command
            if any(tok in command for tok in RAW_SEARCH_TOKENS):
                return "raw_search", "", command
            return None  # ordinary shell command — not part of the ratio
        # Claude Code's Grep tool: a pattern and no command is a content search.
        pattern = str(tool_input.get("pattern") or "")
        if pattern:
            return "raw_search", "", pattern
        return None
    if kind == "read":
        file_path = str(tool_input.get("file_path") or "")
        if file_path:
            return "raw_read", "", file_path
        pattern = str(tool_input.get("pattern") or "")
        if pattern:
            return "raw_glob", "", pattern
    return None


def relativize(target: str, root: Path) -> str | None:
    """Project-relative path, or None when the target lies outside the project.

    Out-of-project reads are not graph gaps — the graph never covered them — so they
    are dropped rather than logged, matching the guard's own handling.
    """
    try:
        return str(Path(target).resolve().relative_to(root))
    except Exception:
        return None


def log(payload: dict, kind: str, nudged: bool) -> None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = payload if isinstance(payload, dict) else {}
    tool = str(payload.get("tool_name") or "")

    verdict = classify(kind, tool, tool_input)
    if verdict is None:
        return
    cls, sub, target = verdict

    root = project_root(payload)
    if root is None:
        return  # no graph here, nothing to measure against

    if cls == "raw_read":
        relative = relativize(target, root)
        if relative is None:
            return
        target = relative

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": str(payload.get("session_id") or "")[:8],
        "tool": tool,
        "cls": cls,
        "target": target[:MAX_TARGET_CHARS],
        "nudged": nudged,
    }
    if sub:
        record["sub"] = sub

    out_dir = root / "graphify-out" / "telemetry"
    out_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    # One write of a short line: concurrent hook processes append atomically on POSIX.
    with open(out_dir / "usage.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line)


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return 0

    guard_stdout = b""
    try:
        completed = subprocess.run(
            [graphify_bin(), "hook-guard", kind, *sys.argv[2:]],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        guard_stdout = completed.stdout or b""
    except Exception:
        guard_stdout = b""

    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
        if isinstance(payload, dict):
            log(payload, kind, nudged=bool(guard_stdout.strip()))
    except Exception:
        pass

    try:
        sys.stdout.buffer.write(guard_stdout)
        sys.stdout.buffer.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
