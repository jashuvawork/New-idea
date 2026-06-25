#!/bin/bash
# Deploy NexusQuant frontend to Vercel
set -euo pipefail

cd "$(dirname "$0")/../frontend"

export VITE_API_URL="${VITE_API_URL:-https://api.nexusquant.uk}"
export VITE_POLL_MS="${VITE_POLL_MS:-3000}"

npm run build

if [ -n "${VERCEL_TOKEN:-}" ]; then
  npx vercel deploy --prod --token "$VERCEL_TOKEN" --yes
else
  npx vercel deploy --prod --yes
fi

echo "==> Frontend deployed to Vercel"
