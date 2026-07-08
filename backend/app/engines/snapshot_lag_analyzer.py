"""Snapshot lag analyzer — where monitoring vs entry gates diverge."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.engines.chop_day_guards import chop_guard_summary
from app.engines.expiry_day_guards import expiry_guard_summary
from app.engines.morning_premium_capture import (
    in_all_day_explosion_window,
    in_afternoon_premium_capture_window,
    in_morning_premium_capture_window,
    is_all_day_explosion_alert,
    is_premium_capture_alert,
)
from app.engines.premium_filter import premium_in_band
from app.engines.trade_selector import find_best_entry
from app.models.schemas import AutoTraderState, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _misleading_flags(chop: dict[str, Any], expiry: dict[str, Any]) -> list[dict[str, str]]:
    """Dashboard labels that confuse operators."""
    notes: list[dict[str, str]] = []
    if expiry.get("eveningBlock") and not expiry.get("eveningBlockActive"):
        notes.append({
            "field": "expiryGuards.eveningBlock",
            "issue": "Shows true after 14:00 IST even when expiry is NOT today",
            "useInstead": "expiryGuards.eveningBlockActive (only blocks when expirySession=true)",
        })
    if expiry.get("expirySession") and not expiry.get("entriesAllowed"):
        notes.append({
            "field": "expiryGuards.entriesAllowed",
            "issue": f"Session blocked: {expiry.get('blockReason')}",
            "useInstead": "Check preExpirySymbols vs expirySymbols",
        })
    if chop.get("dayMode") == "MOMENTUM RALLY" and not chop.get("momentumRallyWindow"):
        notes.append({
            "field": "dayMode",
            "issue": "Day mode label may be stale vs current time window",
            "useInstead": "chopGuards.momentumRallyWindow",
        })
    return notes


def _analyze_explosion_gaps(
    symbol: str,
    snap: SymbolSnapshot,
    settings,
) -> list[dict[str, Any]]:
    """Per-alert: visible on radar but why entry may fail."""
    gaps: list[dict[str, Any]] = []
    chart = snap.spotChart
    min_score = settings.aggressive_min_explosion_score

    for alert in snap.explosionAlerts or []:
        tier = str(alert.get("tier") or "")
        if tier not in ("BUILDING", "EXPLODING", "ELITE", "WATCH"):
            continue
        score = float(alert.get("explosionScore") or 0)
        daily_move = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
        effective_min = min_score
        if daily_move >= settings.all_day_explosion_session_move_min_pct:
            effective_min = min(effective_min, settings.all_day_explosion_min_score)

        blockers: list[str] = []
        if not alert.get("tradeable"):
            blockers.append("not_tradeable_tier")
        if score < effective_min:
            blockers.append(f"score_{score:.1f}<{effective_min:.0f}")
        prem = alert.get("premium")
        if not premium_in_band(prem, mode="explosion"):
            blockers.append("premium_out_of_band")

        capture = is_premium_capture_alert(alert, chart)
        all_day = is_all_day_explosion_alert(alert, chart)
        if tier == "BUILDING" and not capture and not all_day:
            blockers.append("building_outside_capture_window")

        side = str(alert.get("side") or "").upper()
        breadth = (snap.breadth.bias or "NEUTRAL").upper()
        chart_dir = (chart.direction or "NEUTRAL").upper() if chart else "NEUTRAL"
        if chart_dir == "BULLISH" and side == "PUT" and not all_day and not capture:
            blockers.append("put_vs_bullish_chart")
        if chart_dir == "BEARISH" and side == "CALL" and not all_day and not capture:
            blockers.append("call_vs_bearish_chart")

        if blockers or alert.get("allDayExplosion") or daily_move >= 40:
            gaps.append({
                "symbol": symbol,
                "side": side,
                "strike": alert.get("strike"),
                "tier": tier,
                "score": score,
                "dailyMovePct": daily_move,
                "tradeable": bool(alert.get("tradeable")),
                "morningCapture": bool(alert.get("morningCapture")),
                "afternoonCapture": bool(alert.get("afternoonCapture")),
                "allDayExplosion": bool(alert.get("allDayExplosion")),
                "premiumCapture": bool(alert.get("premiumCapture")),
                "blockers": blockers,
                "wouldNeed": _fix_hint(blockers),
            })
    return gaps


def _fix_hint(blockers: list[str]) -> str:
    if any("score" in b for b in blockers):
        return "Lower min score or wait for tier upgrade / session move"
    if "building_outside_capture_window" in blockers:
        return "Enable all-day explosion window or wait for EXPLODING tier"
    if "put_vs_bullish_chart" in blockers:
        return "Premium-led bypass (PE rip vs bullish index chart)"
    if "not_tradeable_tier" in blockers:
        return "Velocity/volume spike needed for tradeable tier"
    return "Review pretrade + directional lock"


def analyze_snapshot_lag(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> dict[str, Any]:
    """Rules-based gap report — what we see vs what gates allow."""
    settings = get_settings()
    state = state or get_state()
    chop = chop_guard_summary(state, snapshots)
    expiry = expiry_guard_summary(state, snapshots)
    bad_day = chop.get("badDayRouting") or {}

    explosion_gaps: list[dict[str, Any]] = []
    all_day_alerts: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        explosion_gaps.extend(_analyze_explosion_gaps(sym, snap, settings))
        for alert in snap.explosionAlerts or []:
            if alert.get("allDayExplosion"):
                all_day_alerts.append({
                    "symbol": sym,
                    "side": alert.get("side"),
                    "strike": alert.get("strike"),
                    "score": alert.get("explosionScore"),
                    "tier": alert.get("tier"),
                    "dailyMovePct": alert.get("dailyMovePct"),
                })

    best = find_best_entry(snapshots, state)
    skipped = list(state.skipped or [])

    session_blocks = [s for s in skipped if s.get("symbol") == "SESSION"]
    candidate_blocks = [s for s in skipped if s.get("symbol") != "SESSION"]

    avg_tqs = 0.0
    live = [s for s in snapshots.values() if s.dataAvailable]
    if live:
        avg_tqs = sum(float(s.tradeQualityScore or 0) for s in live) / len(live)
    lag_score = _lag_score(explosion_gaps, session_blocks, best, avg_tqs)

    return {
        "at": datetime.now(IST).isoformat(),
        "lagScore": lag_score,
        "summary": _summary_text(explosion_gaps, session_blocks, best, chop, expiry),
        "windows": {
            "morningCapture": in_morning_premium_capture_window(),
            "afternoonCapture": in_afternoon_premium_capture_window(),
            "allDayExplosion": in_all_day_explosion_window(),
            "momentumRally": chop.get("momentumRallyWindow"),
            "middayChop": chop.get("middayChopWindow"),
        },
        "misleadingLabels": _misleading_flags(chop, expiry),
        "sessionBlocks": session_blocks,
        "candidateBlocks": candidate_blocks[:12],
        "explosionGaps": explosion_gaps[:16],
        "allDayExplosionAlerts": all_day_alerts[:12],
        "bestCandidate": (
            {
                "symbol": best.symbol,
                "side": best.side.value if hasattr(best.side, "value") else str(best.side),
                "mode": best.mode,
                "score": best.score,
                "strike": best.strike,
            }
            if best
            else None
        ),
        "nearExpirySymbols": expiry.get("nearExpirySymbols") or [],
        "preExpiryAlternates": (bad_day.get("preExpiryAlternates") or {}),
        "badDayMinRank": bad_day.get("minRankFloor"),
        "entriesAllowed": expiry.get("entriesAllowed", True),
        "tqsBySymbol": {
            sym: round(float(s.tradeQualityScore or 0), 1)
            for sym, s in snapshots.items()
            if s.dataAvailable
        },
    }


def _lag_score(
    gaps: list[dict[str, Any]],
    session_blocks: list[dict],
    best: Any,
    tqs: float,
) -> float:
    """0=aligned, 100=severe monitoring/entry mismatch."""
    score = 0.0
    blocked_radar = sum(1 for g in gaps if g.get("blockers"))
    score += min(40, blocked_radar * 8)
    if session_blocks:
        score += 25
    if not best and blocked_radar:
        score += 20
    if tqs < 40:
        score += 10
    return min(100.0, round(score, 1))


def _summary_text(
    gaps: list[dict[str, Any]],
    session_blocks: list[dict],
    best: Any,
    chop: dict,
    expiry: dict,
) -> str:
    parts: list[str] = []
    if session_blocks:
        parts.append(f"Session blocked: {session_blocks[0].get('reason')}")
    blocked = [g for g in gaps if g.get("blockers")]
    if blocked:
        top = blocked[0]
        parts.append(
            f"Radar shows {top.get('side')} {top.get('strike')} ({top.get('tier')}) "
            f"but blocked: {', '.join(top.get('blockers', []))}"
        )
    elif not best:
        parts.append("No candidate passes entry gates — low TQS or no explosion velocity")
    else:
        parts.append(f"Best candidate: {best.symbol} {best.mode} score={best.score:.0f}")
    if expiry.get("nearExpirySymbols") and not expiry.get("expirySession"):
        parts.append(f"Pre-expiry routing active for {expiry.get('nearExpirySymbols')}")
    if chop.get("badDayRouting", {}).get("badDaySession"):
        parts.append(f"Bad-day rank floor {chop.get('badDayRouting', {}).get('minRankFloor')}")
    return " · ".join(parts) if parts else "Monitoring aligned with entry gates"


def build_trade_close_report(
    trade: Any,
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> dict[str, Any]:
    """Post-trade report stored with each close."""
    state = state or get_state()
    ctx = trade.entryContext or {}
    sym = str(trade.symbol).upper()
    snap = snapshots.get(sym)
    side = trade.side.value if hasattr(trade.side, "value") else str(trade.side)

    dominant_put = dominant_ce = None
    if snap:
        from app.engines.rally_capture import dominant_explosion_alert

        dom = dominant_explosion_alert(snap)
        if dom:
            if str(dom.get("side", "")).upper() == "PUT":
                dominant_put = dom
            else:
                dominant_ce = dom

    counter_trend = False
    if snap and snap.spotChart:
        d = (snap.spotChart.direction or "NEUTRAL").upper()
        if d == "BULLISH" and side == "PUT":
            counter_trend = True
        if d == "BEARISH" and side == "CALL":
            counter_trend = True

    return {
        "tradeId": trade.id,
        "symbol": sym,
        "side": side,
        "strike": trade.strike,
        "pnlInr": trade.pnlInr,
        "exitReason": trade.exitReason,
        "strategyType": trade.strategyType.value if hasattr(trade.strategyType, "value") else str(trade.strategyType),
        "selectionMode": ctx.get("selectionMode"),
        "selectionScore": ctx.get("selectionScore"),
        "entryPremium": trade.entryPremium,
        "exitPremium": trade.currentPremium,
        "holdSeconds": _hold_seconds_from_trade(trade),
        "counterTrendVsChart": counter_trend,
        "chartDirection": snap.spotChart.direction if snap and snap.spotChart else None,
        "breadthBias": snap.breadth.bias if snap and snap.breadth else None,
        "dominantExplosionAtExit": dominant_put or dominant_ce,
        "missedOppositeRip": (
            dominant_put is not None and side == "CALL"
        ) or (dominant_ce is not None and side == "PUT"),
        "at": datetime.now(IST).isoformat(),
    }


def _hold_seconds_from_trade(trade: Any) -> float:
    try:
        opened = trade.openedAt
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        end = trade.closedAt or datetime.now(IST)
        if end.tzinfo is None:
            end = end.replace(tzinfo=IST)
        return (end.astimezone(IST) - opened.astimezone(IST)).total_seconds()
    except Exception:
        return 0.0


async def analyze_with_ai(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> dict[str, Any]:
    """Rules report + optional Composer narrative."""
    from app.engines.composer_market_monitor import build_market_context
    from app.services.cursor_composer_client import ComposerClientError, get_composer_client

    rules = analyze_snapshot_lag(snapshots, state)
    state = state or get_state()
    settings = get_settings()

    out: dict[str, Any] = {
        "rules": rules,
        "aiSummary": None,
        "aiError": None,
        "source": "rules_only",
    }

    if not settings.cursor_api_key:
        out["aiError"] = "CURSOR_API_KEY not configured"
        return out

    context = build_market_context(snapshots, state)
    context["lagAnalysis"] = rules

    prompt = f"""Analyze where NexusQuant is LAGGING between market monitoring and trade execution.
Focus on: explosion radar vs entry gates, misleading dashboard flags, missed PE/CE rips, TQS vs rank floors.

Context JSON:
{__import__('json').dumps(context, default=str)[:12000]}

Lag rules report:
{__import__('json').dumps(rules, default=str)[:8000]}

Respond JSON only:
{{
  "headline": "one line",
  "missedOpportunities": ["..."],
  "systemLags": ["where monitoring sees X but gates block Y"],
  "misleadingUI": ["..."],
  "priorityFixes": ["..."],
  "tradeBias": "CALL|PUT|BOTH|STAND_ASIDE"
}}"""

    try:
        client = get_composer_client()
        text = await client.chat_completion(
            [
                {"role": "system", "content": "You are a trading systems auditor. Respond with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        import json
        import re

        raw = text.strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            out["aiSummary"] = json.loads(m.group())
            out["source"] = "rules+composer"
        else:
            out["aiSummary"] = {"headline": raw[:500]}
            out["source"] = "rules+composer_text"
    except ComposerClientError as e:
        out["aiError"] = str(e)
    except Exception as e:
        out["aiError"] = str(e)

    return out
