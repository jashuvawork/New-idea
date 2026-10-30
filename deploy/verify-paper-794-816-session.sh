#!/usr/bin/env bash
# Read-only: confirm paper #794 / #816 session flags after redeploy on main.
set -euo pipefail

API_BASE="${API_BASE:-https://api.jashuvatrade.xyz}"
URL="${API_BASE%/}/api/deployment/status"

python3 << PY
import json
import os
import sys
import urllib.request

url = os.environ.get("VERIFY_URL", "$URL")
with urllib.request.urlopen(url, timeout=20) as resp:
    d = json.load(resp)

f = d.get("flags") or {}
failed = []

entry_want = os.environ.get("EXPECT_ENTRY_EARLIEST", "09:15")
open_setup_want = os.environ.get("EXPECT_OPEN_SETUP_START", "09:15")
checks = [
    ("paperTrading", True),
    ("enableLiveTrading", False),
    ("entryEarliestIst", entry_want),
    ("openSetupStartIst", open_setup_want),
    ("openCautionUntilIst", os.environ.get("EXPECT_OPEN_CAUTION_UNTIL", "09:45")),
    ("paperLiveParityEnabled", False),
]

for key, want in checks:
    got = f.get(key, d.get(key))
    if got != want:
        failed.append(f"{key}: got {got!r}, want {want!r}")

commit = str(d.get("commit") or "")
if not commit or commit.lower() in ("unknown", "none"):
    failed.append(f"commit: missing or invalid ({commit!r})")

if failed:
    print("Paper #794/#816 session verify FAILED:")
    for line in failed:
        print(" ", line)
    sys.exit(1)

print("Paper #794/#816 session verify OK")
print(" commit:", commit)
print(" entryEarliestIst:", f.get("entryEarliestIst"))
print(" paperTrading:", f.get("paperTrading"))
PY
