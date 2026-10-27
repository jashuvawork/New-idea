#!/usr/bin/env bash
# Read-only: confirm paper #676 session flags after full redeploy overlay + --paper.
set -euo pipefail

API="${API:-http://127.0.0.1:8000/api/deployment/status}"
EXPECT_ENTRY_EARLIEST="${EXPECT_ENTRY_EARLIEST:-09:16}"
EXPECT_EXPLOSION_ENTRY_EARLIEST="${EXPECT_EXPLOSION_ENTRY_EARLIEST:-09:16}"
EXPECT_OPEN_SIDE_START="${EXPECT_OPEN_SIDE_START:-09:15}"

json="$(curl -sf "$API")"
export JSON="$json"
export EXPECT_ENTRY_EARLIEST EXPECT_EXPLOSION_ENTRY_EARLIEST EXPECT_OPEN_SIDE_START
python3 - <<'PY'
import json, os, sys

d = json.loads(os.environ["JSON"])
f = d.get("flags") or {}
checks = [
    ("paperTrading", True),
    ("enableLiveTrading", False),
    ("paper676EntryChoke", True),
    ("liveBestTradesOnlyEnabled", False),
    ("paperLiveParityEnabled", False),
    ("entryEarliestIst", os.environ["EXPECT_ENTRY_EARLIEST"]),
    ("explosionEntryEarliestIst", os.environ["EXPECT_EXPLOSION_ENTRY_EARLIEST"]),
    ("openSideConfirmationStartIst", os.environ["EXPECT_OPEN_SIDE_START"]),
]
failed = []
for key, want in checks:
    got = f.get(key)
    if got != want:
        failed.append(f"{key}: got {got!r}, want {want!r}")
if failed:
    print("Paper #676 session verify FAILED:")
    for line in failed:
        print(" ", line)
    sys.exit(1)
print("Paper #676 session verify OK")
print("commit:", d.get("commit"))
print(
    "open:",
    f.get("entryEarliestIst"),
    "explosion",
    f.get("explosionEntryEarliestIst"),
    "sideConfirm",
    f.get("openSideConfirmationStartIst"),
)
PY
