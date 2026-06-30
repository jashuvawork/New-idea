#!/usr/bin/env bash
# Vercel ignoreCommand — exit 0 = SKIP build, exit 1 = BUILD.
# Saves free-tier quota when only backend/EC2 changes are pushed.
set -euo pipefail

# First deploy or shallow clone — always build.
if ! git rev-parse HEAD^ >/dev/null 2>&1; then
  echo "No parent commit — building"
  exit 1
fi

CHANGED="$(git diff --name-only HEAD^ HEAD 2>/dev/null || true)"
if [ -z "$CHANGED" ]; then
  echo "No diff — building"
  exit 1
fi

if echo "$CHANGED" | grep -qE '^(frontend/|vercel\.json|package\.json|scripts/vercel-build\.sh|scripts/vercel-should-build\.sh)'; then
  echo "Frontend or Vercel config changed — building"
  exit 1
fi

echo "Only backend/deploy changed — skipping Vercel build"
exit 0
