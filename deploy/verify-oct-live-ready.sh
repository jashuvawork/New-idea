#!/usr/bin/env bash
# Pre-open verification: Frozen October (Oct 1 rules) + optional live arm state.
#
#   # On EC2 (env file audit + local API):
#   sudo EXPECT_LIVE=false bash deploy/verify-oct-live-ready.sh
#
#   # After --arm-live (require readyForLive):
#   sudo EXPECT_LIVE=true LIVE_CAPITAL_INR=150000 bash deploy/verify-oct-live-ready.sh
#
#   # From laptop (API only, no env file):
#   BASE_URL=https://api.jashuvatrade.xyz EXPECT_LIVE=false bash deploy/verify-oct-live-ready.sh
#
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ENV_FILE="${ENV_FILE:-/opt/nexusquant/env}"
EXPECT_LIVE="${EXPECT_LIVE:-false}"
LIVE_CAPITAL_INR="${LIVE_CAPITAL_INR:-150000}"
CAPITAL_OVERLAY="${CAPITAL_OVERLAY:-${REPO_DIR}/deploy/env.live-150k.overlay}"
if [ "$LIVE_CAPITAL_INR" = "200000" ]; then
  CAPITAL_OVERLAY="${CAPITAL_OVERLAY:-${REPO_DIR}/deploy/env.live-200k.overlay}"
fi

fail() {
  echo "FAIL: $*" >&2
  echo "" >&2
  echo "Fix:" >&2
  echo "  sudo ENV_FILE=$ENV_FILE bash $REPO_DIR/deploy/apply-live-paper-parity-env.sh" >&2
  echo "  sudo LIVE_OVERLAY=$CAPITAL_OVERLAY bash $REPO_DIR/deploy/go-live-10k-monday.sh --prepare" >&2
  echo "  sudo LIVE_OVERLAY=$CAPITAL_OVERLAY LIVE_CAPITAL_INR=$LIVE_CAPITAL_INR bash $REPO_DIR/deploy/go-live-10k-monday.sh --arm-live" >&2
  exit 1
}

echo "=== Frozen October live readiness ==="
echo "API: $BASE_URL | expectLive=$EXPECT_LIVE | capital=₹$LIVE_CAPITAL_INR"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -sf --max-time 30 "$BASE_URL/health" -o "$TMP/health.json" || fail "GET /health failed"
python3 -c "
import json, sys
d = json.load(open('$TMP/health.json'))
w = d.get('loopWatchdog') or {}
if w.get('enabled') and w.get('lastBeatAgeSeconds') is not None:
    age = float(w['lastBeatAgeSeconds'])
    if age > float(w.get('staleSeconds') or 20):
        raise SystemExit(f'loop watchdog stale: {age}s')
print('  health: ok')
" || fail "loop watchdog unhealthy"

curl -sf --max-time 60 "$BASE_URL/api/deployment/status" -o "$TMP/status.json" \
  || fail "GET /api/deployment/status failed"
curl -sf --max-time 60 "$BASE_URL/api/deployment/readiness" -o "$TMP/readiness.json" \
  || fail "GET /api/deployment/readiness failed"

export TMP EXPECT_LIVE LIVE_CAPITAL_INR
python3 << 'PY' || fail "deployment status checks failed"
import json, os, sys

status = json.load(open(os.path.join(os.environ["TMP"], "status.json")))
ready = json.load(open(os.path.join(os.environ["TMP"], "readiness.json")))
expect_live = os.environ.get("EXPECT_LIVE", "false").lower() == "true"
expect_cap = float(os.environ.get("LIVE_CAPITAL_INR", "150000"))
expect_loss = expect_cap * 0.10

commit = status.get("commit")
if not commit:
    print("missing commit on deployment status", file=sys.stderr)
    sys.exit(1)

f = status.get("flags") or {}
frozen = status.get("frozenOctoberProfile") or {}
prof = f.get("livePaperProfile") or {}

print(f"  commit: {commit}")
print(f"  frozenOctoberProfileOk: {frozen.get('profileOk')}")
print(f"  livePaperProfileOk: {prof.get('profileOk')}")
print(f"  enableLiveTrading: {f.get('enableLiveTrading')}")
print(f"  paperTrading: {f.get('paperTrading')}")
print(f"  fallbackCapitalInr: {f.get('fallbackCapitalInr')}")
print(f"  dailyLossStopInr: {f.get('dailyLossStopInr')}")

if frozen.get("profileOk") is not True:
    print("frozen issues:", frozen.get("profileIssues"), file=sys.stderr)
    sys.exit(1)
if prof.get("profileOk") is not True:
    print("live paper profile issues:", prof.get("profileIssues"), file=sys.stderr)
    sys.exit(1)
if not frozen.get("padEntryGuardEnabled"):
    print("pad entry guard disabled", file=sys.stderr)
    sys.exit(1)

live = bool(f.get("enableLiveTrading"))
paper = bool(f.get("paperTrading"))
if expect_live:
    if not live or paper:
        print("expected LIVE armed but flags disagree", file=sys.stderr)
        sys.exit(1)
    cap = float(f.get("fallbackCapitalInr") or 0)
    loss = float(f.get("dailyLossStopInr") or 0)
    if abs(cap - expect_cap) > 1:
        print(f"capital {cap} != expected {expect_cap}", file=sys.stderr)
        sys.exit(1)
    if abs(loss - expect_loss) > 1:
        print(f"daily loss stop {loss} != expected {expect_loss}", file=sys.stderr)
        sys.exit(1)
    if ready.get("readyForLive") is not True:
        print("readyForLive false; steps:", ready.get("armLiveSteps"), file=sys.stderr)
        sys.exit(1)
    if f.get("entryGatesMatchPaper") is not True:
        print("entryGatesMatchPaper false — live must use paper entry gates", file=sys.stderr)
        sys.exit(1)
    if f.get("tradingRulesMatchPaper") is not True:
        print("tradingRulesMatchPaper false — live must mirror Oct paper rule stack", file=sys.stderr)
        sys.exit(1)
else:
    if live and not paper:
        print("WARN: live is armed; set EXPECT_LIVE=true to validate live session", file=sys.stderr)

checks = ready.get("checks") or {}
print(f"  readyForLive: {ready.get('readyForLive')}")
print(f"  frozenOctoberProfileOk (readiness): {checks.get('frozenOctoberProfileOk')}")
PY

if [ -f "$ENV_FILE" ] && [ -f "$REPO_DIR/deploy/audit-live-paper-env.sh" ]; then
  echo "Env file audit ($ENV_FILE)..."
  ENV_FILE="$ENV_FILE" REPO_DIR="$REPO_DIR" CAPITAL_OVERLAY="$CAPITAL_OVERLAY" \
    bash "$REPO_DIR/deploy/audit-live-paper-env.sh" || fail "env audit mismatch"
else
  echo "  (skip env audit — ENV_FILE missing or not on EC2)"
fi

echo "OK — Frozen October checks passed."
echo "Session checklists (entry/selection/flip/hold/exit): deploy/october-live-session-checklists.md"
