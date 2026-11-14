#!/usr/bin/env python3
"""Full session analysis on exported options 1m CSV (Nexus-aligned anchors)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.options_csv_analysis import analyze_csv_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default="/opt/cursor/artifacts/options_1m_upload/options_1m_2026-11_to_2026-11.csv",
    )
    parser.add_argument("--out-dir", default="/opt/cursor/artifacts")
    args = parser.parse_args()
    path = Path(args.csv)
    if not path.is_file():
        print(json.dumps({"error": f"missing {path}"}), file=sys.stderr)
        return 1
    report = analyze_csv_file(path, Path(args.out_dir))
    print(
        json.dumps(
            {
                "generatedAt": report["generatedAt"],
                "macro": report["macro"],
                "training": report.get("training"),
                "artifacts": report.get("artifacts"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())