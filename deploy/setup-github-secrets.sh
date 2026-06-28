#!/usr/bin/env bash
# One-time: store AWS deploy credentials in GitHub Actions secrets.
# Run from your laptop (needs gh auth + repo admin):
#   ./deploy/setup-github-secrets.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/aws.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: missing $ENV_FILE"
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${AWS_ACCESS_KEY_ID:?}"
: "${AWS_SECRET_ACCESS_KEY:?}"

printf '%s' "$AWS_ACCESS_KEY_ID" | gh secret set AWS_ACCESS_KEY_ID --repo jashuvawork/New-idea
printf '%s' "$AWS_SECRET_ACCESS_KEY" | gh secret set AWS_SECRET_ACCESS_KEY --repo jashuvawork/New-idea

echo "GitHub secrets set. Actions workflow 'Deploy to EC2' will run on main pushes."
