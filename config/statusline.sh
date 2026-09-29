#!/bin/bash
# Powerline-style status line: dir · git · model · context. Also feeds abtop's rate-limit hook.
# Needs a Nerd Font in the terminal (e.g. JetBrainsMono Nerd Font) and a truecolor terminal.
INPUT=$(cat)

# Keep abtop working when installed (its hook only writes a file, prints nothing)
[ -x "$HOME/.claude/abtop-statusline.sh" ] && printf '%s' "$INPUT" | "$HOME/.claude/abtop-statusline.sh" >/dev/null 2>&1

# One jq call, one field per line
{
  read -r DIR
  read -r MODEL
  read -r CTX
} < <(jq -r '(.workspace.current_dir // .cwd // ""),
             (.model.display_name // .model.id // "?"),
             (.context_window.used_percentage // "" | tostring)' <<<"$INPUT")

# Nerd Font glyphs, as UTF-8 byte escapes (private-use codepoints are invisible in most editors)
SEP=$'\xee\x82\xb0'          # U+E0B0  powerline arrow
CAP_L=$'\xee\x82\xb6'        # U+E0B6  rounded left cap
CAP_R=$'\xee\x82\xb4'        # U+E0B4  rounded right cap
I_DIR=$'\xef\x81\xbc'        # U+F07C  folder-open
I_HOME=$'\xef\x80\x95'       # U+F015  home
I_BRANCH=$'\xee\x82\xa0'     # U+E0A0  git branch
I_TREE=$'\xf3\xb0\x99\x85'   # U+F0645 file-tree (linked worktree)
I_WARN=$'\xef\x81\xb1'       # U+F071  warning (rebase/merge in progress)
I_MODEL=$'\xf3\xb0\x9a\xa9'  # U+F06A9 robot
I_CTX=$'\xf3\xb0\xa7\x91'    # U+F09D1 brain

# Truecolor helpers: rgb "r;g;b"
fg() { printf '\033[38;2;%sm' "$1"; }
bg() { printf '\033[48;2;%sm' "$1"; }
RESET=$'\033[0m'
DARK="30;30;46"

# Segment renderer: each segment is "bg|fg|text"; arrows take the previous segment's bg as fg
SEGMENTS=()
seg() { SEGMENTS+=("$1|$2|$3"); }

# --- directory ---
if [ -n "$DIR" ]; then
  SHORT=${DIR/#$HOME/\~}
  ICON=$I_DIR
  [ "$DIR" = "$HOME" ] && ICON=$I_HOME
  # Keep the last three path components, like p10k's truncation
  if [ "$(tr -cd '/' <<<"$SHORT" | wc -c)" -gt 3 ]; then
    SHORT="…/$(awk -F/ '{print $(NF-2)"/"$(NF-1)"/"$NF}' <<<"$SHORT")"
  fi
  seg "137;180;250" "$DARK" "$ICON $SHORT"
fi

# --- git: branch, ahead/behind, dirty ---
if [ -n "$DIR" ] && GIT=$(git -C "$DIR" --no-optional-locks status --porcelain=v2 --branch 2>/dev/null); then
  BRANCH=$(awk '/^# branch.head/{print $3}' <<<"$GIT")
  { read -r GIT_DIR; read -r COMMON_DIR; read -r TOPLEVEL; } < <(git -C "$DIR" rev-parse \
    --path-format=absolute --git-dir --git-common-dir --show-toplevel 2>/dev/null)

  # HEAD is detached mid-rebase; the branch being rebased is recorded in the git dir
  OP=""
  for d in rebase-merge rebase-apply; do
    if [ -f "$GIT_DIR/$d/head-name" ]; then
      OP="rebasing"
      BRANCH=$(sed 's#^refs/heads/##' "$GIT_DIR/$d/head-name")
    fi
  done
  [ -z "$OP" ] && [ -f "$GIT_DIR/MERGE_HEAD" ] && OP="merging"
  [ "$BRANCH" = "(detached)" ] && BRANCH="@$(awk '/^# branch.oid/{print substr($3,1,7)}' <<<"$GIT")"

  read -r AHEAD BEHIND < <(awk '/^# branch.ab/{gsub(/[+-]/,""); print $3, $4}' <<<"$GIT")
  DIRTY=$(grep -cv '^#' <<<"$GIT")

  # A linked worktree has its own git dir under the main repo's common dir
  if [ -n "$TOPLEVEL" ] && [ "$GIT_DIR" != "$COMMON_DIR" ]; then
    seg "116;199;236" "$DARK" "$I_TREE ${TOPLEVEL##*/}"
  fi

  TEXT="$I_BRANCH $BRANCH"
  [ -n "$OP" ] && TEXT="$TEXT $I_WARN $OP"
  [ "${AHEAD:-0}" -gt 0 ] && TEXT="$TEXT ⇡$AHEAD"
  [ "${BEHIND:-0}" -gt 0 ] && TEXT="$TEXT ⇣$BEHIND"
  if [ "$DIRTY" -gt 0 ]; then
    seg "249;226;175" "$DARK" "$TEXT ●$DIRTY"
  else
    seg "166;227;161" "$DARK" "$TEXT"
  fi
fi

# --- model ---
seg "203;166;247" "$DARK" "$I_MODEL $MODEL"

# --- context: 10-cell bar, colored by pressure ---
if [ -n "$CTX" ]; then
  PCT=$(printf '%.0f' "$CTX")
  FILLED=$(( (PCT + 5) / 10 )); [ "$FILLED" -gt 10 ] && FILLED=10
  BAR=""
  for ((i = 0; i < 10; i++)); do
    if [ "$i" -lt "$FILLED" ]; then BAR="${BAR}▰"; else BAR="${BAR}▱"; fi
  done
  if [ "$PCT" -ge 80 ]; then C="243;139;168"; elif [ "$PCT" -ge 50 ]; then C="250;179;135"; else C="148;226;213"; fi
  seg "$C" "$DARK" "$I_CTX $BAR $PCT%"
fi

# --- render ---
OUT=""
PREV=""
for s in "${SEGMENTS[@]}"; do
  IFS='|' read -r B F T <<<"$s"
  if [ -z "$PREV" ]; then
    OUT="$(fg "$B")$CAP_L"
  else
    OUT="$OUT$(fg "$PREV")$(bg "$B")$SEP"
  fi
  OUT="$OUT$(bg "$B")$(fg "$F") $T "
  PREV=$B
done
[ -n "$PREV" ] && OUT="$OUT$RESET$(fg "$PREV")$CAP_R$RESET"
printf '%s\n' "$OUT"
