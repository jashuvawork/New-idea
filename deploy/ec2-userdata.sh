#!/bin/bash
# EC2 user-data bootstrap for NexusQuant (robust)
set -ex
exec > /var/log/nexusquant-bootstrap.log 2>&1

echo "=== NexusQuant bootstrap $(date) ==="

dnf update -y
dnf install -y docker git
dnf install -y docker-compose-plugin 2>/dev/null || true
systemctl start docker
systemctl enable docker

# Ensure docker compose works
if ! docker compose version 2>/dev/null; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

mkdir -p /opt/nexusquant
cd /opt/nexusquant

if [ ! -d New-idea ]; then
  git clone --branch cursor/nexusquant-scalping-terminal-8564 \
    https://github.com/jashuvawork/New-idea.git || \
  git clone https://github.com/jashuvawork/New-idea.git
fi

cd New-idea
git fetch origin
git checkout cursor/nexusquant-scalping-terminal-8564 2>/dev/null || git checkout main

cp deploy/env.production.template /opt/nexusquant/env
cat >> /opt/nexusquant/env << 'EOF'
REDIS_URL=redis://redis:6379/0
UPSTOX_REDIRECT_URI=https://www.jashuvatrade.xyz/api/upstox/callback
ENVIRONMENT=production
TRADE_STORE_DIR=/opt/nexusquant/data/trades
DAILY_TOKEN_ONCE=true
EOF

mkdir -p /opt/nexusquant/data/trades

cat > docker-compose.prod.yml << 'COMPOSE'
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - /opt/nexusquant/env
    environment:
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - /opt/nexusquant/data/trades:/opt/nexusquant/data/trades
    depends_on:
      - redis
    restart: unless-stopped
volumes:
  redis_data:
COMPOSE

docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d

echo "=== NexusQuant deployed $(date) ==="
docker compose -f docker-compose.prod.yml ps
