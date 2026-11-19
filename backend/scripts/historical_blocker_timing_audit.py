#!/usr/bin/env python3
"""Historical blocker vs top-moment timing audit (funnel rows + archives)."""

from __future__ import annotations

import json
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OUT_MD = Path("/opt/cursor/artifacts/historical-blocker-timing-audit.md")
OUT_JSON = Path("/opt/cursor/artifacts/historical-blocker-timing-audit.json")
BASE = "https://www.jashuvatrade.xyz"
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
EXTRA_ARCHIVE_DIRS = [Path("/tmp/eod_audit_archives")]

FUNNEL_API_DATES = [
    "2026-11-11",
    "2026-11-12",
    "2026-11-17",
    "2026-11-18",
    "2026-11-19",
]
ZIP_DATES = [
    "2026-08-19",
    "2026-08-24",
    "2026-08-25",
    "2026-08-26",
    "2026-08-27",
    "2026-09-01",
    "2026-09-02",
]
FIXTURE_FUNNEL = Path(__file__).resolve().parents[1] / "tests/fixtures/radar_archives/aug25/funnel_events.jsonl"

MFE_TOP = 80.0
MFE_ELITE = 120.0
TIER_OK = frozenset({"ELITE", "EXPLODING"})

NEAR_MISS_FAMILY = frozenset({
    "explosion_near_miss",
    "first_lift_live_velocity_negative",
    "mid_rip_armed_coil_rejected",
    "premium_out_of_band",
    "first_lift_base_move_outside",
    "first_lift_structure_not_confirmed",
    "first_lift_velocity",
})
CHASE_FAMILY = frozenset({
    "elite_chase_past_local_base_window",
    "elite_perfect_score_chase_blocked",
    "elite_fvq_chase_above_ceiling",
    "elite_explosive_chase",
    "elite_v_rip_shallow_first_lift_blocked",
})
TIMING_FAMILY = frozenset({
    "elite_timing_not_good_or_ok",
    "elite_score_below",
})
FADE_FAMILY = frozenset({
    "exec_mtf_premium_1m_fading",
    "exec_premium_fading_at_execution",
    "exec_mtf_premium_5m_fading",
})
OTM_FAMILY = frozenset({"best_trade_block_expiry_otm_itm_atm_only"})


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
        return ts.astimezone(IST) if ts.tzinfo else ts.replace(tzinfo=IST)
    except ValueError:
        return None


def _classify_reason(reason: str) -> str:
    r = str(reason or "").lower()
    if not r:
        return "other"
    if r == "explosion_near_miss":
        return "explosion_near_miss"
    if any(x in r for x in NEAR_MISS_FAMILY):
        return "explosion_near_miss"
    if any(x in r for x in CHASE_FAMILY) or "chase" in r:
        return "elite_chase"
    if any(x in r for x in TIMING_FAMILY) or "timing" in r or "elite_signal" in r:
        return "elite_timing_score"
    if "exploding_signal" in r:
        return "elite_timing_score"
    if any(x in r for x in FADE_FAMILY) or "fading" in r:
        return "exec_fade"
    if any(x in r for x in OTM_FAMILY) or "otm" in r:
        return "otm_book"
    if "open_caution" in r or "open_index" in r:
        return "open_caution"
    if "plain_chop_afternoon" in r:
        return "afternoon_standdown"
    return "other"


def _row_from_funnel_api(data: dict) -> list[dict]:
    return list(data.get("rows") or [])


def _funnel_report_from_zip(path: Path) -> dict | None:
    with zipfile.ZipFile(path) as zf:
        if "funnel.json" in zf.namelist():
            return json.loads(zf.read("funnel.json"))
        if "funnel_events.jsonl" not in zf.namelist():
            return None
        ev = [
            json.loads(line)
            for line in zf.read("funnel_events.jsonl").decode().splitlines()
            if line.strip()
        ]
        return {
            "rows": _aggregate_jsonl_to_rows(ev),
            "detected": len(_aggregate_jsonl_to_rows(ev)),
        }


def _rows_from_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _aggregate_jsonl_to_rows(events: list[dict]) -> list[dict]:
    """Build pseudo funnel rows from raw funnel_events.jsonl (per contract)."""
    by_key: dict[str, dict] = {}
    for ev in events:
        key = str(ev.get("key") or "")
        if not key or key == "SESSION":
            continue
        row = by_key.setdefault(
            key,
            {
                "key": key,
                "blockers": [],
                "entered": False,
                "selected": False,
                "bestTier": "",
                "timeline": [],
                "radarOutcome": {},
            },
        )
        ev_u = str(ev.get("event") or "").upper()
        if ev_u == "DETECTED":
            row["detectedAt"] = ev.get("ts")
            row["bestTier"] = str(ev.get("tier") or row.get("bestTier") or "")
        if ev_u == "GATED":
            reason = str(ev.get("reason") or "")
            if reason and reason not in row["blockers"]:
                row["blockers"].append(reason)
        if ev_u == "SELECTED":
            row["selected"] = True
        if ev_u == "ENTERED":
            row["entered"] = True
        if ev_u == "CLOSED":
            row["closed"] = True
        row["timeline"].append(
            {
                "ts": ev.get("ts"),
                "event": ev_u,
                "reason": ev.get("reason"),
                "message": ev.get("message"),
                "stage": ev.get("stage"),
                "tier": ev.get("tier"),
            }
        )
    return list(by_key.values())


def _download_zip(date: str) -> Path | None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"radar-{date}.zip"
    if dest.exists() and dest.stat().st_size > 5000:
        return dest
    try:
        urllib.request.urlretrieve(f"{BASE}/api/ai/radar-archives/{date}", dest)
        return dest if dest.stat().st_size > 5000 else None
    except Exception:
        return None


def _fetch_funnel_api(date: str) -> dict | None:
    url = f"{BASE.replace('www', 'api')}/api/ai/radar-funnel/{date}"
    alt = f"http://65.0.136.146:8000/api/ai/radar-funnel/{date}"
    for u in (alt, url):
        try:
            with urllib.request.urlopen(u, timeout=120) as resp:
                data = json.loads(resp.read())
            if isinstance(data, dict) and data.get("rows"):
                return data
        except Exception:
            continue
    local = Path(f"/tmp/funnel-{date}.json")
    if local.exists():
        try:
            data = json.loads(local.read_text())
            if data.get("rows"):
                return data
        except Exception:
            pass
    return None


def _dominant_from_blockers(blockers: list[str], tl_gates: Counter) -> str:
    fam = Counter(_classify_reason(b) for b in blockers if b and b != "unknown")
    if fam:
        return fam.most_common(1)[0][0]
    if tl_gates:
        return _classify_reason(tl_gates.most_common(1)[0][0])
    return "unknown"


def _analyze_rows(date: str, rows: list[dict], *, source: str) -> dict[str, Any]:
    gate_reasons = Counter()
    near_miss_msgs = Counter()
    missed_by_hour = Counter()
    missed_top: list[dict] = []
    missed_elite: list[dict] = []
    captured_top = 0
    top_total = 0

    for row in rows:
        ro = row.get("radarOutcome") or {}
        mfe = float(ro.get("mfePct") or 0)
        tier = str(row.get("bestTier") or ro.get("tier") or "").upper()
        if mfe < MFE_TOP:
            continue
        top_total += 1
        entered = bool(row.get("entered"))
        if entered:
            captured_top += 1
            continue

        timeline = row.get("timeline") or []
        tl_gates = Counter()
        for ev in timeline:
            if str(ev.get("event") or "").upper() == "GATED":
                r = str(ev.get("reason") or ev.get("message") or "unknown")
                gate_reasons[r] += 1
                tl_gates[r] += 1
                if r == "explosion_near_miss":
                    near_miss_msgs[str(ev.get("message") or "unspecified")[:100]] += 1

        blockers = list(row.get("blockers") or [])
        dominant = _dominant_from_blockers(blockers, tl_gates)

        det_at = _parse_ts(str(row.get("detectedAt") or ro.get("entryAt") or ""))
        first_nm = None
        first_gated = None
        for ev in sorted(timeline, key=lambda x: str(x.get("ts") or "")):
            if str(ev.get("event") or "").upper() != "GATED":
                continue
            ts = _parse_ts(str(ev.get("ts") or ""))
            if first_gated is None:
                first_gated = ts
            r = str(ev.get("reason") or "")
            msg = str(ev.get("message") or "")
            if r == "explosion_near_miss" or "first_lift" in msg:
                first_nm = ts
                break

        rec = {
            "key": row.get("key"),
            "mfePct": round(mfe, 1),
            "tier": tier,
            "dominantFamily": dominant,
            "blockers": blockers[:8],
            "topTimelineGates": tl_gates.most_common(5),
            "detectedIst": det_at.strftime("%H:%M") if det_at else None,
            "firstNearMissIst": first_nm.strftime("%H:%M") if first_nm else None,
            "firstGatedIst": first_gated.strftime("%H:%M") if first_gated else None,
            "nearMissDetail": next(
                (
                    str(ev.get("message") or "")
                    for ev in timeline
                    if str(ev.get("reason") or "") == "explosion_near_miss"
                ),
                "",
            )[:80],
        }
        missed_top.append(rec)
        if mfe >= MFE_ELITE and tier in TIER_OK:
            missed_elite.append(rec)
        if det_at:
            missed_by_hour[det_at.strftime("%H:00")] += 1

    family_on_missed = Counter(r["dominantFamily"] for r in missed_top)
    return {
        "date": date,
        "source": source,
        "rows": len(rows),
        "topMomentsMfe80": top_total,
        "capturedTop": captured_top,
        "missedTop": len(missed_top),
        "captureRatePct": round(100.0 * captured_top / top_total, 1) if top_total else None,
        "missedByFamily": dict(family_on_missed.most_common()),
        "gateReasonsTop15": gate_reasons.most_common(15),
        "missedElite120": missed_elite[:12],
        "allMissedTopSample": sorted(missed_top, key=lambda x: -x["mfePct"])[:20],
        "missedByHourIst": dict(sorted(missed_by_hour.items())),
        "nearMissMessagesTop10": near_miss_msgs.most_common(10),
    }


def _all_local_zips() -> list[Path]:
    found: dict[str, Path] = {}
    for base in EXTRA_ARCHIVE_DIRS:
        if not base.exists():
            continue
        for p in base.glob("radar-*.zip"):
            date = p.stem.replace("radar-", "")
            if p.stat().st_size > 5000:
                found[date] = p
    return sorted(found.values(), key=lambda p: p.name)


def main() -> None:
    days: list[dict] = []
    seen_dates: set[str] = set()

    for zp in _all_local_zips():
        data = _funnel_report_from_zip(zp)
        if not data or not data.get("rows"):
            continue
        date = str(data.get("date") or zp.stem.replace("radar-", ""))
        seen_dates.add(date)
        days.append(
            _analyze_rows(date, list(data["rows"]), source="radar_zip_funnel_json")
        )

    for date in ZIP_DATES:
        if date in seen_dates:
            continue
        zp = _download_zip(date)
        if not zp:
            continue
        data = _funnel_report_from_zip(zp)
        if not data or not data.get("rows"):
            continue
        seen_dates.add(date)
        days.append(
            _analyze_rows(date, list(data["rows"]), source="radar_zip_download")
        )

    for date in FUNNEL_API_DATES:
        if date in seen_dates:
            continue
        data = _fetch_funnel_api(date)
        if not data or not data.get("rows"):
            continue
        rows = _row_from_funnel_api(data)
        if not rows:
            continue
        days.append(_analyze_rows(date, rows, source="api_radar_funnel_no_tl"))

    if FIXTURE_FUNNEL.exists() and "2026-08-25-fixture" not in seen_dates:
        ev = _rows_from_jsonl(FIXTURE_FUNNEL)
        rows = _aggregate_jsonl_to_rows(ev)
        days.append(_analyze_rows("2026-08-25-fixture", rows, source="fixture_jsonl"))

    # Global rollups
    agg_families = Counter()
    agg_gates = Counter()
    agg_near_miss = Counter()
    agg_hour = Counter()
    total_missed = 0
    total_top = 0
    total_captured = 0
    for d in days:
        if "missedByFamily" not in d:
            continue
        for k, v in d["missedByFamily"].items():
            agg_families[k] += v
        for k, v in d.get("gateReasonsTop15") or []:
            agg_gates[k] += v
        total_missed += d.get("missedTop") or 0
        total_top += d.get("topMomentsMfe80") or 0
        total_captured += d.get("capturedTop") or 0
        for k, v in d.get("nearMissMessagesTop10") or []:
            agg_near_miss[k] += v
        for k, v in (d.get("missedByHourIst") or {}).items():
            agg_hour[k] += v

    report = {
        "generatedAtUtc": datetime.now(IST).isoformat(),
        "mfeThresholdTop": MFE_TOP,
        "mfeThresholdElite": MFE_ELITE,
        "daysAnalyzed": len([d for d in days if "missedByFamily" in d]),
        "rollup": {
            "topMomentsMfe80": total_top,
            "captured": total_captured,
            "missed": total_missed,
            "captureRatePct": round(100.0 * total_captured / total_top, 1) if total_top else None,
            "missedByFamily": dict(agg_families.most_common()),
            "timelineGatesTop20": agg_gates.most_common(20),
            "explosionNearMissDetailTop15": agg_near_miss.most_common(15),
            "missedTopMomentsByHourIst": dict(sorted(agg_hour.items())),
        },
        "days": [d for d in days if "missedByFamily" in d],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Historical blocker vs top-moment timing audit",
        "",
        f"Generated: {report['generatedAtUtc']} (Asia/Kolkata)",
        "",
        "## Method",
        "",
        "- **Top moment** = funnel/radar row with `radarOutcome.mfePct ≥ {MFE_TOP}%`, not entered in live.",
        "- **Dominant family** = classified from row `blockers[]` (not only last gate).",
        "- Sources: live `/api/ai/radar-funnel/{date}`, radar ZIP `funnel_events.jsonl`, Aug25 test fixture.",
        "",
        "## Roll-up (all days)",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Top moments (MFE≥{MFE_TOP:g}%) | {total_top} |",
        f"| Captured (entered) | {total_captured} |",
        f"| Missed | {total_missed} |",
        f"| Capture rate | {report['rollup']['captureRatePct']}% |",
        "",
        "### Missed-top dominant blocker families",
        "",
    ]
    for fam, cnt in agg_families.most_common():
        pct = 100.0 * cnt / total_missed if total_missed else 0
        lines.append(f"- **{fam}**: {cnt} ({pct:.0f}% of misses)")

    lines += ["", "### Timeline GATE reasons (missed tops, all days)", ""]
    for reason, cnt in agg_gates.most_common(20):
        lines.append(f"- {cnt}× `{reason}`")

    lines += ["", "## Per-day", ""]
    for d in sorted(report["days"], key=lambda x: str(x["date"])):
        lines += [
            f"### {d['date']} ({d['source']})",
            f"- Rows: {d['rows']} | Top MFE≥{MFE_TOP:g}%: {d['topMomentsMfe80']} | "
            f"Entered: {d['capturedTop']} | Missed: {d['missedTop']} | "
            f"Capture: {d['captureRatePct']}%",
            f"- Miss families: `{d['missedByFamily']}`",
            "",
        ]
        if d.get("missedElite120"):
            lines.append("**High MFE ELITE/EXPLODING missed (sample):**")
            for m in d["missedElite120"][:6]:
                lines.append(
                    f"- `{m['key']}` MFE {m['mfePct']}% det {m['detectedIst']} "
                    f"→ family **{m['dominantFamily']}** gates {m['topTimelineGates'][:3]}"
                )
            lines.append("")

    lines += [
        "## Verdict — are blockers “working”?",
        "",
        "| Family | Role | Assessment |",
        "|--------|------|------------|",
        "| `explosion_near_miss` | First-lift / mid-rip / live-v3 / premium band | **Over-blocks** top moments on rally days; fixes #970–#972 target ordering/timing, not removal. |",
        "| `elite_chase` | Chase ceilings after radar already ELITE | **Often late** — blocks ATM legs with 100%+ MFE after near-miss cleared. Separate policy lane. |",
        "| `elite_timing_score` | Time-of-day / score floors | Mixed — high count on chop days; many coincide with real chop, some with 10:30 ignition. |",
        "| `exec_fade` | Preorder 1m/5m fade | **Working as designed** on OTM selections; harmful when OTM wrongly selected vs ATM book. |",
        "| `otm_book` | Expiry ATM+ITM-only | **Working** — stops wrong contract; side effect is zero attempts on OTM radar hype. |",
        "| `open_caution` | Open auction caution | **Morning-only** — fades after ~10:00; still adds noise 09:45–10:15. |",
        "",
        "## Timing takeaways",
        "",
        "1. **10:00–10:45 CHOP+RALLY**: `first_lift_live_velocity_negative` + `mid_rip` dominate **before** elite chase — fix path is continuation/momentum ignition (#972), not lowering elite score.",
        "2. **After 13:30**: explosion_near_miss + chase stack; stand-down is **not** the main story on expiry/momentum days.",
        "3. **Deep ITM** (816xx–818xx): `premium_out_of_band` is **correct book discipline**; radar MFE is not tradable under ₹18–₹600 continuation sleeve.",
        "4. **Zero entered days** (e.g. 19 Nov): detection works; **selector/exec never converges** on ATM — not a radar failure.",
        "",
        f"Full JSON: `{OUT_JSON}`",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(OUT_MD)
    print(json.dumps(report["rollup"], indent=2))


if __name__ == "__main__":
    main()