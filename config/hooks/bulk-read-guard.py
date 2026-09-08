#!/usr/bin/env python3
"""
PreToolUse hook: blocks whole-file reads of large files and redirects Claude
to delegate the read to the `bulk-reader` Haiku subagent.

Registered on both Read and Bash: in bypass-permissions mode Claude reads with
`cat`, so a Read-only guard would be bypassed most of the time.

Escape hatches (a gate with no exit deadlocks editing, and would trap the
bulk-reader subagent reading the very files it was handed):
  - Read with offset/limit  -> allowed (targeted read)
  - second request for the same path within TTL -> allowed
  - piped or redirected Bash -> allowed (output is already reduced)
  - BULKREAD_OFF=1 -> disabled

Env: BULKREAD_MIN_LINES (800), BULKREAD_MAX_BYTES (60000), BULKREAD_TTL (3600)
"""
import sys, json, os, shlex, hashlib, time, tempfile

def env_int(name, default):
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return default

MIN_LINES = env_int("BULKREAD_MIN_LINES", 800)
MAX_BYTES = env_int("BULKREAD_MAX_BYTES", 60000)
TTL       = env_int("BULKREAD_TTL", 3600)

STATE_DIR = os.path.join(tempfile.gettempdir(), "claude-bulk-read-guard")


def allow():
    """Exit 0 with no output: no decision, normal permission flow continues."""
    sys.exit(0)


def seen_recently(path):
    """True if this path was already denied within TTL. Records it either way."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        key = hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:16]
        marker = os.path.join(STATE_DIR, key)
        now = time.time()
        if os.path.exists(marker) and now - os.path.getmtime(marker) < TTL:
            return True
        with open(marker, "w") as f:
            f.write(path)
        return False
    except OSError:
        # Cannot track state -> cannot offer the escape hatch -> do not block.
        return True


def too_big(path):
    """(is_big, lines, bytes) for an existing regular file, else (False, 0, 0)."""
    try:
        if not os.path.isfile(path):
            return False, 0, 0
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(MAX_BYTES + 1)
            if b"\0" in head:          # binary: Read/cat will fail or is intentional
                return False, 0, 0
            lines = head.count(b"\n")
            if size <= len(head):
                pass
            else:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    lines += chunk.count(b"\n")
        return (lines > MIN_LINES or size > MAX_BYTES), lines, size
    except OSError:
        return False, 0, 0


def deny(path, lines, size):
    reason = (
        f"Whole-file read of {path} blocked: {lines} lines / {size} bytes "
        f"(thresholds: {MIN_LINES} lines, {MAX_BYTES} bytes).\n\n"
        "Delegate this read instead of spending main-context tokens on it:\n\n"
        "  Agent(subagent_type=\"bulk-reader\", prompt=\"<your question>\\n"
        "Files:\\n" + path + "\")\n\n"
        "Batch every file you need into ONE bulk-reader call and ask a specific "
        "question; it returns structured bullets, not file contents.\n\n"
        "If you need exact content (editing, line numbers), re-read with "
        "offset/limit for just the section — or re-issue this exact same read "
        "and it will be allowed through the second time. Subagents: re-issue "
        "the same read to proceed."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def check(path, cwd):
    if not path:
        allow()
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    path = os.path.normpath(path)
    big, lines, size = too_big(path)
    if not big:
        allow()
    if seen_recently(path):
        allow()
    deny(path, lines, size)


def bash_targets(cmd):
    """Whole-file read targets in a Bash command. Conservative by design."""
    # A pipe or redirect means the output is already being reduced or written.
    if any(t in cmd for t in ("|", ">", "<", "$(", "`")):
        return []
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return []
    if not tokens:
        return []

    name = os.path.basename(tokens[0])
    args = tokens[1:]

    if name == "cat":
        # Any non-flag argument is a file being read in full.
        return [a for a in args if not a.startswith("-")]

    if name in ("head", "tail"):
        # Bounded to 10 lines unless -n asks for more than the threshold.
        n = None
        for i, a in enumerate(args):
            if a == "-n" and i + 1 < len(args):
                n = args[i + 1]
            elif a.startswith("-n") and len(a) > 2:
                n = a[2:]
        if n is None:
            return []
        try:
            if int(n.lstrip("+-")) <= MIN_LINES:
                return []
        except ValueError:
            return []
        return [a for a in args if not a.startswith("-") and a != n]

    return []


def main():
    if os.environ.get("BULKREAD_OFF"):
        allow()
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()

    if tool == "Read":
        if ti.get("offset") or ti.get("limit"):
            allow()
        check(ti.get("file_path", ""), cwd)

    elif tool == "Bash":
        for target in bash_targets(ti.get("command", "")):
            check(target, cwd)

    allow()


if __name__ == "__main__":
    main()
