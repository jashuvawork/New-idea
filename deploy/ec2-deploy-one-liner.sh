#!/usr/bin/env bash
# Run NexusQuant EC2 update via SSH (one command from your laptop).
#
# Usage:
#   EC2_HOST=65.1.137.232 EC2_KEY=~/.ssh/nexusquant.pem ./deploy/ec2-deploy-one-liner.sh
#
# After PR #11 is merged to main, this pulls and runs ec2-update.sh on the server.

set -euo pipefail

EC2_HOST="${EC2_HOST:-65.1.137.232}"
EC2_USER="${EC2_USER:-ec2-user}"
EC2_KEY="${EC2_KEY:-}"
BRANCH="${BRANCH:-main}"
REPO_RAW="https://raw.githubusercontent.com/jashuvawork/New-idea/${BRANCH}/deploy/ec2-update.sh"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
if [ -n "$EC2_KEY" ]; then
  SSH_OPTS+=(-i "$EC2_KEY")
fi

echo "==> Deploying NexusQuant to ${EC2_USER}@${EC2_HOST} (branch: ${BRANCH})"

# Prefer local script when developing; fall back to GitHub raw on server
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/ec2-update.sh" ]; then
  echo "==> Uploading local deploy/ec2-update.sh"
  ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
    "sudo env BRANCH=${BRANCH} bash -s" < "${SCRIPT_DIR}/ec2-update.sh"
else
  echo "==> Running remote script from ${REPO_RAW}"
  ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
    "curl -fsSL '${REPO_RAW}' | sudo env BRANCH=${BRANCH} bash -s"
fi

echo ""
echo "==> Verify from browser or curl:"
echo "    https://www.jashuvatrade.xyz/api/deployment/status"
echo "    Look for websocket.connected=true during market hours (Upstox token required)"
