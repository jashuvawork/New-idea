#!/usr/bin/env bash
# Full paper #676 redeploy: pull main, apply open/entry overlay, paper mode, verify.
#
# On EC2 (root):
#   sudo bash deploy/redeploy-paper-676-full.sh
#   sudo bash deploy/redeploy-paper-676-full.sh --no-loss-stops
#
# Options:
#   --no-loss-stops   Pass through to set-execution-mode.sh (#858)
#   --skip-update     Skip ec2-update.sh (git pull + docker restart)
#   --dry-run         Print steps only
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
OVERLAY="${REPO_DIR}/deploy/env.paper-676-full-session.overlay"
NO_LOSS=0
SKIP_UPDATE=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --no-loss-stops) NO_LOSS=1 ;;
    --skip-update) SKIP_UPDATE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--no-loss-stops] [--skip-update] [--dry-run]" >&2
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

echo "=== Paper full #676 redeploy $(date -Iseconds) ==="
echo "Repo: $REPO_DIR | Env: $ENV_FILE"

if [ "$SKIP_UPDATE" -eq 0 ]; then
  _run sudo bash "$REPO_DIR/deploy/ec2-update.sh"
fi

if [ ! -f "$OVERLAY" ]; then
  echo "ERROR: overlay not found: $OVERLAY" >&2
  exit 1
fi

_run sudo ENV_FILE="$ENV_FILE" bash "$REPO_DIR/deploy/apply-env-overlay.sh" "$OVERLAY"

MODE_ARGS=(--paper)
if [ "$NO_LOSS" -eq 1 ]; then
  MODE_ARGS+=(--no-loss-stops)
fi
if [ "$DRY_RUN" -eq 1 ]; then
  MODE_ARGS+=(--dry-run)
fi
_run sudo ENV_FILE="$ENV_FILE" REPO_DIR="$REPO_DIR" SKIP_RESTART=0 \
  bash "$REPO_DIR/deploy/set-execution-mode.sh" "${MODE_ARGS[@]}"

export EXPECT_ENTRY_EARLIEST="${EXPECT_ENTRY_EARLIEST:-09:16}"
export EXPECT_EXPLOSION_ENTRY_EARLIEST="${EXPECT_EXPLOSION_ENTRY_EARLIEST:-09:16}"
export EXPECT_OPEN_SIDE_START="${EXPECT_OPEN_SIDE_START:-09:15}"

_run bash "$REPO_DIR/deploy/verify-paper-676-session.sh"

echo "Done. Public check: curl -sf https://api.jashuvatrade.xyz/api/deployment/status | jq .flags"
