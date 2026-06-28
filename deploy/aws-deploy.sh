#!/usr/bin/env bash
# Deploy NexusQuant to EC2 via AWS SSM (uses deploy/aws.env credentials).
#
# Setup once:
#   cp deploy/aws.env.example deploy/aws.env
#   # fill in AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
#
# Deploy:
#   ./deploy/aws-deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/aws.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: missing $ENV_FILE — copy deploy/aws.env.example and add credentials"
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID required in deploy/aws.env}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY required in deploy/aws.env}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
INSTANCE_ID="${EC2_INSTANCE_ID:-i-02b2962f02b61005f}"

echo "==> Deploying to EC2 $INSTANCE_ID ($AWS_DEFAULT_REGION)"

CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "aws-deploy.sh $(date -Iseconds)" \
  --parameters "commands=[
    \"set -euo pipefail\",
    \"export HOME=/root\",
    \"export GIT_CONFIG_GLOBAL=/root/.gitconfig\",
    \"git config --global --add safe.directory /opt/nexusquant/New-idea\",
    \"cd /opt/nexusquant/New-idea\",
    \"git fetch origin main\",
    \"git checkout main\",
    \"git pull --ff-only origin main || git reset --hard origin/main\",
    \"bash deploy/ec2-update.sh\"
  ]" \
  --query Command.CommandId \
  --output text)

echo "SSM command: $CMD_ID"
for i in $(seq 1 40); do
  STATUS=$(aws ssm get-command-invocation \
    --command-id "$CMD_ID" \
    --instance-id "$INSTANCE_ID" \
    --query Status \
    --output text 2>/dev/null || echo Pending)
  echo "  $i: $STATUS"
  if [ "$STATUS" = "Success" ]; then
    aws ssm get-command-invocation \
      --command-id "$CMD_ID" \
      --instance-id "$INSTANCE_ID" \
      --query StandardOutputContent \
      --output text | tail -25
    echo ""
    echo "==> Verify: https://www.jashuvatrade.xyz/api/deployment/status"
    exit 0
  fi
  if [ "$STATUS" = "Failed" ] || [ "$STATUS" = "Cancelled" ] || [ "$STATUS" = "TimedOut" ]; then
    aws ssm get-command-invocation \
      --command-id "$CMD_ID" \
      --instance-id "$INSTANCE_ID" \
      --output json
    exit 1
  fi
  sleep 15
done

echo "ERROR: deploy timed out"
exit 1
