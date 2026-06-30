#!/bin/bash
# Deploy NexusQuant frontend to Vercel
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export VITE_API_URL="${VITE_API_URL:-}"
export VITE_POLL_MS="${VITE_POLL_MS:-2000}"

npm run vercel-build

if [ -n "${VERCEL_TOKEN:-}" ]; then
  npx vercel deploy --prod --token "$VERCEL_TOKEN" --yes
else
  npx vercel deploy --prod --yes
fi

echo "==> Frontend deployed to Vercel"
