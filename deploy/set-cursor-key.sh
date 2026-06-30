#!/usr/bin/env bash
# Set CURSOR_API_KEY in production env and restart backend (run on EC2 via SSM).
# Usage: CURSOR_API_KEY=crsr_... sudo bash deploy/set-cursor-key.sh
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
REPO_DIR="${REPO_DIR:-/opt/nexusquant/New-idea}"
KEY="${CURSOR_API_KEY:?CURSOR_API_KEY required}"

touch "$ENV_FILE"
grep -v '^CURSOR_API_KEY=' "$ENV_FILE" > /tmp/nexus.env || true
printf '%s\n' "CURSOR_API_KEY=${KEY}" >> /tmp/nexus.env
mv /tmp/nexus.env "$ENV_FILE"
chmod 600 "$ENV_FILE"

cd "$REPO_DIR"
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
sleep 6
docker compose -f docker-compose.prod.yml exec -T backend python3 -c \
  "from app.config import get_settings; s=get_settings(); print('configured', bool(s.cursor_api_key), 'len', len(s.cursor_api_key))"
