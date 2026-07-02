#!/usr/bin/env bash
# Push Upstox / API secrets from deploy/secrets.env to EC2 /opt/nexusquant/env via SSM.
#
# Setup:
#   cp deploy/secrets.env.example deploy/secrets.env
#   # fill UPSTOX_API_KEY, UPSTOX_API_SECRET, FINNHUB_API_KEY, CURSOR_API_KEY
#
# Usage:
#   ./deploy/sync-secrets.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/aws.env"
SECRETS_FILE="${SCRIPT_DIR}/secrets.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: missing $ENV_FILE"
  exit 1
fi
if [ ! -f "$SECRETS_FILE" ]; then
  echo "ERROR: missing $SECRETS_FILE — copy deploy/secrets.env.example"
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${AWS_ACCESS_KEY_ID:?}"
: "${AWS_SECRET_ACCESS_KEY:?}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
INSTANCE_ID="${EC2_INSTANCE_ID:-i-0f3f9e5e67815c21b}"

KEYS=(UPSTOX_API_KEY UPSTOX_API_SECRET FINNHUB_API_KEY CURSOR_API_KEY)
REMOTE_CMDS=("set -euo pipefail" "touch /opt/nexusquant/env")

while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line// }" ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  for k in "${KEYS[@]}"; do
    if [ "$key" = "$k" ] && [ -n "$val" ]; then
      esc="${val//\\/\\\\}"
      esc="${esc//|/\\|}"
      REMOTE_CMDS+=("if grep -q '^${key}=' /opt/nexusquant/env; then sed -i 's|^${key}=.*|${key}=${esc}|' /opt/nexusquant/env; else echo '${key}=${esc}' >> /opt/nexusquant/env; fi")
      echo "  sync $key"
    fi
  done
done < "$SECRETS_FILE"

REMOTE_CMDS+=("cd /opt/nexusquant/New-idea && docker compose -f docker-compose.prod.yml restart backend")
REMOTE_CMDS+=("sleep 5 && curl -sf http://127.0.0.1:8000/api/upstox/setup | python3 -c \"import json,sys; d=json.load(sys.stdin); print('clientId configured:', bool(d.get('clientId')))\"")

JSON_CMDS=$(printf '%s\n' "${REMOTE_CMDS[@]}" | python3 -c "import json,sys; print(json.dumps([l.rstrip('\n') for l in sys.stdin]))")

CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "sync-secrets.sh" \
  --parameters "commands=${JSON_CMDS}" \
  --query Command.CommandId --output text)

echo "SSM command: $CMD_ID"
for i in $(seq 1 20); do
  STATUS=$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query Status --output text 2>/dev/null || echo Pending)
  echo "  $i: $STATUS"
  if [ "$STATUS" = "Success" ]; then
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query StandardOutputContent --output text | tail -10
    exit 0
  fi
  if [ "$STATUS" = "Failed" ]; then
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --output json
    exit 1
  fi
  sleep 5
done
