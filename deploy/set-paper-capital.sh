#!/usr/bin/env bash
# Legacy name — forwards to set-daily-capital.sh (with backend restart).
#
#   sudo bash deploy/set-paper-capital.sh
#   PAPER_CAPITAL_INR=45000 sudo bash deploy/set-paper-capital.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (sudo bash deploy/set-paper-capital.sh)" >&2
  exit 1
fi

# Map legacy env name
export CAPITAL_BOOK_INR="${CAPITAL_BOOK_INR:-${PAPER_CAPITAL_INR:-}}"
export RESTART_BACKEND=1
exec bash "${SCRIPT_DIR}/set-daily-capital.sh" "$@"