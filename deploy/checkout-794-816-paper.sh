#!/usr/bin/env bash
# Detach the EC2 checkout at the #794 book plus the #816 exit stack
# (43208db0 on cursor/794-816-exits-3b1b) and recreate the backend with
# paper on and live off. That tree's production template arms live trading,
# so this script pins paper after the checkout. The sizing book stays the
# #794 ₹2,00,000 sleeve.
# Do not call deploy/ec2-update.sh: that script resets to BRANCH (default main).
set -euo pipefail

export HOME="${HOME:-/root}"
export GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL:-/root/.gitconfig}"

REPO=/opt/nexusquant/New-idea
ENV_FILE=/opt/nexusquant/env
SHA=43208db083dd97c48d1ce6b605510c75863b1002
SHORT=43208db0

git config --global --add safe.directory "$REPO" || true
git config --global --add safe.directory /opt/nexusquant || true

cd "$REPO"
git fetch origin cursor/794-816-exits-3b1b
git checkout --detach "$SHA"
test "$(git rev-parse HEAD)" = "$SHA"
echo "Detached at $(git rev-parse --short HEAD)"

touch "$ENV_FILE"
python3 - <<'PY'
from pathlib import Path

env_path = Path("/opt/nexusquant/env")
forced = {
    "ENABLE_LIVE_TRADING": "false",
    "PAPER_TRADING": "true",
    "PAPER_SLIPPAGE_ENABLED": "true",
    "PAPER_SIMULATE_BROKER_ORDERS": "true",
    "COMMIT_SHA": "43208db0",
    "FALLBACK_CAPITAL_INR": "200000",
    "MAX_SIZING_CAPITAL_INR": "200000",
    "ENTRY_EARLIEST_HOUR": "9",
    "ENTRY_EARLIEST_MINUTE": "20",
    "EXPLOSION_ENTRY_EARLIEST_HOUR": "9",
    "EXPLOSION_ENTRY_EARLIEST_MINUTE": "20",
}
lines = env_path.read_text().splitlines() if env_path.exists() else []
seen = set()
out = []
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    key = line.split("=", 1)[0]
    if key in forced:
        if key not in seen:
            out.append(f"{key}={forced[key]}")
            seen.add(key)
        continue
    out.append(line)
    seen.add(key)
for key, value in forced.items():
    if key not in seen:
        out.append(f"{key}={value}")
env_path.write_text("\n".join(out) + "\n")
print("pinned", ", ".join(f"{k}={v}" for k, v in forced.items()))
PY

if [ "$(id -u)" -eq 0 ]; then
  DOCKER=(docker)
else
  DOCKER=(sudo docker)
fi

"${DOCKER[@]}" compose -f docker-compose.prod.yml build backend
"${DOCKER[@]}" compose -f docker-compose.prod.yml up -d --force-recreate --no-deps backend

for i in $(seq 1 36); do
  if curl -sf --max-time 5 http://127.0.0.1:8000/api/deployment/status | grep -q "$SHORT"; then
    curl -sf http://127.0.0.1:8000/api/deployment/status
    exit 0
  fi
  echo "waiting for local API ($i)"
  sleep 5
done

echo "ERROR: local API did not report $SHORT"
curl -sv --max-time 10 http://127.0.0.1:8000/api/deployment/status || true
"${DOCKER[@]}" compose -f docker-compose.prod.yml logs --tail 80 backend || true
exit 1
