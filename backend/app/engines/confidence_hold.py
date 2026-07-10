"""Hold high-confidence trades longer; block immediate re-entry after early exit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import OptimizedProfile, PaperTrade, Side

IST = ZoneInfo("Asia/Kolkata")

_last_high_conf_close: dict[str, dict[str, Any]] = {}
_session_date: Optional[str] = None


@dataclass
class ConfidenceExitTuning:
    micro_min_best_points: float
    min_hold_before_micro_seconds: int
    micro_giveback_points: float
    trail_keep_ratio: float
    max_hold_multiplier: float


def _roll_session() -> None:
    global _session_date, _last_high_conf_close
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _last_high_conf_close.clear()


def reset_confidence_hold_state() -> None:
    global _session_date
    _last_high_conf_close.clear()
    _session_date = None


def trade_entry_score(trade: PaperTrade) -> float:
    """Best available entry quality score stored on the trade."""
    ctx = trade.entryContext or {}
    for key in ("selectionScore", "confidence", "tqs", "explosionScore"):
        val = ctx.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def is_high_confidence_trade(trade: PaperTrade) -> bool:
    settings = get_settings()
    if not settings.high_confidence_hold_enabled:
        return False
    return trade_entry_score(trade) >= settings.high_confidence_min_score


def confidence_exit_tuning(trade: PaperTrade) -> Optional[ConfidenceExitTuning]:
    settings = get_settings()
    if not is_high_confidence_trade(trade):
        return None
    return ConfidenceExitTuning(
        micro_min_best_points=settings.high_confidence_micro_min_best_points,
        min_hold_before_micro_seconds=settings.high_confidence_min_hold_before_micro_seconds,
        micro_giveback_points=settings.high_confidence_micro_giveback_points,
        trail_keep_ratio=settings.high_confidence_trail_keep_ratio,
        max_hold_multiplier=settings.high_confidence_max_hold_multiplier,
    )


def chart_confidence_for_trade(trade: PaperTrade) -> float:
    """Best available chart confidence on the trade (live or entry)."""
    ctx = trade.entryContext or {}
    return max(
        float(ctx.get("chartConfidence") or 0),
        float(ctx.get("entryChartConfidence") or 0),
        float((ctx.get("exitPlan") or {}).get("chartConfidence") or 0),
    )


def target_points_for_trade(trade: PaperTrade) -> float:
    ctx = trade.entryContext or {}
    plan = ctx.get("exitPlan") or {}
    return float(plan.get("targetPoints") or plan.get("targetPoints2") or 12.0)


def is_confidence_runner_hold(trade: PaperTrade) -> bool:
    """
    High chart/score confidence + aligned — hold until chart TP, not scratch exits.
    """
    settings = get_settings()
    if not settings.chart_confidence_hold_enabled:
        return is_high_confidence_trade(trade)

    conf = chart_confidence_for_trade(trade)
    score = trade_entry_score(trade)
    if conf < settings.chart_confidence_hold_min_confidence and score < settings.high_confidence_min_score:
        return False

    from app.engines.bullish_hold import direction_aligned_with_breadth

    if direction_aligned_with_breadth(trade):
        return True
    if conf >= settings.all_day_min_chart_confidence + 16:
        return True
    return score >= settings.high_confidence_min_score + 8


def hold_until_target_active(
    trade: PaperTrade,
    best: float,
    *,
    target_points: Optional[float] = None,
) -> bool:
    """True while trade should keep running toward chart/adaptive TP."""
    if not is_confidence_runner_hold(trade):
        return False
    settings = get_settings()
    target = target_points if target_points is not None else target_points_for_trade(trade)
    floor = max(settings.runner_min_best_points, target * settings.chart_confidence_hold_min_target_pct)
    return best < floor


def confidence_hold_max_seconds(trade: PaperTrade) -> int:
    settings = get_settings()
    if not is_confidence_runner_hold(trade):
        return 0
    base = settings.chart_confidence_hold_max_seconds
    conf = chart_confidence_for_trade(trade)
    if conf >= 85:
        return int(base * 1.25)
    return base


def confidence_hold_stop_multiplier(trade: PaperTrade) -> float:
    settings = get_settings()
    if not is_confidence_runner_hold(trade):
        return 1.0
    return settings.chart_confidence_hold_stop_mult



def should_defer_no_progress_exit(trade: PaperTrade, best: float) -> bool:
    """Skip no-progress scratch while a high-confidence trade works toward chart TP."""
    if hold_until_target_active(trade, best):
        return True
    settings = get_settings()
    from app.engines.bullish_hold import direction_aligned_with_breadth

    if is_confidence_runner_hold(trade):
        return True
    if not settings.scalp_no_progress_skip_when_aligned:
        return False
    if direction_aligned_with_breadth(trade):
        return True
    ctx = trade.entryContext or {}
    if ctx.get("extremeAllInBypass"):
        return True
    edge = ctx.get("edgeScore") or {}
    if edge.get("letRunners"):
        return True
    return False


def scalp_no_progress_limit_seconds(trade: PaperTrade) -> int:
    """How long to wait before scalp no-progress exit — longer on aligned holds."""
    settings = get_settings()
    base = settings.scalp_no_progress_seconds
    aligned = settings.scalp_no_progress_aligned_seconds
    from app.engines.bullish_hold import direction_aligned_with_breadth

    if is_confidence_runner_hold(trade) or direction_aligned_with_breadth(trade):
        conf_max = confidence_hold_max_seconds(trade)
        return max(aligned, conf_max or aligned)
    if trade_entry_score(trade) >= 80:
        return int(base * 1.5)
    return base


def apply_confidence_hold_profile(
    trade: PaperTrade,
    profile: OptimizedProfile,
) -> OptimizedProfile:
    """Extend targets and hold time for high-confidence entries."""
    tuning = confidence_exit_tuning(trade)
    if not tuning:
        return profile
    mult = tuning.max_hold_multiplier
    return OptimizedProfile(
        targetPoints=round(profile.targetPoints * 1.12, 2),
        stopPoints=profile.stopPoints,
        microTargetPoints=round(max(profile.microTargetPoints, 3.5), 2),
        maxHoldSeconds=int(profile.maxHoldSeconds * mult),
        sessionLabel=f"{profile.sessionLabel}_high_conf",
    )


def _instrument_key(symbol: str, side: Side | str, strike: float) -> str:
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    return f"{symbol.upper()}:{side_val}:{int(strike)}"


_MICRO_EARLY_EXITS = frozenset({
    "simple_micro_profit_lock",
    "simple_trail_profit_lock",
    "explosion_micro_profit_lock",
    "explosion_trail_lock",
})


def record_high_confidence_close(
    symbol: str,
    side: Side | str,
    strike: float,
    entry_score: float,
    pnl_inr: float,
    exit_reason: str = "",
) -> None:
    """Remember high-confidence exits so we don't churn the same setup."""
    settings = get_settings()
    if not settings.high_confidence_hold_enabled:
        return
    if entry_score < settings.high_confidence_min_score:
        return
    if pnl_inr <= 0 and exit_reason not in _MICRO_EARLY_EXITS:
        return

    _roll_session()
    key = _instrument_key(symbol, side, strike)
    _last_high_conf_close[key] = {
        "score": round(entry_score, 2),
        "pnlInr": round(float(pnl_inr), 2),
        "exitReason": exit_reason or "",
        "at": datetime.now(IST),
    }


def high_confidence_reentry_blocked(
    symbol: str,
    side: Side | str,
    strike: float,
    candidate_score: float,
) -> tuple[bool, str]:
    """
    Block re-entry on the same strike when we just exited a high-confidence trade.
    Allow only if the new signal is materially stronger.
    """
    settings = get_settings()
    if not settings.high_confidence_hold_enabled:
        return False, "ok"

    _roll_session()
    key = _instrument_key(symbol, side, strike)
    last = _last_high_conf_close.get(key)
    if not last or not last.get("at"):
        return False, "ok"

    at = last["at"]
    if at.tzinfo is None:
        at = at.replace(tzinfo=IST)
    elapsed = (datetime.now(IST) - at.astimezone(IST)).total_seconds()
    cooldown = settings.high_confidence_reentry_cooldown_seconds
    if elapsed >= cooldown:
        return False, "ok"

    prev_score = float(last.get("score", 0))
    uplift = settings.high_confidence_reentry_score_uplift
    if candidate_score >= prev_score + uplift:
        return False, "ok"

    remain = int(cooldown - elapsed)
    return True, f"high_conf_reentry_{key}_{remain}s_prev_{prev_score:.0f}"


def high_confidence_close_summary() -> dict[str, Any]:
    settings = get_settings()
    _roll_session()
    return {
        "enabled": settings.high_confidence_hold_enabled,
        "minScore": settings.high_confidence_min_score,
        "recentCloses": len(_last_high_conf_close),
        "reentryCooldownSeconds": settings.high_confidence_reentry_cooldown_seconds,
    }
