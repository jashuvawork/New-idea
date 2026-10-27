#!/usr/bin/env bash
# Read-only: confirm paper #676 session flags after set-execution-mode --paper.
set -euo pipefail

API="${API:-http://127.0.0.1:8000/api/deployment/status}"

json="$(curl -sf "$API")"
python3 - <<'PY' "$json"
import json, sys
d = json.loads(sys.argv[1])
f = d.get("flags") or {}
checks = [
    ("paperTrading", True),
    ("enableLiveTrading", False),
    ("paper676EntryChoke", True),
    ("paper816ExitPack", True),
    ("liveBestTradesOnlyEnabled", False),
]
failed = []
for key, want in checks:
    got = f.get(key)
    if got is not want:
        failed.append(f"{key}: got {got!r}, want {want!r}")
if failed:
    print("Paper #676 session verify FAILED:")
    for line in failed:
        print(" ", line)
    sys.exit(1)
print("Paper #676 session verify OK")
print("commit:", d.get("commit"))
PY
