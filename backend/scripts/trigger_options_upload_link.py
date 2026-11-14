#!/usr/bin/env python3
"""POST options CSV/ZIP URL to Nexus backend for analysis + training results."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Google Drive or HTTPS link to options 1m csv/zip")
    parser.add_argument("--api-base", default="http://65.0.136.146:8000")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    base = args.api_base.rstrip("/")
    body = json.dumps({"url": args.url, "persist": not args.no_persist}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/ai/options-data/from-link",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        print(json.dumps(out, indent=2, default=str))
        return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())