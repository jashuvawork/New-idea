"""Local-base audit week — daily 5-layer proof that we are ahead at the base.

Layers (from the live success framework):
1. Detection lead — radar sees the move before vertical (earlyRecall, leadSeconds)
2. Entry pad — trades open with localBaseBaseRelPct in the 2–20% window
3. Causality — index helpers / drift confirm at entry
4. Tier timing — BUILDING / FTV / V / early EXPLODING, not late ELITE chase
5. MFE capture — realized PnL vs radar archive peak move
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import audit_week_local_base_overrides, get_settings

IST = ZoneInfo("Asia/Kolkata")

# Pass thresholds for the validation week.
LAYER1_EARLY_RECALL_TARGET_PCT = 50.0
LAYER1_AVG_LEAD_TARGET_SECONDS = 15.0
LAYER2_EARLY_PAD_TARGET_PCT = 70.0  # share of entries with pad <= 20%
LAYER2_MAX_PAD_PCT = 20.0
LAYER3_CAUSALITY_TARGET_PCT = 50.0
LAYER4_EARLY_TIER_TARGET_PCT = 50.0
LAYER5_MFE_CAPTURE_TARGET_PCT = 35.0

EARLY_MOMENT_TYPES = frozenset({
    "v",
    "first_lift_local_base",
    "armed_base_local_base",
    "flat_then_vertical",
    "building_local_base_lift_ready",
})
EARLY_TIERS = frozenset({"BUILDING", "EXPLODING", "WATCH"})


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct(part: float, whole: float) -> float:
    if whole <= 0:
        return 0.0
    return round(part / whole * 100.0, 1)


def _layer_status(passed: bool, *, partial: bool = False) -> str:
    if passed:
        return "PASS"
    if partial:
        return "PARTIAL"
    return "FAIL"


def _score_layer(passed: bool, partial: bool = False) -> int:
    if passed:
        return 2
    if partial:
        return 1
    return 0


def _trade_key(trade: Mapping[str, Any]) -> str:
    symbol = str(trade.get("symbol") or "").upper()
    side = str(trade.get("side") or "").upper()
    strike = _number(trade.get("strike"))
    if symbol and side and strike > 0:
        return f"{symbol}:{side}:{strike:g}"
    ctx = trade.get("entryContext") or {}
    return str(ctx.get("radarKey") or "")


def _is_early_tier_entry(ctx: Mapping[str, Any]) -> bool:
    tier = str(ctx.get("explosionTier") or "").upper()
    moment = str(ctx.get("momentType") or "").lower()
    if moment in EARLY_MOMENT_TYPES:
        return True
    if tier in EARLY_TIERS:
        return True
    if bool(ctx.get("ictFirstLift") or ctx.get("firstLiftCapture")):
        return True
    if bool(ctx.get("ictArmedBaseLaunch") or ctx.get("armedBaseCapture")):
        return True
    if bool(ctx.get("ictFlatThenVertical")):
        return True
    if bool(ctx.get("indexConfirmedFtv")):
        return True
    auth = str(ctx.get("ftvAuthorizationMode") or "").upper()
    if auth in {"BUILDING_RIP_FTV", "TOP_FTV_A", "WINNER_LOCAL_BASE"}:
        return True
    return False


def _has_causality(ctx: Mapping[str, Any]) -> bool:
    return bool(
        ctx.get("indexConfirmedFtv")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("ictFirstLift")
        or ctx.get("ictArmedBaseLaunch")
        or ctx.get("armedBaseCapture")
        or ctx.get("firstLiftCapture")
        or str(ctx.get("ftvAuthorizationMode") or "").upper()
        in {"BUILDING_RIP_FTV", "TOP_FTV_A", "S_STRICT"}
    )


def _analyze_trades(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    opened = [t for t in trades if str(t.get("status") or "").upper() in {"OPEN", "CLOSED"}]
    pads: list[float] = []
    early_pad = 0
    causality_ok = 0
    early_tier = 0
    mfe_ratios: list[float] = []

    for trade in opened:
        ctx = trade.get("entryContext") or {}
        pad = _number(ctx.get("localBaseBaseRelPct"))
        if pad > 0:
            pads.append(pad)
            if pad <= LAYER2_MAX_PAD_PCT:
                early_pad += 1
        if _has_causality(ctx):
            causality_ok += 1
        if _is_early_tier_entry(ctx):
            early_tier += 1

        entry_prem = _number(trade.get("entryPremium"))
        exit_prem = _number(trade.get("exitPremium") or trade.get("currentPremium"))
        if entry_prem > 0 and exit_prem > 0 and str(trade.get("status")) == "CLOSED":
            realized_pct = (exit_prem - entry_prem) / entry_prem * 100.0
            peak_pct = _number(ctx.get("peakMovePct") or ctx.get("dailyMovePct"))
            if peak_pct > 0:
                mfe_ratios.append(min(1.0, max(0.0, realized_pct / peak_pct)))

    pad_count = len(pads)
    return {
        "tradeCount": len(opened),
        "closedCount": sum(1 for t in opened if str(t.get("status")) == "CLOSED"),
        "avgEntryPadPct": round(sum(pads) / pad_count, 1) if pad_count else None,
        "medianEntryPadPct": round(sorted(pads)[pad_count // 2], 1) if pad_count else None,
        "earlyPadCount": early_pad,
        "earlyPadPct": _pct(early_pad, pad_count),
        "causalityCount": causality_ok,
        "causalityPct": _pct(causality_ok, len(opened)),
        "earlyTierCount": early_tier,
        "earlyTierPct": _pct(early_tier, len(opened)),
        "avgMfeCaptureRatio": (
            round(sum(mfe_ratios) / len(mfe_ratios), 3) if mfe_ratios else None
        ),
        "mfeCapturePct": _pct(
            sum(1 for r in mfe_ratios if r >= 0.35),
            len(mfe_ratios),
        ),
        "trades": [
            {
                "id": trade.get("id"),
                "key": _trade_key(trade),
                "status": trade.get("status"),
                "tier": (trade.get("entryContext") or {}).get("explosionTier"),
                "momentType": (trade.get("entryContext") or {}).get("momentType"),
                "localBaseBaseRelPct": (trade.get("entryContext") or {}).get(
                    "localBaseBaseRelPct"
                ),
                "indexConfirmedFtv": (trade.get("entryContext") or {}).get(
                    "indexConfirmedFtv"
                ),
                "ftvAuthorizationMode": (trade.get("entryContext") or {}).get(
                    "ftvAuthorizationMode"
                ),
                "pnlInr": trade.get("pnlInr"),
            }
            for trade in opened
        ],
    }


def _analyze_detection(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    events = list(scorecard.get("events") or [])
    early = [e for e in events if str(e.get("capture") or "").upper() == "EARLY"]
    late = [e for e in events if str(e.get("capture") or "").upper() == "LATE"]
    missed = [e for e in events if str(e.get("capture") or "").upper() == "MISSED"]
    leads = [
        _number(e.get("leadSeconds"))
        for e in early
        if e.get("leadSeconds") is not None
    ]
    early_recall = _number(scorecard.get("earlyRecallPct"))
    avg_lead = round(sum(leads) / len(leads), 1) if leads else None
    return {
        "truthCount": int(scorecard.get("truthCount") or 0),
        "earlyDetected": len(early),
        "lateDetected": len(late),
        "missed": len(missed),
        "earlyRecallPct": early_recall,
        "recallPct": _number(scorecard.get("recallPct")),
        "avgLeadSeconds": avg_lead,
        "missedHighValue": [
            {
                "key": e.get("key"),
                "peakMovePct": e.get("peakMovePct"),
                "capture": e.get("capture"),
            }
            for e in sorted(missed, key=lambda r: -_number(r.get("peakMovePct")))[:5]
        ],
    }


def _analyze_mfe_from_archives(
    archives: list[Mapping[str, Any]],
    trades: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Layer 5 from radar archive outcomes vs closed trade PnL."""
    trades_by_key: dict[str, list[Mapping[str, Any]]] = {}
    for trade in trades:
        key = _trade_key(trade)
        if key:
            trades_by_key.setdefault(key, []).append(trade)

    ratios: list[float] = []
    rows: list[dict[str, Any]] = []
    for row in archives:
        key = str(row.get("key") or "")
        outcome = row.get("outcome") or {}
        mfe_pct = _number(outcome.get("mfePct"))
        if mfe_pct <= 0:
            continue
        matched = [
            t for t in trades_by_key.get(key, [])
            if str(t.get("status")) == "CLOSED"
        ]
        if not matched:
            continue
        for trade in matched:
            entry = _number(trade.get("entryPremium"))
            exit_p = _number(trade.get("exitPremium"))
            if entry <= 0 or exit_p <= 0:
                continue
            realized = (exit_p - entry) / entry * 100.0
            ratio = min(1.0, max(0.0, realized / mfe_pct))
            ratios.append(ratio)
            rows.append({
                "key": key,
                "mfePct": round(mfe_pct, 1),
                "realizedPct": round(realized, 1),
                "captureRatio": round(ratio, 3),
                "pnlInr": trade.get("pnlInr"),
            })

    good = sum(1 for r in ratios if r >= 0.35)
    return {
        "matchedCount": len(ratios),
        "avgCaptureRatio": round(sum(ratios) / len(ratios), 3) if ratios else None,
        "captureAbove35Pct": _pct(good, len(ratios)),
        "rows": rows,
    }


def _build_checklist(
    layer1: Mapping[str, Any],
    trade_stats: Mapping[str, Any],
    mfe_stats: Mapping[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    early_recall = _number(layer1.get("earlyRecallPct"))
    items.append({
        "id": "detection_lead",
        "label": "Radar detects at local base before vertical",
        "metric": f"earlyRecall {early_recall}% (target ≥{LAYER1_EARLY_RECALL_TARGET_PCT}%)",
        "status": _layer_status(
            early_recall >= LAYER1_EARLY_RECALL_TARGET_PCT,
            partial=early_recall >= LAYER1_EARLY_RECALL_TARGET_PCT * 0.7,
        ),
    })

    avg_lead = layer1.get("avgLeadSeconds")
    lead_val = _number(avg_lead)
    items.append({
        "id": "detection_lead_seconds",
        "label": "Average detection lead time before vertical",
        "metric": (
            f"avgLead {avg_lead}s (target ≥{LAYER1_AVG_LEAD_TARGET_SECONDS}s)"
            if avg_lead is not None
            else "no lead data"
        ),
        "status": _layer_status(
            avg_lead is not None and lead_val >= LAYER1_AVG_LEAD_TARGET_SECONDS,
            partial=avg_lead is not None and lead_val >= LAYER1_AVG_LEAD_TARGET_SECONDS * 0.5,
        ),
    })

    early_pad = _number(trade_stats.get("earlyPadPct"))
    items.append({
        "id": "entry_pad",
        "label": "Entries taken within 20% of local base",
        "metric": (
            f"earlyPad {early_pad}% (target ≥{LAYER2_EARLY_PAD_TARGET_PCT}%)"
            if trade_stats.get("tradeCount")
            else "no trades — check radar-only layers"
        ),
        "status": _layer_status(
            trade_stats.get("tradeCount", 0) > 0
            and early_pad >= LAYER2_EARLY_PAD_TARGET_PCT,
            partial=trade_stats.get("tradeCount", 0) > 0
            and early_pad >= LAYER2_EARLY_PAD_TARGET_PCT * 0.6,
        )
        if trade_stats.get("tradeCount")
        else "SKIP",
    })

    causality = _number(trade_stats.get("causalityPct"))
    items.append({
        "id": "causality",
        "label": "Index helpers / FTV causality at entry",
        "metric": (
            f"causality {causality}% (target ≥{LAYER3_CAUSALITY_TARGET_PCT}%)"
            if trade_stats.get("tradeCount")
            else "no trades"
        ),
        "status": _layer_status(
            trade_stats.get("tradeCount", 0) > 0
            and causality >= LAYER3_CAUSALITY_TARGET_PCT,
            partial=trade_stats.get("tradeCount", 0) > 0
            and causality >= LAYER3_CAUSALITY_TARGET_PCT * 0.6,
        )
        if trade_stats.get("tradeCount")
        else "SKIP",
    })

    early_tier = _number(trade_stats.get("earlyTierPct"))
    items.append({
        "id": "tier_timing",
        "label": "BUILDING / FTV / V / early EXPLODING — not late ELITE chase",
        "metric": (
            f"earlyTier {early_tier}% (target ≥{LAYER4_EARLY_TIER_TARGET_PCT}%)"
            if trade_stats.get("tradeCount")
            else "no trades"
        ),
        "status": _layer_status(
            trade_stats.get("tradeCount", 0) > 0
            and early_tier >= LAYER4_EARLY_TIER_TARGET_PCT,
            partial=trade_stats.get("tradeCount", 0) > 0
            and early_tier >= LAYER4_EARLY_TIER_TARGET_PCT * 0.6,
        )
        if trade_stats.get("tradeCount")
        else "SKIP",
    })

    mfe_cap = _number(mfe_stats.get("captureAbove35Pct") or trade_stats.get("mfeCapturePct"))
    items.append({
        "id": "mfe_capture",
        "label": "Capture ≥35% of archive MFE on closed trades",
        "metric": (
            f"mfeCapture {mfe_cap}% (target ≥{LAYER5_MFE_CAPTURE_TARGET_PCT}%)"
            if mfe_stats.get("matchedCount") or trade_stats.get("closedCount")
            else "no closed trades"
        ),
        "status": _layer_status(
            (mfe_stats.get("matchedCount") or 0) > 0
            and mfe_cap >= LAYER5_MFE_CAPTURE_TARGET_PCT,
            partial=(mfe_stats.get("matchedCount") or 0) > 0
            and mfe_cap >= LAYER5_MFE_CAPTURE_TARGET_PCT * 0.6,
        )
        if mfe_stats.get("matchedCount") or trade_stats.get("closedCount")
        else "SKIP",
    })

    return items


def _overall_score(checklist: list[Mapping[str, Any]]) -> dict[str, Any]:
    scored = [
        item for item in checklist if str(item.get("status")) != "SKIP"
    ]
    points = 0
    max_points = len(scored) * 2
    for item in scored:
        status = str(item.get("status"))
        if status == "PASS":
            points += 2
        elif status == "PARTIAL":
            points += 1
    pct = round(points / max_points * 100.0, 1) if max_points else 0.0
    return {
        "points": points,
        "maxPoints": max_points,
        "scorePct": pct,
        "verdict": (
            "AHEAD"
            if pct >= 75
            else ("ON_TRACK" if pct >= 50 else "BEHIND")
        ),
    }


def build_local_base_audit(date: str) -> dict[str, Any]:
    """Build the 5-layer local-base audit for one IST session date."""
    from app.services import trade_store
    from app.services.radar_archive import read_archive_entries
    from app.services.radar_learning import analyze_hindsight, build_funnel_report

    settings = get_settings()
    scorecard = analyze_hindsight(date)
    funnel = build_funnel_report(date)
    day = trade_store.get_day_detail(date) or {}
    trades = list(day.get("trades") or [])
    archives = read_archive_entries(date)

    layer1 = _analyze_detection(scorecard)
    trade_stats = _analyze_trades(trades)
    mfe_stats = _analyze_mfe_from_archives(archives, trades)
    checklist = _build_checklist(layer1, trade_stats, mfe_stats)
    overall = _overall_score(checklist)

    return {
        "date": date,
        "generatedAt": datetime.now(IST).isoformat(),
        "auditWeekEnabled": bool(settings.local_base_audit_week_enabled),
        "auditWeekOverrides": (
            audit_week_local_base_overrides()
            if settings.local_base_audit_week_enabled
            else {}
        ),
        "targets": {
            "earlyRecallPct": LAYER1_EARLY_RECALL_TARGET_PCT,
            "avgLeadSeconds": LAYER1_AVG_LEAD_TARGET_SECONDS,
            "earlyPadPct": LAYER2_EARLY_PAD_TARGET_PCT,
            "maxEntryPadPct": LAYER2_MAX_PAD_PCT,
            "causalityPct": LAYER3_CAUSALITY_TARGET_PCT,
            "earlyTierPct": LAYER4_EARLY_TIER_TARGET_PCT,
            "mfeCapturePct": LAYER5_MFE_CAPTURE_TARGET_PCT,
        },
        "layers": {
            "detectionLead": layer1,
            "entryPad": {
                "avgPadPct": trade_stats.get("avgEntryPadPct"),
                "medianPadPct": trade_stats.get("medianEntryPadPct"),
                "earlyPadPct": trade_stats.get("earlyPadPct"),
                "tradeCount": trade_stats.get("tradeCount"),
            },
            "causality": {
                "causalityPct": trade_stats.get("causalityPct"),
                "tradeCount": trade_stats.get("tradeCount"),
            },
            "tierTiming": {
                "earlyTierPct": trade_stats.get("earlyTierPct"),
                "tradeCount": trade_stats.get("tradeCount"),
            },
            "mfeCapture": mfe_stats,
        },
        "funnel": {
            "detected": funnel.get("detected"),
            "selected": funnel.get("selected"),
            "entered": funnel.get("entered"),
            "detectionToEntryPct": funnel.get("detectionToEntryPct"),
            "entryWinRatePct": funnel.get("entryWinRatePct"),
        },
        "checklist": checklist,
        "overall": overall,
        "trades": trade_stats.get("trades"),
    }


def build_local_base_audit_week(
    start_date: str,
    *,
    days: int = 5,
) -> dict[str, Any]:
    """Roll up Mon–Fri (or N days) local-base audit scores."""
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    daily: list[dict[str, Any]] = []
    for offset in range(max(1, min(days, 7))):
        target = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        try:
            daily.append(build_local_base_audit(target))
        except (ValueError, OSError):
            daily.append({"date": target, "error": "no_data"})

    valid = [d for d in daily if "overall" in d]
    avg_score = (
        round(sum(_number(d["overall"]["scorePct"]) for d in valid) / len(valid), 1)
        if valid
        else 0.0
    )
    ahead_days = sum(1 for d in valid if d["overall"]["verdict"] == "AHEAD")
    return {
        "startDate": start_date,
        "days": days,
        "generatedAt": datetime.now(IST).isoformat(),
        "daily": daily,
        "summary": {
            "sessionsScored": len(valid),
            "avgScorePct": avg_score,
            "aheadDays": ahead_days,
            "verdict": (
                "AHEAD"
                if avg_score >= 75
                else ("ON_TRACK" if avg_score >= 50 else "BEHIND")
            ),
        },
    }
