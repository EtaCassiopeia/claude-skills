# graphify integration

Wires [graphify](https://graphify.net) into a repo so Claude Code navigates a **knowledge
graph** instead of grepping raw files, and so **design docs and implementation stay in sync**
rather than drifting quietly.

Repo-agnostic: nothing here is specific to one project, and nothing is copied into a project's
working tree. Enabling a repo is one `git config` line.

---

## The problem this solves

A graph that exists is not a graph that gets used. Three things have to be true, and by default
none of them are:

1. **Claude has to know it exists.** Without a `CLAUDE.md` directive and a `PreToolUse` hook,
   every session greps raw files and the graph is decoration.
2. **It has to be fresh.** A graph built at some past commit quietly describes code that no
   longer exists — worse than no graph, because it looks authoritative.
3. **It has to include the docs.** AST extraction alone produces **zero** doc↔code edges. The
   design documents sit in the graph as an isolated island, so no question about design/code
   drift can be answered from it. Only graphify's semantic pass creates those edges.

Point 3 is the one that is easy to miss: `graphify update` happily indexes markdown and reports
a healthy-looking node count, while the edges that actually connect a design doc to the code
implementing it are all absent.

---

## Layout

```
config/graphify/
  lib/common.sh        shared helpers (repo/worktree resolution, refresh, logging)
  hooks/post-commit    refresh the graph after each commit
  hooks/post-checkout  seed a new worktree / refresh on branch switch
  hooks/pre-push       delegates to the global guard (see "Do not lose the guard")
  bin/graph-seed.sh    copy the base graph into a fresh worktree and extend it
  bin/graph-sync.sh    refresh the main checkout after a PR merges on the remote
  bin/design-sync.py   advisory design <-> implementation drift report
```

`setup.sh` symlinks `~/.claude/graphify` -> `config/graphify`, so the repo is canonical and the
live tooling tracks it.

---

## Enabling it for a repo

```sh
cd <repo>

# 1. Build the graph, INCLUDING the semantic pass (see "Building the graph" below)
#    In Claude Code:  /graphify . --mode deep

# 2. Tell Claude the graph exists (writes CLAUDE.md + a PreToolUse hook)
graphify claude install

# 3. Wire the git hooks
git config core.hooksPath ~/.claude/graphify/hooks
```

Step 3 is **repo-local**. Sibling repos are untouched and keep whatever hooks they had.

To turn it off for a repo: `git config --unset core.hooksPath`. To turn it off globally for one
command or one shell: `GRAPHIFY_DISABLE=1`.

### You almost certainly need a `.graphifyignore`

**graphify does not read your global gitignore.** It honors the repo's own `.gitignore` and
`.graphifyignore`, nothing else. So anything you exclude globally — `.claude/`, `target/`,
`node_modules/` — gets indexed anyway unless you say so per repo.

This is easy to miss because it fails quietly: the build succeeds and reports a healthy node
count, which happens to be mostly agent config and vendored dependencies. One repo here had
**1068 markdown files under `.claude/`** and **611 under `node_modules/`** — they would have
drowned out ~350 real source files.

```
# .graphifyignore
.claude/
node_modules/
target/
build/
.bloop/
.metals/
```

Add `.graphifyignore` to your global gitignore so it does not show up as an untracked file.
Verify it worked by counting what actually got indexed:

```sh
python3 -c "
import json; m = json.load(open('graphify-out/manifest.json'))
print('indexed:', len(m))
print('noise:', len([k for k in m if k.startswith(('.claude/','node_modules/','target/'))]))"
```

### Do not lose the global pre-push guard

Setting `core.hooksPath` makes git stop reading `~/.git-hooks` **entirely**. If you rely on a
global hook there — e.g. a `pre-push` that blocks commit messages mentioning "Claude" — pointing
`core.hooksPath` elsewhere silently disarms it, and nothing about the repo looks different
afterwards.

`hooks/pre-push` exists solely to delegate back:

```sh
exec "$HOME/.git-hooks/pre-push" "$@"
```

It is deliberately *not* gated on graphify being installed or enabled: the guard must run even
when the graph tooling is disabled. If you keep other global hooks, add matching delegators.

---

## Building the graph

Run the full pipeline, not `graphify update`:

```
/graphify . --mode deep
```

`graphify update` is AST-only. It is what the hooks run (fast, free, no LLM), but it **cannot
create doc↔code edges**. Only the semantic pass — dispatched as parallel `general-purpose`
subagents when no `GEMINI_API_KEY`/`GOOGLE_API_KEY` is set — links a design document to the code
that implements it.

When dispatching those subagents, tell them explicitly which crates/modules exist and to emit
edges to code entities using graphify's node-ID format. Left to itself the extractor produces a
well-formed doc-only island, which is the failure mode described above.

**Verify the semantic pass actually landed** — a node count is not evidence:

```sh
python3 - <<'EOF'
import json
g = json.load(open('graphify-out/graph.json'))
idx = {n['id']: n for n in g['nodes']}
def area(i):
    s = (idx.get(i, {}).get('source_file') or '')
    return 'docs' if s.startswith('docs/') else ('code' if s.startswith(('crates/','src/','vendor/')) else '?')
cross = [l for l in g['links'] if {area(l['source']), area(l['target'])} == {'docs','code'}]
print('doc<->code edges:', len(cross))
EOF
```

If that prints `0`, the semantic pass did not land and the drift report cannot use graph edges.

### Two other things that bite

- **`graphify update` does not accept `--no-viz`.** That flag belongs to `cluster-only`. Above
  5000 nodes graphify skips `graph.html` on its own; use `graphify tree` for a size-independent
  visual.
- **Re-clustering invalidates community labels.** After a rebuild that changes the node count,
  run a full `graphify label .` — `--missing-only` preserves the old, now-misaligned names, so
  you get confident labels pointing at the wrong code. This is the worst kind of stale: a
  community of Raft consensus code cheerfully labelled "TypeScript Config".
- **Community labels need an LLM backend.** With no `GEMINI_API_KEY`/`GOOGLE_API_KEY`,
  `graphify label` keeps `Community N` placeholders and says so. Re-running it falls back to
  filename-derived names (`admin_front.rs`), which are less descriptive but *correct* — prefer
  those over stale semantic names. `--backend claude-cli` labels successfully but then hangs;
  the labels are already written by that point.

---

## How freshness works

| Event | What happens | Cost |
|---|---|---|
| `git commit` | `post-commit` refreshes the graph in the background | ~6s, AST-only, no API |
| branch switch | `post-checkout` refreshes | ~6s |
| `git worktree add` | `post-checkout` seeds from the main checkout, then extends | seconds (APFS clone) |
| PR merges on GitHub | *nothing local fires* — run `graph-sync.sh` | ~10s |

Hooks always `exit 0`. A knowledge-graph problem must never fail a commit, a checkout, or a
push. But "never fail" must not become "fail silently" — failures are appended to
`~/.claude/graphify-hook.log`. Check it if the graph seems to stop updating.

### Worktrees

`git worktree add` fires `post-checkout` with cwd set to the **new worktree** and `$1` set to the
null SHA. That null SHA distinguishes "a fresh worktree appeared" from "someone switched
branches", and it is what the seeding hangs on — so worktree-per-issue flows (`/fix-issue`,
`/ship-issues`) get a queryable graph automatically, with no step for a model to forget.

Seeding copies `graphify-out/` from the main checkout with `cp -Rc` (APFS copy-on-write: near-zero
time and disk), then rewrites `.graphify_root` to point at the worktree. **That rewrite is the
subtle part** — skip it and graphify re-extracts the main checkout's files while writing results
into the worktree's graph. Both look healthy while silently diverging.

`graphify-out/` is gitignored, so `git worktree remove` cleans it up with the worktree.

---

## Keeping design and implementation in sync

```sh
design-sync.py --diff                       # docs linked to current changes
design-sync.py --diff <ref|worktree-path>   # ... to that branch's changes
design-sync.py                              # UNIMPLEMENTED + UNDOCUMENTED audit
design-sync.py --all                        # include vendored code
```

`--diff` answers *"I changed this code — which design docs describe it, and might now be
lying?"* The audit mode answers the two standing questions: which design docs describe something
nobody built (`UNIMPLEMENTED`), and which built subsystems nobody wrote down (`UNDOCUMENTED`).

It draws on **two independent linkage sources**, because each fails differently:

1. **Graph edges** from the semantic pass (`rationale_for`, `implements`,
   `conceptually_related_to`, ...). Rich, but only as good as the extraction.
2. **Literal crate-name mentions** in doc text. Coarse and deterministic, needs no LLM.

The second exists so the report degrades to *useful* rather than *empty* when semantic edges are
thin — which is exactly the state a repo is in before its first `--mode deep` run.

Advisory by construction: **always exits 0**. It surfaces drift; whether drift is a problem is a
judgement call for a person. Wire it into a review step, not a blocking gate, unless you have
decided you want the friction on every PR.

---

## Using the graph efficiently

Cheapest tool that answers the question; escalate only when it comes up short.

| Need | Command |
|---|---|
| Orient in an unfamiliar area | `graphify query "<question>"` |
| What is this symbol, and what surrounds it | `graphify explain "<symbol>"` |
| How do these two things connect | `graphify path "<A>" "<B>"` |
| Blast radius before changing something | `graphify affected "<symbol>" --depth 3` |
| Architectural hubs worth knowing | `graphify god-nodes` |

Close the loop — the graph improves only if it hears what worked *and what didn't*:

```sh
graphify save-result --question "<q>" --answer "<a>" --nodes <labels> --outcome useful
graphify save-result --question "<q>" --outcome dead_end
graphify save-result --question "<q>" --outcome corrected --correction "<what was true>"
graphify reflect     # aggregates graphify-out/memory/ -> reflections/LESSONS.md
```

---

## Verification

```sh
git config core.hooksPath                     # -> ~/.claude/graphify/hooks
git commit --allow-empty -m x && sleep 10     # graph.json mtime should advance
cat ~/.claude/graphify-hook.log               # should be empty

# worktree seeding
git worktree add /tmp/wt-probe -b probe/x HEAD
ls /tmp/wt-probe/graphify-out/graph.json      # exists
cat /tmp/wt-probe/graphify-out/.graphify_root # points at the PROBE, not the main checkout
git worktree remove /tmp/wt-probe --force && git branch -D probe/x

# the global guard survived the core.hooksPath switch
printf 'refs/heads/x %s refs/heads/x %s\n' "$(git rev-parse HEAD)" "$(printf '0%.0s' $(seq 40))" \
  | ~/.claude/graphify/hooks/pre-push origin git@github.com:x/y.git
```

An empty commit is **not** a valid test of `post-commit`: it changes no files, so the graph is
correctly left alone. Use a real edit.
