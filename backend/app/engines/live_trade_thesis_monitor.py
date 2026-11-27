"""Live open-trade thesis monitor — session leg + MTF vs trade side.

While a position is open, re-check whether the session playbook still supports
this side. Counter-leg trades that stay underwater or only scratch green with
opposing HTF charts get a timely scratch / few-point snatch instead of full SL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.session_intent_authority import (
    _side_counter_to_participation,
    authority_active,
    mtf_summary_for_side,
    resolve_session_intent,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _side_u(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _allowed_symbol(sym: str, settings: Any) -> bool:
    raw = str(
        getattr(settings, "session_intent_symbols_csv", "NIFTY,SENSEX") or "NIFTY,SENSEX"
    )
    return sym.upper() in {s.strip().upper() for s in raw.split(",") if s.strip()}


def assess_live_trade_thesis(
    trade: PaperTrade,
    snap: SymbolSnapshot | None,
    state: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """Return a stamped assessment (reasoning) for HUD / funnel — no side effects."""
    settings = settings or get_settings()
    sym = str(trade.symbol or "").upper()
    side_u = _side_u(trade.side)
    out: dict[str, Any] = {
        "symbol": sym,
        "side": side_u,
        "enabled": False,
        "thesisBroken": False,
        "counterParticipation": False,
    }
    if snap is None or not authority_active(settings):
        return out
    if not bool(getattr(settings, "live_trade_thesis_exit_enabled", True)):
        return out
    if not _allowed_symbol(sym, settings):
        return out

    state = state or AutoTraderState()
    intent = resolve_session_intent(sym, snap, state, settings=settings)
    out["sessionIntent"] = {
        "sessionLeg": intent.get("sessionLeg"),
        "confidence": intent.get("confidence"),
        "participationSide": intent.get("participationSide"),
    }
    out["enabled"] = bool(intent.get("enabled"))
    if not out["enabled"]:
        return out

    counter = _side_counter_to_participation(side_u, intent)
    out["counterParticipation"] = counter
    if not counter:
        return out

    if intent.get("confidence") != "HIGH":
        out["reason"] = "counter_allowed_confidence"
        return out

    mtf = mtf_summary_for_side(trade.side, snap, settings=settings)
    out["mtf"] = mtf
    min_htf = int(
        getattr(settings, "live_trade_thesis_min_htf_oppose", 1) or 1
    )
    htf_oppose = int(mtf.get("htfOpposeCount") or 0)
    tactical_oppose = bool(
        mtf.get("tacticalOpposes") or mtf.get("tactical5mOpposes")
    )
    out["htfOpposeCount"] = htf_oppose
    out["tacticalOpposes"] = tactical_oppose

    need_tactical = bool(
        getattr(settings, "live_trade_thesis_require_tactical_oppose", True)
    )
    if htf_oppose < min_htf:
        out["reason"] = "htf_not_opposing"
        return out
    if need_tactical and not tactical_oppose:
        out["reason"] = "tactical_not_opposing"
        return out

    out["thesisBroken"] = True
    out["reason"] = "session_counter_leg_mtf"
    return out


def _stamp_live_thesis(trade: PaperTrade, assessment: dict[str, Any]) -> None:
    if trade.entryContext is None:
        trade.entryContext = {}
    ctx = trade.entryContext
    ctx["liveThesisAssessment"] = assessment
    ctx["liveThesisBroken"] = bool(assessment.get("thesisBroken"))
    ctx["liveThesisRefreshedAt"] = datetime.now(IST).isoformat()


def _observed_worst_pnl(trade: PaperTrade, *, pnl_pts: float) -> float:
    ctx = trade.entryContext or {}
    try:
        worst = float(
            getattr(trade, "worstPnlPoints", 0)
            or ctx.get("worstPnlPoints")
            or 0
        )
    except (TypeError, ValueError):
        worst = 0.0
    return min(worst, float(pnl_pts))


def _premium_rolling_over(trade: PaperTrade, *, settings: Any, live_velocity_3s: float) -> bool:
    from app.engines.explosion_profit import _premium_rolling_over

    return _premium_rolling_over(
        trade, settings=settings, live_velocity_3s=live_velocity_3s,
    )


def _skip_for_runner_hold(
    trade: PaperTrade,
    *,
    best: float,
    settings: Any,
) -> bool:
    ctx = trade.entryContext or {}
    if ctx.get("maxProfitCapture") or ctx.get("vBaseFtvRunner"):
        if bool(getattr(settings, "live_trade_thesis_skip_max_profit", True)):
            return True
    min_runner = float(
        getattr(settings, "live_trade_thesis_runner_min_best_points", 18.0) or 18.0
    )
    if best + 1e-6 >= min_runner:
        return True
    from app.engines.explosion_profit import _should_skip_elite_runner_early_exits

    if _should_skip_elite_runner_early_exits(trade, settings=settings):
        must_take = (ctx.get("eliteAssessment") or {}).get("mustTake")
        if must_take and best + 1e-6 >= min_runner * 0.5:
            return True
    return False


def live_wrong_side_thesis_exit_reason(
    trade: PaperTrade,
    snap: SymbolSnapshot | None,
    state: Any,
    *,
    pnl_pts: float,
    best: float,
    hold_seconds: float,
    live_velocity_3s: float = 0.0,
    settings: Any = None,
) -> Optional[str]:
    """Exit a live counter-leg trade when session + MTF say the thesis failed."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_trade_thesis_exit_enabled", True)):
        return None
    if snap is None:
        return None

    assessment = assess_live_trade_thesis(trade, snap, state, settings=settings)
    _stamp_live_thesis(trade, assessment)
    if not assessment.get("thesisBroken"):
        return None

    min_hold = float(
        getattr(settings, "live_trade_thesis_min_hold_seconds", 120.0) or 120.0
    )
    if hold_seconds < min_hold:
        return None

    if _skip_for_runner_hold(trade, best=best, settings=settings):
        return None

    max_v3 = float(
        getattr(settings, "live_trade_thesis_max_velocity_3s", 0.35) or 0.35
    )
    if live_velocity_3s > max_v3:
        return None

    worst = _observed_worst_pnl(trade, pnl_pts=pnl_pts)
    underwater_min = float(
        getattr(settings, "live_trade_thesis_min_underwater_pts", 6.0) or 6.0
    )

    scratch_max = float(
        getattr(settings, "live_trade_thesis_scratch_max_pnl_pts", 2.5) or 2.5
    )
    snatch_lo = float(
        getattr(settings, "live_trade_thesis_snatch_min_pts", 0.35) or 0.35
    )
    snatch_hi = float(
        getattr(settings, "live_trade_thesis_snatch_max_pts", 9.0) or 9.0
    )

    # Deep red on wrong leg — scratch before adaptive SL
    if (
        pnl_pts <= scratch_max
        and worst <= -underwater_min
        and live_velocity_3s <= max_v3
    ):
        return "live_wrong_side_thesis_scratch"

    # Revisit entry / few points green, then fade (requires rollover)
    if (
        snatch_lo <= pnl_pts <= snatch_hi
        and worst <= -underwater_min
        and _premium_rolling_over(trade, settings=settings, live_velocity_3s=live_velocity_3s)
    ):
        return "live_wrong_side_thesis_snatch"

    # Underwater, never established meaningful green
    max_never_green = float(
        getattr(settings, "live_trade_thesis_never_green_max_best_pts", 1.5) or 1.5
    )
    deep_loss = float(
        getattr(settings, "live_trade_thesis_never_green_loss_pts", 10.0) or 10.0
    )
    if (
        best <= max_never_green
        and pnl_pts <= -deep_loss
        and worst <= -underwater_min
    ):
        return "live_wrong_side_thesis_never_green"

    return None