#!/usr/bin/env bash
# After ec2-update on production: refresh execution flags without disarming live.
#
# - If /opt/nexusquant/env has ENABLE_LIVE_TRADING=true → set-execution-mode --live
# - Else → set-execution-mode --paper
#
# set-execution-mode already preserves live capital overrides when arming live.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "WARN: $ENV_FILE missing — defaulting to paper"
  sudo ENV_FILE="$ENV_FILE" REPO_DIR="$REPO_DIR" bash "$REPO_DIR/deploy/set-execution-mode.sh" --paper
  exit 0
fi

if grep -q '^ENABLE_LIVE_TRADING=true' "$ENV_FILE" 2>/dev/null; then
  echo "Live armed on $ENV_FILE — keeping LIVE after deploy"
  sudo ENV_FILE="$ENV_FILE" REPO_DIR="$REPO_DIR" bash "$REPO_DIR/deploy/set-execution-mode.sh" --live
else
  echo "Live not armed — setting PAPER after deploy"
  sudo ENV_FILE="$ENV_FILE" REPO_DIR="$REPO_DIR" bash "$REPO_DIR/deploy/set-execution-mode.sh" --paper
fi
