#!/usr/bin/env bash
# Vercel build — works from repo root OR frontend/ root directory.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f "frontend/package.json" ] && grep -q '"name": "nexusquant-frontend"' frontend/package.json 2>/dev/null; then
  APP_DIR="frontend"
elif [ -f "package.json" ] && grep -q '"name": "nexusquant-frontend"' package.json 2>/dev/null; then
  APP_DIR="."
else
  echo "ERROR: could not locate nexusquant-frontend package.json"
  exit 1
fi

echo "==> Vercel build in ${APP_DIR} (NODE_ENV=${NODE_ENV:-unset})"
npm ci --prefix "$APP_DIR" --include=dev
npm run build --prefix "$APP_DIR"
