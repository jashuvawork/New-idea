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
    microTargetPoints: float
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
        base_stop, base_target = 4.0, settings.explosion_target_standard
        trail_arm, trail_keep = 5.0, 0.65
        micro = 3.0
    else:
        base_stop = session_profile.stopPoints
        base_target = session_profile.targetPoints
        trail_arm = 3.0
        trail_keep = 0.55
        micro = session_profile.microTargetPoints

    stop = base_stop
    target = base_target

    # ML tuning
    if win_prob >= 0.72:
        target *= 1.2
        trail_arm *= 1.15
        reasoning.append(f"ML win prob {win_prob:.0%} — wider target")
    elif win_prob <= 0.42:
        stop *= 0.85
        target *= 0.85
        reasoning.append(f"ML win prob {win_prob:.0%} — tighter SL/TP")

    # Psychology tuning
    if psychology.exit_bias == "TIGHT_STOPS":
        stop *= 0.8
        target *= 0.9
        micro *= 0.9
        reasoning.append(f"Psychology {psychology.label} — tighter stops")
    elif psychology.exit_bias == "LET_RUNNERS":
        target *= 1.25
        trail_arm *= 1.2
        trail_keep = min(0.75, trail_keep + 0.05)
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
        if (snap.topExplosion or {}).get("tier") == "ELITE":
            target = settings.explosion_target_elite
            trail_arm = 8.0
            reasoning.append("ELITE explosion — 25pt target")

    return AdaptiveExitPlan(
        stopPoints=round(max(2.0, stop), 2),
        targetPoints=round(max(3.0, target), 2),
        trailArmPoints=round(max(1.5, trail_arm), 2),
        trailKeepRatio=round(trail_keep, 2),
        microTargetPoints=round(max(1.5, micro), 2),
        mlWinProb=round(win_prob, 3),
        psychologyLabel=psychology.label,
        exitBias=psychology.exit_bias,
        reasoning=reasoning,
    )


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
    from app.engines.simple_profit import evaluate_exit

    exit_reason, pnl = evaluate_exit(trade, current_premium, adapted, lot_multiplier)
    if exit_reason:
        return exit_reason, pnl

    # Extra adaptive trail using plan ratios
    pnl_pts = current_premium - trade.entryPremium
    best = max(trade.bestPnlPoints, pnl_pts)
    if best >= plan.trailArmPoints and pnl_pts < best * plan.trailKeepRatio:
        return "adaptive_trail_sl", pnl_pts * trade.lots * lot_multiplier

    return None, pnl_pts * trade.lots * lot_multiplier


def evaluate_adaptive_explosion_exit(
    trade: PaperTrade,
    current_premium: float,
    plan: AdaptiveExitPlan,
    tier: str,
    lot_multiplier: int,
) -> tuple[Optional[str], float]:
    from app.engines.explosion_profit import evaluate_explosion_exit

    exit_reason, pnl = evaluate_explosion_exit(trade, current_premium, tier, lot_multiplier)
    if exit_reason:
        return exit_reason, pnl

    pnl_pts = current_premium - trade.entryPremium
    best = max(trade.bestPnlPoints, pnl_pts)
    if pnl_pts >= plan.targetPoints:
        return "adaptive_tp", pnl_pts * trade.lots * lot_multiplier
    if best >= plan.trailArmPoints and pnl_pts < best * plan.trailKeepRatio:
        return "adaptive_trail_sl", pnl_pts * trade.lots * lot_multiplier
    if pnl_pts <= -plan.stopPoints:
        return "adaptive_sl", pnl_pts * trade.lots * lot_multiplier

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
