#!/usr/bin/env python3
"""Write open + post-open policy JSON for EOD archive (run after session confirm)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.engines.open_setup_policy import open_setup_policy_status


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/open-setup-policy.json")
    payload = open_setup_policy_status(Settings())
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
