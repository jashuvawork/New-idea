"""EOD playbook engine — next-session prep generated after market close."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.engines.capital_allocator import compute_session_pnl
from app.engines.chop_day_guards import chop_guard_summary
from app.engines.expiry_day_guards import expiry_guard_summary, near_expiry_symbols
from app.engines.worst_day_guard import identify_worst_day
from app.models.schemas import AutoTraderState, SymbolSnapshot

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_last_playbook: Optional[dict[str, Any]] = None
_last_eod_target: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def next_trading_day(from_dt: Optional[datetime] = None) -> str:
    """Next NSE session date (skip weekends)."""
    d = (from_dt or datetime.now(IST)).date()
    candidate = d + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d")


def in_eod_playbook_window() -> bool:
    """15:20–23:59 IST — after regular session, before next open."""
    settings = get_settings()
    start = settings.eod_playbook_start_hour * 60 + settings.eod_playbook_start_minute
    return _minutes_now() >= start


def _dominant_side(snap: SymbolSnapshot) -> str:
    puts = calls = 0.0
    for alert in snap.explosionAlerts or []:
        side = str(alert.get("side") or "").upper()
        score = float(alert.get("explosionScore") or 0)
        if side == "PUT":
            puts += score
        elif side == "CALL":
            calls += score
    if puts > calls * 1.2:
        return "PUT"
    if calls > puts * 1.2:
        return "CALL"
    chart = snap.spotChart
    if chart and chart.direction in ("BULLISH", "BEARISH"):
        return "CALL" if chart.direction == "BULLISH" else "PUT"
    return "BOTH"


def _symbol_eod_context(sym: str, snap: SymbolSnapshot) -> dict[str, Any]:
    chart = snap.spotChart
    analysis = snap.chartAnalysis
    breadth = snap.breadth
    return {
        "symbol": sym,
        "spot": snap.spot,
        "optionExpiry": snap.optionExpiry,
        "regime": str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime),
        "tqs": snap.tradeQualityScore,
        "breadthBias": breadth.bias if breadth else "NEUTRAL",
        "chartDirection": chart.direction if chart else "NEUTRAL",
        "mtfConsensus": (analysis.consensus if analysis else None) or (chart.direction if chart else "NEUTRAL"),
        "momentum5Pct": chart.momentum5Pct if chart else 0,
        "momentum30Pct": chart.momentum30Pct if chart else 0,
        "pcr": snap.pcr,
        "maxPain": snap.maxPain,
        "dominantSide": _dominant_side(snap),
        "topExplosion": (
            {
                "side": snap.topExplosion.get("side"),
                "strike": snap.topExplosion.get("strike"),
                "score": snap.topExplosion.get("explosionScore"),
            }
            if snap.topExplosion
            else None
        ),
    }


def _build_scenarios(
    symbols_ctx: dict[str, dict[str, Any]],
    expiry: dict[str, Any],
    bias: str,
    worst: Any,
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    near = expiry.get("nearExpirySymbols") or []
    exp_today = expiry.get("expirySymbols") or []

    if near or exp_today:
        sym = (exp_today or near)[0]
        scenarios.append({
            "id": "expiry_gamma",
            "label": f"{sym} expiry / near-expiry gamma",
            "probability": "HIGH",
            "action": "Morning selective · 14:00 deep OTM rips · widen scan range",
        })

    if bias == "PUT":
        scenarios.append({
            "id": "bear_continuation",
            "label": "Bearish MTF continuation",
            "probability": "MEDIUM",
            "action": "Favor PUT explosions · premium-led bypass if chart lags",
        })
    elif bias == "CALL":
        scenarios.append({
            "id": "bull_continuation",
            "label": "Bullish MTF continuation",
            "probability": "MEDIUM",
            "action": "Favor CALL on momentum · avoid counter-trend PUTs early",
        })
    else:
        scenarios.append({
            "id": "chop_dual",
            "label": "Chop / two-sided session",
            "probability": "MEDIUM",
            "action": "All-day explosion window · don't force direction until 10:00",
        })

    scenarios.append({
        "id": "open_gap",
        "label": "Open gap fill or gap-and-go",
        "probability": "MEDIUM",
        "action": "Watch premarket panel 09:00–09:15 · open caution until 09:45",
    })

    scenarios.append({
        "id": "power_hour",
        "label": "14:00 power hour vertical rips",
        "probability": "HIGH" if near else "MEDIUM",
        "action": "Volume awakening on flat bases · SENSEX 1500pt scan",
    })

    if worst.is_worst:
        scenarios.append({
            "id": "worst_day",
            "label": "Worst-day / bad-day guards",
            "probability": "MEDIUM",
            "action": "Breakout-only or stand aside · rank floor elevated",
        })

    return scenarios[:6]


def _build_watchlist(symbols_ctx: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, ctx in symbols_ctx.items():
        side = ctx.get("dominantSide") or "BOTH"
        if side == "BOTH":
            side = "PUT" if ctx.get("mtfConsensus") == "BEARISH" else (
                "CALL" if ctx.get("mtfConsensus") == "BULLISH" else "BOTH"
            )
        reason_parts = []
        if ctx.get("mtfConsensus"):
            reason_parts.append(f"MTF {ctx['mtfConsensus']}")
        if ctx.get("optionExpiry"):
            reason_parts.append(f"exp {ctx['optionExpiry']}")
        top = ctx.get("topExplosion")
        strike_hint = f"near {top['strike']}" if top and top.get("strike") else "ATM ±2 strikes"
        out.append({
            "symbol": sym,
            "side": side,
            "strikes": strike_hint,
            "reason": " · ".join(reason_parts) or "session close momentum",
            "priority": float(top.get("score") or ctx.get("tqs") or 50),
        })
    out.sort(key=lambda w: w.get("priority", 0), reverse=True)
    return out


def _aggregate_bias(symbols_ctx: dict[str, dict[str, Any]]) -> tuple[str, str]:
    put_v = call_v = 0.0
    for ctx in symbols_ctx.values():
        mtf = str(ctx.get("mtfConsensus") or "NEUTRAL").upper()
        if mtf == "BEARISH":
            put_v += 2
        elif mtf == "BULLISH":
            call_v += 2
        dom = str(ctx.get("dominantSide") or "").upper()
        if dom == "PUT":
            put_v += 1.5
        elif dom == "CALL":
            call_v += 1.5
        bb = str(ctx.get("breadthBias") or "NEUTRAL").upper()
        if bb == "BEARISH":
            put_v += 1
        elif bb == "BULLISH":
            call_v += 1

    if put_v > call_v * 1.35:
        return "PUT", "HIGH" if put_v > call_v * 1.8 else "MEDIUM"
    if call_v > put_v * 1.35:
        return "CALL", "HIGH" if call_v > put_v * 1.8 else "MEDIUM"
    if max(put_v, call_v) < 1:
        return "STAND_ASIDE", "LOW"
    return "BOTH", "MEDIUM"


def _build_playbook_steps(
    bias: str,
    expiry: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> list[str]:
    steps: list[str] = [
        "09:00 — Check premarket gap + auction bias",
        "09:15–09:45 — Open caution; wait for direction",
        "09:20–11:45 — Morning premium capture window",
        "10:00+ — Primary entry window opens",
    ]
    near = expiry.get("nearExpirySymbols") or []
    if near:
        steps.append(f"Pre-expiry {', '.join(near)} — consider cross-index routing")
    if bias == "PUT":
        steps.append("Favor PUT explosions when velocity + volume align")
    elif bias == "CALL":
        steps.append("Favor CALL explosions; block late OTM chase")
    else:
        steps.append("Two-sided OK — let radar pick dominant side")
    steps.append("14:00–15:25 — Power hour: flat-then-vertical + volume awakening")
    steps.append("Review AI analysis reports if session misses repeats")
    return steps


def build_eod_playbook(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
    *,
    target_date: Optional[str] = None,
) -> dict[str, Any]:
    """Rules-based next-day playbook from session close context."""
    state = state or get_state()
    session_date = datetime.now(IST).strftime("%Y-%m-%d")
    target = target_date or next_trading_day()

    symbols_ctx: dict[str, dict[str, Any]] = {}
    for sym, snap in snapshots.items():
        if snap.dataAvailable:
            symbols_ctx[sym.upper()] = _symbol_eod_context(sym, snap)

    expiry = expiry_guard_summary(state, snapshots)
    chop = chop_guard_summary(state, snapshots)
    worst = identify_worst_day(state, snapshots)
    session_pnl = compute_session_pnl(state)

    bias, confidence = _aggregate_bias(symbols_ctx)
    scenarios = _build_scenarios(symbols_ctx, expiry, bias, worst)
    watchlist = _build_watchlist(symbols_ctx)
    playbook_steps = _build_playbook_steps(bias, expiry, scenarios)

    risk_flags: list[str] = []
    if expiry.get("nearExpirySymbols"):
        risk_flags.append(f"Near-expiry: {', '.join(expiry['nearExpirySymbols'])}")
    if expiry.get("expirySymbols"):
        risk_flags.append(f"Expiry session: {', '.join(expiry['expirySymbols'])}")
    if worst.is_worst:
        risk_flags.append(f"Worst-day forecast ({worst.score:.0f}): {', '.join(worst.reasons[:2])}")
    if chop.get("badDayRouting", {}).get("badDaySession"):
        risk_flags.append(f"Bad-day rank floor {chop['badDayRouting'].get('minRankFloor')}")
    if session_pnl < -5000:
        risk_flags.append(f"Session loss ₹{session_pnl:.0f} — tighter gates tomorrow")

    near_txt = ", ".join(expiry.get("nearExpirySymbols") or []) or "none"
    summary = (
        f"Target {target} · bias {bias} ({confidence}) · "
        f"near-expiry {near_txt} · session PnL ₹{session_pnl:.0f}"
    )

    return {
        "generatedAt": _now_iso(),
        "sessionDate": session_date,
        "targetDate": target,
        "summary": summary,
        "bias": bias,
        "confidence": confidence,
        "scenarios": scenarios,
        "watchlist": watchlist,
        "riskFlags": risk_flags,
        "symbols": symbols_ctx,
        "playbook": playbook_steps,
        "sessionPnlInr": round(session_pnl, 2),
        "expiryGuards": {
            "nearExpirySymbols": expiry.get("nearExpirySymbols"),
            "expirySymbols": expiry.get("expirySymbols"),
            "worstDay": expiry.get("worstDay"),
        },
        "source": "rules",
        "aiSummary": None,
        "aiError": None,
    }


async def enrich_eod_playbook_with_ai(playbook: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.eod_playbook_use_ai or not settings.cursor_api_key:
        playbook["aiError"] = "AI disabled or CURSOR_API_KEY not set"
        return playbook

    from app.services.cursor_composer_client import ComposerClientError, get_composer_client

    prompt = f"""You are preparing TOMORROW's Indian index options trading playbook (EOD brief).
Target session date: {playbook.get('targetDate')}
Today's close context:
{json.dumps({k: playbook.get(k) for k in ('summary', 'bias', 'symbols', 'riskFlags', 'scenarios', 'watchlist')}, default=str)[:10000]}

Respond JSON only:
{{
  "headline": "one line plan for tomorrow",
  "openPlan": "09:15-10:00 what to do",
  "afternoonPlan": "14:00+ what to watch",
  "priorityStrikes": ["symbol side strike hint"],
  "avoid": ["what not to do tomorrow"],
  "confidence": "HIGH|MEDIUM|LOW"
}}"""

    try:
        client = get_composer_client()
        text = await client.chat_completion(
            [
                {"role": "system", "content": "You are an Indian index options session planner. JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        import re

        m = re.search(r"\{[\s\S]*\}", text.strip())
        if m:
            playbook["aiSummary"] = json.loads(m.group())
            playbook["source"] = "rules+composer"
        else:
            playbook["aiSummary"] = {"headline": text[:400]}
            playbook["source"] = "rules+composer_text"
    except ComposerClientError as exc:
        playbook["aiError"] = str(exc)
    except Exception as exc:
        playbook["aiError"] = str(exc)
    return playbook


async def run_eod_playbook_cycle(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Build, optionally AI-enrich, and persist next-day playbook."""
    global _last_playbook, _last_eod_target

    from app.services import trade_store

    state = state or get_state()
    target = next_trading_day()

    if not force:
        existing = trade_store.get_eod_playbook(target)
        if existing:
            _last_playbook = existing
            _last_eod_target = target
            return existing

    playbook = build_eod_playbook(snapshots, state, target_date=target)
    if get_settings().eod_playbook_use_ai:
        playbook = await enrich_eod_playbook_with_ai(playbook)

    trade_store.save_eod_playbook(playbook)
    _last_playbook = playbook
    _last_eod_target = target
    logger.info("EOD playbook saved for %s (bias=%s)", target, playbook.get("bias"))
    return playbook


def get_latest_eod_playbook() -> Optional[dict[str, Any]]:
    return _last_playbook


def monitor_status() -> dict[str, Any]:
    settings = get_settings()
    target = next_trading_day()
    from app.services import trade_store

    stored = trade_store.get_eod_playbook(target)
    return {
        "enabled": settings.eod_playbook_enabled,
        "inEodWindow": in_eod_playbook_window(),
        "targetDate": target,
        "lastGeneratedAt": (stored or _last_playbook or {}).get("generatedAt"),
        "lastBias": (stored or _last_playbook or {}).get("bias"),
        "hasPlaybook": bool(stored or _last_playbook),
        "useAi": settings.eod_playbook_use_ai,
    }
