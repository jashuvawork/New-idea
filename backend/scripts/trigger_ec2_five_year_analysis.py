#!/usr/bin/env python3
"""From cloud VM: trigger EC2 five-year Upstox job via Nexus API and poll status."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def _get(url: str, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"}, data=b"{}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://65.0.136.146:8000")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--wait", action="store_true", help="Poll until completed or failed")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-wait-minutes", type=float, default=90.0)
    args = parser.parse_args()
    base = args.api_base.rstrip("/")
    qs = urllib.parse.urlencode({"symbol": args.symbol, "years": args.years})
    start_url = f"{base}/api/ai/upstox-five-year-analysis/start?{qs}"
    status_url = f"{base}/api/ai/upstox-five-year-analysis/status?symbol={args.symbol}"

    try:
        started = _post(start_url, timeout=60)
        print(json.dumps(started, indent=2))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(body, file=sys.stderr)
        return 1

    if not args.wait:
        return 0

    deadline = time.time() + args.max_wait_minutes * 60
    while time.time() < deadline:
        time.sleep(args.poll_seconds)
        try:
            st = _get(status_url, timeout=30)
            print(json.dumps(st, indent=2))
            if st.get("status") in ("completed", "failed", "idle"):
                return 0 if st.get("status") == "completed" else 2
        except urllib.error.URLError as exc:
            print(json.dumps({"pollError": str(exc)}))
    print(json.dumps({"status": "timeout"}))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
