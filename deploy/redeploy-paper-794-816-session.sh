#!/usr/bin/env bash
# Paper #794 book on main: pull latest, paper mode, 09:20 entry (template — no detach, no 09:16 overlay).
#
# On EC2 (root):
#   sudo bash deploy/redeploy-paper-794-816-session.sh
#   sudo bash deploy/redeploy-paper-794-816-session.sh --skip-update
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-}"
if [ -z "$REPO_DIR" ]; then
  if [ -d /opt/nexusquant/New-idea/.git ]; then
    REPO_DIR=/opt/nexusquant/New-idea
  elif [ -d /opt/nexusquant/.git ]; then
    REPO_DIR=/opt/nexusquant
  else
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
fi
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
SKIP_UPDATE=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --skip-update) SKIP_UPDATE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--skip-update] [--dry-run]" >&2
      exit 1
      ;;
  esac
done

_run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "=== Paper #794 / #816 redeploy on main $(date -Iseconds) ==="
echo "Repo: $REPO_DIR | Env: $ENV_FILE"

if [ "$SKIP_UPDATE" -eq 0 ]; then
  _run sudo bash "$REPO_DIR/deploy/ec2-update.sh"
fi

_run sudo ENV_FILE="$ENV_FILE" REPO_DIR="$REPO_DIR" SKIP_RESTART=0 \
  bash "$REPO_DIR/deploy/set-execution-mode.sh" --paper

export EXPECT_ENTRY_EARLIEST="${EXPECT_ENTRY_EARLIEST:-09:20}"
export EXPECT_EXPLOSION_ENTRY_EARLIEST="${EXPECT_EXPLOSION_ENTRY_EARLIEST:-09:20}"

_run bash "$REPO_DIR/deploy/verify-paper-794-816-session.sh"

echo "=== Done ==="
