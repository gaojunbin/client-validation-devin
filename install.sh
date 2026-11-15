#!/usr/bin/env bash
# Install client-validation-devin: the skills for Claude Code, Codex and Antigravity, the CLI on PATH,
# and your Devin API key. Works from a checkout (./install.sh) or piped:
#   curl -fsSL https://raw.githubusercontent.com/gaojunbin/client-validation-devin/main/install.sh | bash
# Never overwrites or deletes anything it did not create.
set -euo pipefail

DEFAULT_REPO="https://github.com/gaojunbin/client-validation-devin.git"
SKILLS=(client-validation-devin client-validation-devin-setup)
AGENTS="claude,codex,antigravity"
BIN_DIR="$HOME/.local/bin"
MODE="install"
DRY_RUN=0
ASK_KEY=1

usage() {
  cat <<EOF
Usage: install.sh [--agents claude,codex,antigravity] [--bin-dir DIR] [--no-key] [--uninstall] [--dry-run]

  claude       -> ~/.claude/skills/<skill>
  codex        -> ~/.agents/skills/<skill>
  antigravity  -> ~/.gemini/config/skills/<skill>
  CLI          -> <bin-dir>/client-validation-devin (default ~/.local/bin)
  --no-key     do not ask for the Devin API key (run 'client-validation-devin login' later)

Piped installs clone into \$CLIENT_VALIDATION_DEVIN_DIR (default ~/.local/share/client-validation-devin);
running the installer again updates that clone.
EOF
}

ARGS=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents) AGENTS="${2:?--agents needs a value}"; shift 2 ;;
    --bin-dir) BIN_DIR="${2:?--bin-dir needs a value}"; shift 2 ;;
    --no-key) ASK_KEY=0; shift ;;
    --uninstall) MODE="uninstall"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 4 ;;
  esac
done

bootstrap() { # piped install: get a checkout, then run its installer
  local dir="${CLIENT_VALIDATION_DEVIN_DIR:-$HOME/.local/share/client-validation-devin}"
  local repo="${CLIENT_VALIDATION_DEVIN_REPO:-$DEFAULT_REPO}"
  command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 4; }
  if [[ -d "$dir/.git" ]]; then
    echo "updating $dir"
    git -C "$dir" pull --ff-only --quiet
  elif [[ -e "$dir" ]]; then
    echo "$dir exists but is not a client-validation-devin clone; set CLIENT_VALIDATION_DEVIN_DIR" >&2
    exit 4
  else
    echo "cloning into $dir"
    mkdir -p "$(dirname "$dir")"
    git clone --quiet --depth 1 "$repo" "$dir"
  fi
  exec bash "$dir/install.sh" ${ARGS[@]+"${ARGS[@]}"}
}

SOURCE="${BASH_SOURCE[0]:-}"
REPO_DIR=""
if [[ -n "$SOURCE" && -f "$SOURCE" ]]; then
  REPO_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
fi
if [[ -z "$REPO_DIR" || ! -f "$REPO_DIR/skills/client-validation-devin/SKILL.md" ]]; then
  bootstrap
fi
CLI_SOURCE="$REPO_DIR/skills/client-validation-devin/scripts/client-validation-devin"

skill_dir() {
  case "$1" in
    claude) echo "$HOME/.claude/skills" ;;
    codex) echo "$HOME/.agents/skills" ;;
    antigravity) echo "$HOME/.gemini/config/skills" ;;
    *) echo "unknown agent: $1 (use claude, codex, antigravity)" >&2; exit 4 ;;
  esac
}

run() {
  if [[ $DRY_RUN -eq 1 ]]; then echo "  would run: $*"; else "$@"; fi
}

link() { # SOURCE DEST
  local src="$1" dest="$2"
  if [[ -L "$dest" ]]; then
    if [[ "$(readlink "$dest")" == "$src" ]]; then
      echo "ok      $dest"
    else
      echo "skip    $dest is a symlink to $(readlink "$dest"); leaving it alone"
    fi
    return
  fi
  if [[ -e "$dest" ]]; then
    echo "skip    $dest exists and was not created by this installer; leaving it alone"
    return
  fi
  run mkdir -p "$(dirname "$dest")"
  run ln -s "$src" "$dest"
  echo "linked  $dest -> $src"
}

unlink_ours() { # SOURCE DEST
  local src="$1" dest="$2"
  if [[ -L "$dest" && "$(readlink "$dest")" == "$src" ]]; then
    run rm "$dest"
    echo "removed $dest"
  fi
}

apply() { # SOURCE DEST
  if [[ "$MODE" == "install" ]]; then link "$1" "$2"; else unlink_ours "$1" "$2"; fi
}

python_ok() {
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null
}

key_configured() {
  [[ -n "${DEVIN_API_KEY:-}" ]] && return 0
  local env_file="${CLIENT_VALIDATION_DEVIN_ENV_FILE:-$HOME/.config/client-validation-devin/env}"
  [[ -f "$env_file" ]] && grep -q '^\(export \)\{0,1\}DEVIN_API_KEY=cog_' "$env_file"
}

configure_key() {
  if [[ $ASK_KEY -eq 0 || $DRY_RUN -eq 1 ]]; then
    return
  fi
  if ! python_ok; then
    echo "skipping the API key: python3 >= 3.11 is required (brew install python, or uv python install 3.12)"
    return
  fi
  if key_configured; then
    echo "Devin API key already configured; run 'client-validation-devin login' to replace it"
    return
  fi
  if ! { : </dev/tty; } 2>/dev/null; then
    echo "no terminal to ask for the key; run 'client-validation-devin login' later"
    return
  fi
  echo
  echo "Connect your Devin account (a personal access token starting with cog_)."
  until "$CLI_SOURCE" login </dev/tty; do
    printf 'Try again? [Y/n] ' >/dev/tty
    read -r answer </dev/tty || answer=n
    [[ "$answer" =~ ^[Nn] ]] && { echo "skipped; run 'client-validation-devin login' later"; return; }
  done
}

IFS=',' read -r -a agent_list <<< "$AGENTS"
for agent in "${agent_list[@]}"; do
  dir="$(skill_dir "$agent")"
  for skill in "${SKILLS[@]}"; do
    apply "$REPO_DIR/skills/$skill" "$dir/$skill"
  done
done
apply "$CLI_SOURCE" "$BIN_DIR/client-validation-devin"

if [[ "$MODE" == "uninstall" ]]; then
  echo "uninstalled the links; your key stays in ~/.config/client-validation-devin/env and the code in $REPO_DIR"
  exit 0
fi

python_ok || echo "warning: client-validation-devin needs python3 >= 3.11 on PATH (brew install python, or uv python install 3.12)"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "warning: $BIN_DIR is not on PATH; add it to your shell profile" ;;
esac
configure_key

cat <<EOF

Installed. In a client-app repository, ask your coding agent:
  "Set up Devin cloud validation for this repo"      (skill client-validation-devin-setup, once per repo)
  "Implement <feature>, then validate it on every platform with client-validation-devin"
Explicit invocation: Claude Code /client-validation-devin · Codex \$client-validation-devin · Antigravity /client-validation-devin
Check a machine and repo any time: client-validation-devin available --online
EOF
