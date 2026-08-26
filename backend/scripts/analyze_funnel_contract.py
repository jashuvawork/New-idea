#!/usr/bin/env python3
"""Pinpoint why one contract was missed on a session day.

Reads funnel_events.jsonl (telemetry dir or radar ZIP) and optional archive
milestones for a single symbol/side/strike. Prints a blocker timeline.

Usage:
  python -m scripts.analyze_funnel_contract --date 2026-08-26 \\
      --symbol SENSEX --side PUT --strike 77800

  python -m scripts.analyze_funnel_contract --funnel /path/funnel_events.jsonl \\
      --symbol SENSEX --side PUT --strike 77800

  # Demo on Aug25 archive (77800 PE was detected but never entered):
  python -m scripts.analyze_funnel_contract --date 2026-08-25 \\
      --funnel /opt/cursor/artifacts/radar-aug25/extracted/funnel_events.jsonl \\
      --symbol SENSEX --side PUT --strike 77800
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.radar_archive import archive_path, read_archive_entries
from app.services.radar_learning import funnel_path

IST = ZoneInfo("Asia/Kolkata")


def _contract_key(symbol: str, side: str, strike: float) -> str:
    return f"{symbol.upper()}:{side.upper()}:{strike:g}"


def _load_funnel_rows(
    *,
    date: str | None,
    funnel_file: Path | None,
) -> list[dict[str, Any]]:
    if funnel_file is not None:
        path = funnel_file
    elif date:
        path = funnel_path(date)
        if not path.exists():
            zip_path = archive_path(date)
            if zip_path.exists():
                with zipfile.ZipFile(zip_path, "r") as archive:
                    if "funnel_events.jsonl" in archive.namelist():
                        text = archive.read("funnel_events.jsonl").decode("utf-8")
                        return [
                            json.loads(line)
                            for line in text.splitlines()
                            if line.strip()
                        ]
        else:
            path = funnel_path(date)
    else:
        raise ValueError("Provide --date or --funnel")

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        return ts.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _time_hm(ts: datetime | None) -> str:
    return ts.strftime("%H:%M:%S") if ts else "?"


def analyze_contract(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    side: str,
    strike: float,
    archive_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = _contract_key(symbol, side, strike)
    events = [row for row in rows if str(row.get("key") or "") == key]
    events.sort(key=lambda row: str(row.get("ts") or ""))

    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        by_event[str(row.get("event") or "UNKNOWN").upper()].append(row)

    detected = by_event.get("DETECTED", [])
    gated = by_event.get("GATED", [])
    selected = by_event.get("SELECTED", [])
    entered = by_event.get("ENTERED", [])
    closed = by_event.get("CLOSED", [])
    ranked_out = by_event.get("RANKED_OUT", [])

    tier_counts: Counter[str] = Counter()
    moment_counts: Counter[str] = Counter()
    for row in detected:
        tier_counts[str(row.get("tier") or "?").upper()] += 1
        moment_counts[str(row.get("momentType") or row.get("moment_type") or "?")] += 1

    gate_reasons: Counter[str] = Counter()
    gate_messages: Counter[str] = Counter()
    gate_timeline: list[dict[str, Any]] = []
    for row in gated:
        reason = str(row.get("reason") or "unknown")
        gate_reasons[reason] += 1
        message = str(row.get("message") or "")
        if message:
            gate_messages[message] += 1
        gate_timeline.append({
            "ts": row.get("ts"),
            "time": _time_hm(_parse_ts(row.get("ts"))),
            "reason": reason,
            "message": message or None,
            "tier": row.get("tier"),
            "score": row.get("score"),
            "mode": row.get("mode"),
        })

    first_detected = detected[0] if detected else None
    last_detected = detected[-1] if detected else None
    best_detected = max(
        detected,
        key=lambda row: float(row.get("score") or 0),
        default=None,
    )

    if entered:
        verdict = "TRADED"
        verdict_detail = "At least one ENTERED event for this contract."
    elif selected:
        verdict = "SELECTED_NOT_FILLED"
        verdict_detail = "Selected but never entered (execution/preorder block)."
    elif gated and not detected:
        verdict = "GATED_NO_DETECTION"
        verdict_detail = "Gate block recorded without radar DETECTED rows."
    elif gated and len(gated) >= max(3, len(detected) // 4):
        verdict = "MISSED_AT_GATE"
        verdict_detail = (
            f"Radar fired {len(detected)}x but gates blocked repeatedly "
            f"({len(gated)} GATED events)."
        )
    elif gated and detected:
        top_reason = gate_reasons.most_common(1)[0][0] if gate_reasons else "unknown"
        top_msg = gate_messages.most_common(1)[0][0] if gate_messages else ""
        verdict = "MISSED_AT_GATE"
        verdict_detail = (
            f"Radar fired {len(detected)}x; recorded gate block: {top_reason}"
            + (f" ({top_msg})" if top_msg else "")
            + ". Never SELECTED — likely lost rank/allocation vs louder NIFTY leg."
        )
    elif detected:
        verdict = "MISSED_AFTER_DETECTION"
        verdict_detail = (
            f"Radar fired {len(detected)}x but contract was never SELECTED "
            "(rank / allocation / top-moment filter)."
        )
    else:
        verdict = "NO_RADAR"
        verdict_detail = "No funnel rows for this contract — not on radar watchlist."

    milestones: list[dict[str, Any]] = []
    if archive_entry:
        for item in archive_entry.get("milestones") or []:
            if isinstance(item, dict):
                milestones.append(item)
        alert = archive_entry.get("alert") or {}
    else:
        alert = {}

    return {
        "contract": {
            "key": key,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "strike": strike,
        },
        "verdict": verdict,
        "verdictDetail": verdict_detail,
        "counts": {
            "detected": len(detected),
            "gated": len(gated),
            "selected": len(selected),
            "entered": len(entered),
            "closed": len(closed),
            "rankedOut": len(ranked_out),
        },
        "detection": {
            "first": {
                "ts": first_detected.get("ts") if first_detected else None,
                "time": _time_hm(_parse_ts(first_detected.get("ts") if first_detected else None)),
                "tier": first_detected.get("tier") if first_detected else None,
                "score": first_detected.get("score") if first_detected else None,
                "momentType": first_detected.get("momentType") if first_detected else None,
            },
            "last": {
                "ts": last_detected.get("ts") if last_detected else None,
                "time": _time_hm(_parse_ts(last_detected.get("ts") if last_detected else None)),
                "tier": last_detected.get("tier") if last_detected else None,
                "score": last_detected.get("score") if last_detected else None,
                "momentType": last_detected.get("momentType") if last_detected else None,
            },
            "bestScore": {
                "ts": best_detected.get("ts") if best_detected else None,
                "time": _time_hm(_parse_ts(best_detected.get("ts") if best_detected else None)),
                "tier": best_detected.get("tier") if best_detected else None,
                "score": best_detected.get("score") if best_detected else None,
                "momentType": best_detected.get("momentType") if best_detected else None,
            },
            "tierCounts": dict(tier_counts),
            "momentTypeCounts": dict(moment_counts),
        },
        "gateBlockers": {
            "reasonCounts": dict(gate_reasons),
            "messageCounts": dict(gate_messages),
            "timeline": gate_timeline,
        },
        "archive": {
            "firstSeenAt": archive_entry.get("firstSeenAt") if archive_entry else None,
            "bestSeenAt": archive_entry.get("bestSeenAt") if archive_entry else None,
            "bestTier": archive_entry.get("tier") if archive_entry else None,
            "bestAlert": {
                "premium": alert.get("premium"),
                "peakMovePct": alert.get("peakMovePct"),
                "offLowMovePct": alert.get("offLowMovePct"),
                "tradeable": alert.get("tradeable"),
                "ictBaseArmed": alert.get("ictBaseArmed"),
                "ictVRipReady": alert.get("ictVRipReady"),
                "ictFlatThenVertical": alert.get("ictFlatThenVertical"),
                "ictBaseReadinessReason": alert.get("ictBaseReadinessReason"),
            } if alert else None,
            "milestoneCount": len(milestones),
            "milestones": milestones[-10:],
        },
        "timeline": events,
    }


def _print_report(report: dict[str, Any]) -> None:
    c = report["contract"]
    print(f"\n=== Funnel analysis: {c['key']} ===\n")
    print(f"Verdict: {report['verdict']}")
    print(f"  {report['verdictDetail']}\n")

    det = report["detection"]
    if det["first"]["ts"]:
        print("Radar DETECTED:")
        print(
            f"  first  {det['first']['time']}  tier={det['first']['tier']}  "
            f"score={det['first']['score']}  moment={det['first']['momentType']}"
        )
        print(
            f"  last   {det['last']['time']}  tier={det['last']['tier']}  "
            f"score={det['last']['score']}  moment={det['last']['momentType']}"
        )
        print(
            f"  best   {det['bestScore']['time']}  tier={det['bestScore']['tier']}  "
            f"score={det['bestScore']['score']}  moment={det['bestScore']['momentType']}"
        )
        print(f"  counts {report['counts']['detected']} detections — tiers: {det['tierCounts']}")
    else:
        print("Radar DETECTED: none")

    blockers = report["gateBlockers"]
    if blockers["timeline"]:
        print("\nGate blocks:")
        for row in blockers["timeline"]:
            msg = f" — {row['message']}" if row.get("message") else ""
            print(
                f"  {row['time']}  {row['reason']}  "
                f"tier={row.get('tier')} score={row.get('score')}{msg}"
            )
        if blockers["reasonCounts"]:
            print(f"\n  Top reasons: {blockers['reasonCounts']}")
    else:
        print("\nGate blocks: none recorded")

    arch = report["archive"]
    if arch.get("bestSeenAt"):
        print("\nArchive best snapshot:")
        ba = arch.get("bestAlert") or {}
        print(
            f"  bestSeenAt={arch['bestSeenAt']}  tier={arch['bestTier']}  "
            f"premium={ba.get('premium')}  peakMove={ba.get('peakMovePct')}%  "
            f"offLow={ba.get('offLowMovePct')}%  tradeable={ba.get('tradeable')}"
        )
        if ba.get("ictBaseReadinessReason"):
            print(f"  readiness={ba.get('ictBaseReadinessReason')}")

    counts = report["counts"]
    if counts["selected"] or counts["entered"]:
        print(
            f"\nExecution: selected={counts['selected']} entered={counts['entered']} "
            f"closed={counts['closed']}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze funnel blockers for one contract.")
    parser.add_argument("--date", help="Session date YYYY-MM-DD")
    parser.add_argument("--funnel", type=Path, help="Path to funnel_events.jsonl")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True, choices=["CALL", "PUT", "call", "put"])
    parser.add_argument("--strike", type=float, required=True)
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    if not args.date and not args.funnel:
        parser.error("Provide --date or --funnel")

    rows = _load_funnel_rows(date=args.date, funnel_file=args.funnel)
    archive_entry = None
    if args.date:
        key = _contract_key(args.symbol, args.side, args.strike)
        for entry in read_archive_entries(args.date):
            if str(entry.get("key") or "") == key:
                archive_entry = entry
                break

    report = analyze_contract(
        rows,
        symbol=args.symbol,
        side=args.side,
        strike=args.strike,
        archive_entry=archive_entry,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if not rows:
            print(
                f"No funnel data found for {args.date or args.funnel}.\n"
                "On production copy:\n"
                "  {TRADE_STORE_DIR}/radar_archives/telemetry/YYYY-MM-DD.funnel.jsonl\n"
                "or download radar-YYYY-MM-DD.zip before EOD finalize purges telemetry.",
                file=sys.stderr,
            )
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
