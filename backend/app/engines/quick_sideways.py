"""Quick sideways scalps — fast in/out on RANGE_BOUND / chop sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.chop_day_guards import is_chop_session
from app.engines.premium_filter import premium_in_band, premium_reject_reason
from app.models.schemas import (
    HeatmapStrike,
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


def _in_chop(snap: SymbolSnapshot) -> bool:
    regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime)
    return regime in (Regime.RANGE_BOUND.value, Regime.CHOP.value) or is_chop_session(
        {snap.symbol: snap},
    )


def _min_velocity_pct(snap: SymbolSnapshot) -> float:
    settings = get_settings()
    if _in_chop(snap):
        return settings.quick_sideways_chop_min_velocity_pct
    return settings.quick_sideways_min_velocity_pct


def resolve_quick_sideways_stop_points(entry_premium: float) -> float:
    """Wider stop for expensive premiums — reduces noise stops on ₹100+ strikes."""
    settings = get_settings()
    if not settings.quick_sideways_stop_adaptive_enabled:
        return settings.quick_sideways_stop_points
    if entry_premium < 60:
        return settings.quick_sideways_stop_premium_lt_60
    if entry_premium < 90:
        return settings.quick_sideways_stop_premium_60_90
    if entry_premium < 130:
        return settings.quick_sideways_stop_premium_90_130
    return settings.quick_sideways_stop_premium_gt_130


def cap_quick_sideways_lots(lots: int, premium: float) -> int:
    settings = get_settings()
    if premium > settings.quick_sideways_high_premium_threshold_inr:
        return min(lots, settings.quick_sideways_high_premium_lot_cap)
    return lots


def snapshot_in_chop(snap: SymbolSnapshot) -> bool:
    return _in_chop(snap)


def get_quick_sideways_profile(entry_premium: float | None = None) -> OptimizedProfile:
    settings = get_settings()
    stop = (
        resolve_quick_sideways_stop_points(entry_premium)
        if entry_premium is not None
        else settings.quick_sideways_stop_points
    )
    return OptimizedProfile(
        targetPoints=settings.quick_sideways_target_points,
        stopPoints=stop,
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
    settings = get_settings()
    mom_thresh = (
        settings.quick_sideways_chop_pick_momentum_pct
        if _in_chop(snap)
        else 0.04
    )
    tick_thresh = 28 if _in_chop(snap) else 38
    delta_thresh = 25 if _in_chop(snap) else 35

    mom5 = chart.momentum5Pct or 0
    tick = snap.orderflow.tickMomentum or 0
    delta = snap.orderflow.deltaVelocity or 0

    if mom5 >= mom_thresh or tick >= tick_thresh or delta >= delta_thresh:
        return Side.CALL
    if mom5 <= -mom_thresh or tick <= -tick_thresh or delta <= -delta_thresh:
        return Side.PUT

    direction = (chart.direction or "NEUTRAL").upper()
    if direction == "BULLISH":
        return Side.CALL
    if direction == "BEARISH":
        return Side.PUT
    return None


def _strike_premium(row: HeatmapStrike, side: Side) -> tuple[float, Optional[float]]:
    if side == Side.CALL:
        return row.strike, row.callLtp
    return row.strike, row.putLtp


def _near_spot(strike: float, spot: float, radius: float) -> bool:
    return abs(strike - spot) <= radius


def _micro_velocity(snap: SymbolSnapshot, side: Side, strike: float) -> float:
    best = 0.0
    for entry in snap.explosiveRunnerWatchlist or []:
        if str(entry.get("side", "")).upper() != side.value:
            continue
        if abs(float(entry.get("strike") or 0) - strike) <= 150:
            best = max(best, abs(float(entry.get("premiumVelocityPct") or 0)))
    runner = snap.explosiveRunner
    if runner and runner.signal and runner.side == side:
        if abs((runner.strike or 0) - strike) <= 150:
            best = max(best, abs(float(runner.signal.premiumVelocityPct or 0)))
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side", "")).upper() != side.value:
            continue
        if abs(float(alert.get("strike") or 0) - strike) <= 150:
            best = max(
                best,
                abs(float(alert.get("velocity3s") or 0)),
                abs(float(alert.get("velocity9s") or 0)) * 0.5,
            )
    return max(best, abs(snap.orderflow.signedMomentumPct or 0))


def _collect_strike_candidates(
    snap: SymbolSnapshot,
    side: Side,
) -> list[tuple[float, float]]:
    """ATM + watchlist/heatmap strikes for slow sideways premium ticks."""
    settings = get_settings()
    spot = snap.spot or snap.atmStrike or 0.0
    radius = float(settings.quick_sideways_strike_scan_radius)
    out: dict[float, float] = {}

    for row in snap.heatmap:
        if not _near_spot(row.strike, spot, radius):
            continue
        strike, prem = _strike_premium(row, side)
        if prem and prem > 0:
            out[strike] = prem

    if settings.quick_sideways_scan_watchlist:
        for entry in snap.explosiveRunnerWatchlist or []:
            if str(entry.get("side", "")).upper() != side.value:
                continue
            strike = float(entry.get("strike") or 0)
            prem = float(entry.get("premium") or entry.get("ltp") or 0)
            if strike > 0 and prem > 0 and _near_spot(strike, spot, radius):
                out[strike] = prem

    return sorted(out.items(), key=lambda x: abs(x[0] - spot))


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
    floor = _min_velocity_pct(snap)
    if vel < floor:
        return False, f"velocity_below_{floor}"

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
    # Closer-to-spot liquid strikes in chop
    spot = snap.spot or snap.atmStrike or strike
    if abs(strike - spot) <= 100:
        score += 3
    settings = get_settings()
    if settings.quick_sideways_preferred_premium_min <= premium <= settings.quick_sideways_preferred_premium_max:
        score += 8
    elif premium > settings.quick_sideways_high_premium_penalty_start:
        score -= min(12.0, (premium - settings.quick_sideways_high_premium_penalty_start) * 0.15)
    return round(score, 2)


def scan_quick_sideways_setups(
    symbol: str,
    snap: SymbolSnapshot,
) -> list[dict]:
    """Build quick sideways entry setups — ATM + watchlist strikes for slow chop ticks."""
    if not quick_sideways_enabled() or not is_sideways_snapshot(snap):
        return []

    chart = snap.spotChart
    if not chart:
        return []

    side = _pick_side(chart, snap)
    if not side:
        return []

    setups: list[dict] = []
    for strike, premium in _collect_strike_candidates(snap, side):
        vel = _micro_velocity(snap, side, strike)
        ok, reason = check_quick_sideways_entry(
            snap, side, strike, premium, velocity_pct=vel,
        )
        if not ok:
            continue
        setups.append({
            "symbol": symbol,
            "side": side,
            "strike": strike,
            "premium": premium,
            "velocityPct": vel,
            "score": score_quick_sideways(snap, side, strike, premium, vel),
            "reason": reason,
        })

    setups.sort(key=lambda s: s["score"], reverse=True)
    return setups[:2]


def evaluate_quick_sideways_exit(
    trade: PaperTrade,
    current_premium: float,
    lot_multiplier: int,
) -> tuple[Optional[str], float]:
    """Tight quick scalp exits — adaptive stop by premium, 30s min hold, chop early lock."""
    settings = get_settings()
    profile = get_quick_sideways_profile(trade.entryPremium)
    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    hold = _hold_seconds(trade)
    best = max(trade.bestPnlPoints, pnl_pts)
    in_chop = bool((trade.entryContext or {}).get("inChop"))

    min_hold = settings.quick_sideways_min_stop_hold_seconds
    if hold >= min_hold and pnl_pts <= -profile.stopPoints:
        return "quick_sideways_stop", pnl_inr

    if pnl_pts >= profile.targetPoints:
        return "quick_sideways_target", pnl_inr

    if in_chop and settings.quick_sideways_chop_early_lock_points > 0:
        early = settings.quick_sideways_chop_early_lock_points
        if best >= early and pnl_pts > 0:
            giveback = best - pnl_pts
            if giveback >= settings.quick_sideways_chop_early_giveback_points:
                return "quick_sideways_chop_early_lock", pnl_inr

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
