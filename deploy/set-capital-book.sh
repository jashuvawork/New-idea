#!/usr/bin/env bash
# Post-deploy / full sync: daily capital script + backend restart.
# Prefer morning updates: deploy/set-daily-capital.sh (no restart by default).
#
#   sudo bash deploy/set-capital-book.sh
#   CAPITAL_BOOK_INR=45000 sudo bash deploy/set-capital-book.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/set-capital-book.sh)" >&2
  exit 1
fi

export RESTART_BACKEND=1
exec bash "${SCRIPT_DIR}/set-daily-capital.sh" "$@"