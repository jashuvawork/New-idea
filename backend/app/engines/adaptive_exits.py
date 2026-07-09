"""Adaptive SL/TP/trailing — ML + psychology + session tuned exits."""

from dataclasses import dataclass, asdict
from typing import Any, Optional

from app.config import get_settings
from app.engines.psychology_engine import PsychologyState
from app.engines.ml_engine import get_ml_engine
from app.models.schemas import OptimizedProfile, PaperTrade, StrategyType, SymbolSnapshot


@dataclass
class AdaptiveExitPlan:
    stopPoints: float
    targetPoints: float
    trailArmPoints: float
    trailKeepRatio: float
    trailStepPoints: float = 2.5
    trailTightArm: float = 8.0
    trailTightPoints: float = 3.0
    microTargetPoints: float = 2.5
    stopPct: float = 0.0
    targetPct: float = 0.0
    mlWinProb: float = 0.5
    psychologyLabel: str = "NEUTRAL"
    exitBias: str = "BALANCED"
    reasoning: list[str] = None

    def __post_init__(self):
        if self.reasoning is None:
            self.reasoning = []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdaptiveExitPlan":
        return cls(
            stopPoints=data.get("stopPoints", 3.0),
            targetPoints=data.get("targetPoints", 6.0),
            trailArmPoints=data.get("trailArmPoints", 3.0),
            trailKeepRatio=data.get("trailKeepRatio", 0.55),
            microTargetPoints=data.get("microTargetPoints", 2.5),
            trailStepPoints=data.get("trailStepPoints", 2.5),
            trailTightArm=data.get("trailTightArm", 8.0),
            trailTightPoints=data.get("trailTightPoints", 3.0),
            stopPct=data.get("stopPct", 0.0),
            targetPct=data.get("targetPct", 0.0),
            mlWinProb=data.get("mlWinProb", 0.5),
            psychologyLabel=data.get("psychologyLabel", "NEUTRAL"),
            exitBias=data.get("exitBias", "BALANCED"),
            reasoning=data.get("reasoning", []),
        )


def compute_adaptive_exit_plan(
    snap: SymbolSnapshot,
    strategy_type: StrategyType,
    psychology: PsychologyState,
    session_profile: OptimizedProfile,
    side: str = "CALL",
    confidence: float = 70.0,
    news: Optional[list[dict[str, Any]]] = None,
    *,
    entry_premium: Optional[float] = None,
    entry_velocity_3s: Optional[float] = None,
    explosion_tier: Optional[str] = None,
) -> AdaptiveExitPlan:
    """Derive SL, TP, and trailing parameters from ML + psychology + session."""
    settings = get_settings()
    ml = get_ml_engine()
    reasoning: list[str] = []

    ctx = _build_ml_context(snap, psychology, session_profile, side, confidence)
    features = ml.extract_features(type("Sig", (), {"side": type("S", (), {"value": side})(), "confidence": confidence})(), ctx)
    win_prob = ml.predict_win_probability(features)

    if strategy_type == StrategyType.SWING:
        return _swing_plan(settings, psychology, win_prob, reasoning)

    if strategy_type == StrategyType.EXPLOSIVE:
        top = snap.topExplosion or {}
        tier = explosion_tier or str(top.get("tier") or "EXPLODING")
        vel = entry_velocity_3s
        if vel is None:
            vel = float(top.get("velocity3s") or 0)
            if not vel and snap.explosiveRunner and snap.explosiveRunner.signal:
                vel = float(snap.explosiveRunner.signal.premiumVelocityPct or 0)
        premium = entry_premium
        if premium is None:
            premium = float(top.get("premium") or 0)
            if not premium and snap.explosiveRunner:
                premium = float(snap.explosiveRunner.premium or 0)
        premium = max(premium, 25.0)

        # Per-trade SL from premium + momentum — not a global fixed point value
        base_stop = max(settings.scalp_stop_min_points, premium * 0.10)
        base_target = settings.explosion_target_standard
        trail_arm, trail_keep = settings.explosion_trail_arm_points, settings.explosion_trail_keep_ratio
        trail_step = settings.explosion_trail_step_points
        trail_tight_arm = settings.explosion_trail_tight_arm
        trail_tight_pts = settings.explosion_trail_tight_points
        micro = settings.explosion_micro_target_points

        if vel >= 2.5:
            base_stop *= 1.25
            reasoning.append(f"Explosion vel {vel:.1f}% — wider adaptive SL")
        if vel >= 4.0:
            base_stop *= 1.15
        if tier == "ELITE":
            base_stop *= 1.12
            base_target = settings.explosion_target_elite
            trail_arm = max(trail_arm, 8.0)
            reasoning.append("ELITE explosion — wider SL + 25pt target")
        daily_move = float(top.get("dailyMovePct") or top.get("openPremiumMove") or 0)
        if (
            settings.extreme_explosion_all_in_enabled
            and daily_move >= settings.extreme_explosion_elite_move_min_pct
        ):
            base_target = max(base_target, settings.explosion_target_elite * 1.6)
            trail_arm = max(trail_arm, settings.extreme_explosion_hold_min_best_points)
            trail_keep = min(0.82, trail_keep + 0.08)
            micro = max(micro, 5.0)
            reasoning.append(f"extreme_rip_{daily_move:.0f}pct_chart_hold")
    else:
        base_stop = session_profile.stopPoints
        base_target = session_profile.targetPoints
        trail_arm = settings.scalp_trail_arm_points
        trail_keep = settings.scalp_trail_keep_ratio
        trail_step = settings.scalp_trail_step_points
        trail_tight_arm = settings.scalp_trail_tight_arm
        trail_tight_pts = settings.scalp_trail_tight_points
        micro = session_profile.microTargetPoints

    stop = base_stop
    target = base_target

    # ML tuning
    if win_prob >= 0.72:
        target *= 1.2
        trail_arm *= 1.15
        if strategy_type == StrategyType.EXPLOSIVE:
            stop *= 1.1
        reasoning.append(f"ML win prob {win_prob:.0%} — wider target")
    elif win_prob <= 0.42:
        stop = max(settings.scalp_stop_min_points, stop * 0.9)
        target = max(base_target * 0.92, target * 0.92)
        reasoning.append(f"ML win prob {win_prob:.0%} — slightly tighter SL/TP")

    # Psychology tuning
    if psychology.exit_bias == "TIGHT_STOPS":
        stop = max(settings.scalp_stop_min_points, stop * 0.92)
        target = max(base_target * 0.95, target * 0.95)
        micro *= 0.95
        reasoning.append(f"Psychology {psychology.label} — modestly tighter stops")
    elif psychology.exit_bias == "LET_RUNNERS":
        target *= 1.25
        trail_arm *= 1.2
        trail_keep = min(0.75, trail_keep + 0.05)
        if strategy_type == StrategyType.EXPLOSIVE:
            stop *= 1.15
        reasoning.append(f"Psychology {psychology.label} — let runners run")
    elif psychology.exit_bias == "TIGHT_TRAIL":
        trail_arm *= 0.7
        trail_keep = max(0.5, trail_keep - 0.05)
        reasoning.append("Euphoria — early trail arm")

    # News event risk
    if news:
        bearish = sum(1 for n in news[:5] if n.get("sentiment") == "BEARISH")
        bullish = sum(1 for n in news[:5] if n.get("sentiment") == "BULLISH")
        if side == "CALL" and bearish >= 3:
            stop *= 0.85
            reasoning.append("Bearish news — tighten call stops")
        if side == "PUT" and bullish >= 3:
            stop *= 0.85
            reasoning.append("Bullish news — tighten put stops")

    # TQS boost
    tqs = snap.tradeQualityScore or 50
    if tqs >= 80:
        target *= 1.1
    elif tqs < 60:
        stop *= 0.9

    if strategy_type == StrategyType.EXPLOSIVE:
        if session_profile.sessionLabel in ("momentum_rally", "open_drive"):
            stop = max(settings.scalp_stop_min_points, stop * 1.12)
            trail_arm *= 1.1
            target = max(target, session_profile.targetPoints)
            reasoning.append(f"{session_profile.sessionLabel} — ride rally, wider adaptive SL")

    stop_floor = settings.scalp_stop_min_points
    stop_cap = 20.0 if strategy_type == StrategyType.EXPLOSIVE else 5.0
    target_floor = base_target * 0.95 if strategy_type != StrategyType.EXPLOSIVE else settings.explosion_target_standard * 0.85

    return AdaptiveExitPlan(
        stopPoints=round(min(stop_cap, max(stop_floor, stop)), 2),
        targetPoints=round(max(target_floor, target), 2),
        trailArmPoints=round(max(1.5, trail_arm), 2),
        trailKeepRatio=round(trail_keep, 2),
        trailStepPoints=round(max(1.0, trail_step), 2),
        trailTightArm=round(trail_tight_arm, 2),
        trailTightPoints=round(max(1.0, trail_tight_pts), 2),
        microTargetPoints=round(max(1.5, micro), 2),
        mlWinProb=round(win_prob, 3),
        psychologyLabel=psychology.label,
        exitBias=psychology.exit_bias,
        reasoning=reasoning,
    )


def apply_chart_exit_tuning(
    plan: AdaptiveExitPlan,
    snap: SymbolSnapshot,
    side: str,
    entry_premium: float,
) -> AdaptiveExitPlan:
    """Merge multi-chart SL/TP/trail levels into adaptive plan."""
    from app.engines.chart_exit_levels import merge_chart_into_exit_plan

    merged = merge_chart_into_exit_plan(plan.to_dict(), snap, side, entry_premium)
    return AdaptiveExitPlan.from_dict(merged)


def _swing_plan(settings, psychology: PsychologyState, win_prob: float, reasoning: list[str]) -> AdaptiveExitPlan:
    target_pct = settings.swing_target_pct
    stop_pct = settings.swing_stop_pct
    if psychology.exit_bias == "LET_RUNNERS":
        target_pct *= 1.15
        reasoning.append("Swing: greed — higher TP%")
    elif psychology.exit_bias == "TIGHT_STOPS":
        stop_pct *= 0.85
        target_pct *= 0.9
        reasoning.append("Swing: fear — tighter SL%")
    if win_prob >= 0.7:
        target_pct *= 1.1
    return AdaptiveExitPlan(
        stopPoints=0,
        targetPoints=0,
        trailArmPoints=0,
        trailKeepRatio=settings.swing_trail_keep,
        microTargetPoints=0,
        stopPct=round(stop_pct, 2),
        targetPct=round(target_pct, 2),
        mlWinProb=round(win_prob, 3),
        psychologyLabel=psychology.label,
        exitBias=psychology.exit_bias,
        reasoning=reasoning,
    )


def _build_ml_context(
    snap: SymbolSnapshot,
    psychology: PsychologyState,
    profile: OptimizedProfile,
    side: str,
    confidence: float,
) -> dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    now = datetime.now(IST)
    return {
        "tqs": snap.tradeQualityScore,
        "delta_velocity": snap.orderflow.deltaVelocity,
        "volume_accel": snap.orderflow.volumeAcceleration,
        "breakout_vel": snap.orderflow.breakoutVelocity,
        "tick_momentum": snap.orderflow.tickMomentum,
        "breadth_score": snap.breadth.score,
        "iv_expansion": snap.greeks.ivExpansion,
        "iv_rank": snap.greeks.ivRank,
        "pcr": snap.pcr or 1.0,
        "liquidity_score": max((h.liquidityScore for h in snap.heatmap), default=50),
        "velocity_pct": snap.explosiveRunner.signal.premiumVelocityPct if snap.explosiveRunner.signal else 0,
        "regime": snap.regime.value if hasattr(snap.regime, "value") else str(snap.regime),
        "session": profile.sessionLabel,
        "hour_ist": now.hour + now.minute / 60,
    }


def evaluate_adaptive_scalp_exit(
    trade: PaperTrade,
    current_premium: float,
    plan: AdaptiveExitPlan,
    profile: OptimizedProfile,
    lot_multiplier: int,
) -> tuple[Optional[str], float]:
    """Scalp exit using adaptive plan (wraps simple_profit rules with dynamic levels)."""
    from datetime import datetime
    from app.models.schemas import OptimizedProfile as OP

    adapted = OP(
        targetPoints=plan.targetPoints,
        stopPoints=plan.stopPoints,
        microTargetPoints=plan.microTargetPoints,
        maxHoldSeconds=profile.maxHoldSeconds,
        sessionLabel=profile.sessionLabel,
    )
    if plan.exitBias == "LET_RUNNERS" or plan.mlWinProb >= 0.72:
        adapted = OP(
            targetPoints=adapted.targetPoints,
            stopPoints=adapted.stopPoints,
            microTargetPoints=adapted.microTargetPoints,
            maxHoldSeconds=int(adapted.maxHoldSeconds * 1.25),
            sessionLabel=adapted.sessionLabel,
        )
    from app.engines.simple_profit import evaluate_exit

    exit_reason, pnl = evaluate_exit(
        trade,
        current_premium,
        adapted,
        lot_multiplier,
        trail_arm=plan.trailArmPoints,
        trail_keep=plan.trailKeepRatio,
        trail_step=plan.trailStepPoints,
        trail_tight_arm=plan.trailTightArm,
        trail_tight_pts=plan.trailTightPoints,
    )
    return exit_reason, pnl


def evaluate_adaptive_explosion_exit(
    trade: PaperTrade,
    current_premium: float,
    plan: AdaptiveExitPlan,
    tier: str,
    lot_multiplier: int,
    *,
    current_velocity_3s: float = 0.0,
) -> tuple[Optional[str], float]:
    """Explosion exits — per-trade adaptive SL/trail; no fixed global stop."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.engines.explosion_profit import (
        evaluate_explosion_exit,
        explosion_exit_params_from_plan,
    )

    IST = ZoneInfo("Asia/Kolkata")
    params = explosion_exit_params_from_plan(plan, tier)
    exit_reason, pnl = evaluate_explosion_exit(
        trade, current_premium, tier, lot_multiplier, params=params,
    )
    if exit_reason:
        return exit_reason, pnl

    pnl_pts = current_premium - trade.entryPremium
    best = max(trade.bestPnlPoints, pnl_pts)

    from app.engines.bullish_hold import direction_aligned_with_breadth
    from app.models.schemas import StrategyType

    min_arm = plan.trailArmPoints
    ctx = trade.entryContext or {}
    extreme_hold = bool(ctx.get("extremeAllInBypass"))
    if trade.strategyType == StrategyType.EXPLOSIVE:
        if direction_aligned_with_breadth(trade):
            min_arm = max(min_arm, 4.0)
        elif extreme_hold:
            min_arm = max(min_arm, float(get_settings().extreme_explosion_hold_min_best_points))

    if best >= min_arm and pnl_pts < best * plan.trailKeepRatio:
        return "adaptive_trail_sl", pnl_pts * trade.lots * lot_multiplier

    return None, pnl_pts * trade.lots * lot_multiplier


def evaluate_adaptive_swing_exit(
    trade: PaperTrade,
    current_premium: float,
    plan: AdaptiveExitPlan,
    lot_multiplier: int,
) -> tuple[Optional[str], float]:
    from app.engines.swing_profit import evaluate_swing_exit

    trade.entryContext = trade.entryContext or {}
    if plan.targetPct:
        trade.entryContext["targetPct"] = plan.targetPct
    if plan.stopPct:
        trade.entryContext["stopPct"] = plan.stopPct
    return evaluate_swing_exit(trade, current_premium, lot_multiplier)
