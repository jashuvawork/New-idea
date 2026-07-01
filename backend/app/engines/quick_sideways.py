"""Quick sideways scalps — fast in/out on RANGE_BOUND / chop sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.chop_day_guards import is_chop_session
from app.engines.premium_filter import premium_in_band, premium_reject_reason
from app.models.schemas import (
    OptimizedProfile,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def quick_sideways_enabled() -> bool:
    settings = get_settings()
    return settings.quick_sideways_enabled or settings.rapid_scalp_mode_enabled


def is_sideways_snapshot(snap: SymbolSnapshot) -> bool:
    """Range-bound or neutral chop — ideal for quick mean-reversion scalps."""
    if not snap.dataAvailable:
        return False
    regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime)
    if regime == Regime.RANGE_BOUND.value:
        return True
    if regime == Regime.CHOP.value:
        return True
    chart = snap.spotChart
    if chart and abs(chart.momentum5Pct or 0) < 0.35 and chart.trendStrength < 40:
        return True
    return (snap.breadth.bias or "NEUTRAL").upper() == "NEUTRAL"


def is_sideways_session(snapshots: dict[str, SymbolSnapshot]) -> bool:
    if not quick_sideways_enabled():
        return False
    live = [s for s in snapshots.values() if s.dataAvailable]
    if not live:
        return False
    sideways = sum(1 for s in live if is_sideways_snapshot(s))
    return sideways >= max(1, len(live) // 2) or is_chop_session(snapshots)


def get_quick_sideways_profile() -> OptimizedProfile:
    settings = get_settings()
    return OptimizedProfile(
        targetPoints=settings.quick_sideways_target_points,
        stopPoints=settings.quick_sideways_stop_points,
        microTargetPoints=settings.quick_sideways_micro_target_points,
        maxHoldSeconds=settings.quick_sideways_max_hold_seconds,
        sessionLabel="quick_sideways",
    )


def _hold_seconds(trade: PaperTrade) -> float:
    opened = trade.openedAt
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=IST)
    return (datetime.now(IST) - opened.astimezone(IST)).total_seconds()


def _pick_side(chart: SpotChart, snap: SymbolSnapshot) -> Optional[Side]:
    """Fade micro-moves in a range — follow short-term spot impulse."""
    mom5 = chart.momentum5Pct or 0
    tick = snap.orderflow.tickMomentum or 0
    delta = snap.orderflow.deltaVelocity or 0

    if mom5 >= 0.04 or tick >= 38 or delta >= 35:
        return Side.CALL
    if mom5 <= -0.04 or tick <= -38 or delta <= -35:
        return Side.PUT

    direction = (chart.direction or "NEUTRAL").upper()
    if direction == "BULLISH":
        return Side.CALL
    if direction == "BEARISH":
        return Side.PUT
    return None


def _atm_premium(snap: SymbolSnapshot, side: Side) -> tuple[Optional[float], Optional[float]]:
    atm = snap.atmStrike or snap.spot
    if not atm:
        return None, None
    for row in snap.heatmap:
        if abs(row.strike - atm) > 50:
            continue
        if side == Side.CALL:
            return row.strike, row.callLtp
        return row.strike, row.putLtp
    return None, None


def _micro_velocity(snap: SymbolSnapshot, side: Side, strike: float) -> float:
    for entry in snap.explosiveRunnerWatchlist or []:
        if str(entry.get("side", "")).upper() != side.value:
            continue
        if abs(float(entry.get("strike") or 0) - strike) <= 100:
            return abs(float(entry.get("premiumVelocityPct") or 0))
    runner = snap.explosiveRunner
    if runner and runner.signal and runner.side == side:
        return abs(float(runner.signal.premiumVelocityPct or 0))
    return abs(snap.orderflow.signedMomentumPct or 0)


def check_quick_sideways_entry(
    snap: SymbolSnapshot,
    side: Side,
    strike: float,
    premium: float,
    *,
    velocity_pct: float = 0.0,
) -> tuple[bool, str]:
    settings = get_settings()
    if not quick_sideways_enabled():
        return False, "quick_sideways_disabled"
    if not is_sideways_snapshot(snap):
        return False, "not_sideways"
    if not premium_in_band(premium):
        return False, premium_reject_reason(premium)
    if snap.tradeQualityScore < settings.quick_sideways_min_tqs:
        return False, f"tqs_below_{settings.quick_sideways_min_tqs}"

    chart = snap.spotChart
    mom5 = abs(chart.momentum5Pct or 0) if chart else 0
    vel = max(velocity_pct, _micro_velocity(snap, side, strike), mom5)
    if vel < settings.quick_sideways_min_velocity_pct:
        return False, f"velocity_below_{settings.quick_sideways_min_velocity_pct}"

    # Avoid chasing full explosions in sideways mode
    if vel > settings.enhanced_velocity_threshold * 1.8:
        return False, "velocity_too_hot_for_sideways"

    return True, "passed"


def score_quick_sideways(
    snap: SymbolSnapshot,
    side: Side,
    strike: float,
    premium: float,
    velocity_pct: float,
) -> float:
    chart = snap.spotChart
    mom5 = abs(chart.momentum5Pct or 0) if chart else 0
    vel = max(velocity_pct, _micro_velocity(snap, side, strike), mom5)
    tick = abs(snap.orderflow.tickMomentum or 0)
    score = 48.0
    score += min(12, vel * 8)
    score += min(8, tick * 0.15)
    score += snap.tradeQualityScore * 0.25
    if snap.symbol.upper() == "SENSEX":
        score += 4
    if chart and chart.direction in ("BULLISH", "BEARISH"):
        aligned = (
            (chart.direction == "BULLISH" and side == Side.CALL)
            or (chart.direction == "BEARISH" and side == Side.PUT)
        )
        if aligned:
            score += 6
    return round(score, 2)


def scan_quick_sideways_setups(
    symbol: str,
    snap: SymbolSnapshot,
) -> list[dict]:
    """Build quick sideways entry setups for one symbol."""
    if not quick_sideways_enabled() or not is_sideways_snapshot(snap):
        return []

    chart = snap.spotChart
    if not chart:
        return []

    side = _pick_side(chart, snap)
    if not side:
        return []

    strike, premium = _atm_premium(snap, side)
    if not strike or not premium or premium <= 0:
        return []

    vel = _micro_velocity(snap, side, strike)
    ok, reason = check_quick_sideways_entry(
        snap, side, strike, premium, velocity_pct=vel,
    )
    if not ok:
        return []

    return [{
        "symbol": symbol,
        "side": side,
        "strike": strike,
        "premium": premium,
        "velocityPct": vel,
        "score": score_quick_sideways(snap, side, strike, premium, vel),
        "reason": reason,
    }]


def evaluate_quick_sideways_exit(
    trade: PaperTrade,
    current_premium: float,
    lot_multiplier: int,
) -> tuple[Optional[str], float]:
    """Tight quick scalp exits — 2–3pt targets, 2pt stop, short hold."""
    settings = get_settings()
    profile = get_quick_sideways_profile()
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    hold = _hold_seconds(trade)
    best = max(trade.bestPnlPoints, pnl_pts)

    min_hold = max(15, settings.scalp_stop_min_hold_seconds // 2)
    if hold >= min_hold and pnl_pts <= -profile.stopPoints:
        return "quick_sideways_stop", pnl_inr

    if pnl_pts >= profile.targetPoints:
        return "quick_sideways_target", pnl_inr

    if best >= profile.microTargetPoints and pnl_pts >= profile.microTargetPoints * 0.85:
        if best - pnl_pts >= settings.quick_sideways_micro_giveback_points:
            return "quick_sideways_micro_lock", pnl_inr

    if hold >= profile.maxHoldSeconds:
        if pnl_pts > 0:
            return "quick_sideways_time_profit", pnl_inr
        return "quick_sideways_time_scratch", pnl_inr

    if hold >= settings.quick_sideways_no_progress_seconds and best <= 0.5:
        return "quick_sideways_no_progress", pnl_inr

    return None, pnl_inr
