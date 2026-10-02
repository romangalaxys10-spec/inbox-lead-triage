#!/usr/bin/env bash
# install.sh — install inbox-lead-triage onto one or more agent platforms.
#
# The repo holds ONE canonical skill (skills/inbox-lead-triage). Each target
# gets: scripts + templates + tests copied (or symlinked with --dev), and a
# SKILL.md assembled from the canonical body + the platform's NOTES.md.
#
# Usage:
#   ./install.sh --zcode                 # ~/.zcode/skills/inbox-lead-triage
#   ./install.sh --claude                # ~/.claude/skills/inbox-lead-triage
#   ./install.sh --antigravity           # needs ANTIGRAVITY_PROJECT=<dir>
#   ./install.sh --agents-md             # prints AGENTS.md snippet (stdout)
#   ./install.sh --all                   # zcode + claude (+antigravity if set)
#   ./install.sh --dev --zcode           # symlink engine instead of copy
#
# Env overrides:
#   ZCODE_SKILLS_DIR      (default ~/.zcode/skills)
#   CLAUDE_SKILLS_DIR     (default ~/.claude/skills)
#   CLAUDE_COMMANDS_DIR   (default ~/.claude/commands)
#   ANTIGRAVITY_PROJECT   (project dir receiving .agent/workflows/)
#   AGENTS_MD_FILE        (append snippet to this AGENTS.md instead of stdout)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$REPO_ROOT/skills/inbox-lead-triage"
DEV=0
TARGETS=()

ZCODE_SKILLS_DIR="${ZCODE_SKILLS_DIR:-$HOME/.zcode/skills}"
CLAUDE_SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
CLAUDE_COMMANDS_DIR="${CLAUDE_COMMANDS_DIR:-$HOME/.claude/commands}"

log() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# literal string replace in a file (no sed regex escaping issues)
py_replace_in_file() { # file placeholder value
  python3 - "$1" "$2" "$3" <<'PY'
import sys, pathlib
f, ph, val = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(f)
p.write_text(p.read_text().replace(ph, val))
PY
}

require_dir() { [ -d "$1" ] || die "missing required directory: $1"; }

copy_tree() { # src dst (cp or symlink in --dev mode)
  local src="$1" dst="$2"
  if [ "$DEV" = "1" ]; then
    ln -sfn "$src" "$dst"
  else
    cp -R "$src" "$dst"
  fi
}

install_skill() { # platform dst
  local platform="$1" dst="$2"
  # validate every source BEFORE deleting anything at the destination
  require_dir "$SKILL_SRC"
  [ -f "$SKILL_SRC/SKILL.md" ] || die "missing $SKILL_SRC/SKILL.md"
  for sub in scripts templates tests; do
    require_dir "$SKILL_SRC/$sub"
  done
  [ -f "$REPO_ROOT/adapters/$platform/NOTES.md" ] || die "no NOTES.md for platform $platform"
  rm -rf "$dst"
  mkdir -p "$dst"
  copy_tree "$SKILL_SRC/scripts" "$dst/scripts"
  copy_tree "$SKILL_SRC/templates" "$dst/templates"
  copy_tree "$SKILL_SRC/tests" "$dst/tests"
  {
    cat "$SKILL_SRC/SKILL.md"
    printf '\n'
    cat "$REPO_ROOT/adapters/$platform/NOTES.md"
  } > "$dst/SKILL.md"
  log "  installed: $dst"
}

install_claude_command() {
  [ -f "$REPO_ROOT/commands/ilt-triage.md" ] || die "missing commands/ilt-triage.md"
  mkdir -p "$CLAUDE_COMMANDS_DIR"
  cp "$REPO_ROOT/commands/ilt-triage.md" "$CLAUDE_COMMANDS_DIR/ilt-triage.md"
  log "  installed: $CLAUDE_COMMANDS_DIR/ilt-triage.md"
}

install_antigravity() {
  local proj="${ANTIGRAVITY_PROJECT:-}"
  [ -n "$proj" ] || die "--antigravity needs ANTIGRAVITY_PROJECT=<project dir>"
  [ -d "$proj" ] || die "ANTIGRAVITY_PROJECT does not exist: $proj"
  local wf_dir="$proj/.agent/workflows"
  mkdir -p "$wf_dir"
  cp "$REPO_ROOT/adapters/antigravity/workflow.md" "$wf_dir/inbox-lead-triage.md"
  py_replace_in_file "$wf_dir/inbox-lead-triage.md" "__ILT_REPO__" "$REPO_ROOT"
  log "  installed: $wf_dir/inbox-lead-triage.md"
}

install_agents_md() {
  local snippet_file="$REPO_ROOT/adapters/agents-md/AGENTS.snippet.md"
  [ -f "$snippet_file" ] || die "missing $snippet_file"
  if [ -n "${AGENTS_MD_FILE:-}" ]; then
    local marker_begin="<!-- inbox-lead-triage:begin -->"
    local marker_end="<!-- inbox-lead-triage:end -->"
    mkdir -p "$(dirname "$AGENTS_MD_FILE")"
    touch "$AGENTS_MD_FILE"
    python3 - "$AGENTS_MD_FILE" "$marker_begin" "$marker_end" "$snippet_file" "$REPO_ROOT" <<'PY'
import sys, pathlib
f, b, e, snippet_file, repo = sys.argv[1:6]
snippet = "<!-- inbox-lead-triage:begin -->\n" + pathlib.Path(snippet_file).read_text() + "\n<!-- inbox-lead-triage:end -->\n"
snippet = snippet.replace("__ILT_REPO__", repo)
p = pathlib.Path(f); t = p.read_text()
i, j = t.find(b), t.find(e)
if i != -1 and j != -1 and j > i:
    p.write_text(t[:i] + snippet + t[j + len(e):])   # replace existing block
else:
    p.write_text(t.rstrip() + "\n\n" + snippet)      # append (also covers dangling marker)
PY
    log "  installed: $AGENTS_MD_FILE (inbox-lead-triage block)"
  else
    python3 - "$snippet_file" "$REPO_ROOT" <<'PY'
import sys, pathlib
print(pathlib.Path(sys.argv[1]).read_text().replace("__ILT_REPO__", sys.argv[2]), end="")
PY
    log "  (set AGENTS_MD_FILE=<path> to append this block automatically)" >&2
  fi
}

usage() {
  sed -n '2,26p' "$REPO_ROOT/install.sh" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --zcode) TARGETS+=(zcode); shift ;;
    --claude) TARGETS+=(claude); shift ;;
    --antigravity) TARGETS+=(antigravity); shift ;;
    --agents-md) TARGETS+=(agents-md); shift ;;
    --all)
      TARGETS+=(zcode claude)
      [ -n "${ANTIGRAVITY_PROJECT:-}" ] && TARGETS+=(antigravity)
      shift ;;
    --dev) DEV=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown flag: $1 (try --help)" ;;
  esac
done
[ ${#TARGETS[@]} -gt 0 ] || { usage; exit 1; }

log "inbox-lead-triage installer (repo: $REPO_ROOT)"
for t in "${TARGETS[@]}"; do
  case "$t" in
    zcode) install_skill zcode "$ZCODE_SKILLS_DIR/inbox-lead-triage" ;;
    claude)
      install_skill claude-code "$CLAUDE_SKILLS_DIR/inbox-lead-triage"
      install_claude_command ;;
    antigravity) install_antigravity ;;
    agents-md) install_agents_md ;;
  esac
done
log "done. next: fill criteria.md, run the tests, then schedule the tick."
