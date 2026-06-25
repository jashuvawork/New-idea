"""Strategy orchestrator — runs all Indian market strategies, ML-ranks signals."""

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.ml_engine import get_ml_engine
from app.engines.strategies.atm_acceleration import ATMPremiumAcceleration
from app.engines.strategies.base import StrategySignal, compute_pcr
from app.engines.strategies.closing_sprint import ClosingMomentumSprint
from app.engines.strategies.gamma_wall import GammaWallBreakout
from app.engines.strategies.iv_expansion import IVExpansionScalp
from app.engines.strategies.lunch_fade import LunchChopFade
from app.engines.strategies.max_pain import MaxPainMagnet
from app.engines.strategies.oi_shift import OIShiftMomentum
from app.engines.strategies.opening_drive import OpeningDriveScalp
from app.engines.strategies.pcr_reversal import PCRReversalScalp
from app.engines.strategies.premium_explosion import PremiumExplosion
from app.engines.strategies.vwap_bounce import VwapBounceScalp
from app.models.schemas import (
    Breadth,
    Greeks,
    MarketProfile,
    Orderflow,
    Regime,
    Side,
    StrategyType,
    SuggestedTrade,
)

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_premium_explosion = PremiumExplosion()

ALL_STRATEGIES = [
    _premium_explosion,  # #1 priority — daily chart moments
    OpeningDriveScalp(),
    VwapBounceScalp(),
    OIShiftMomentum(),
    PCRReversalScalp(),
    GammaWallBreakout(),
    MaxPainMagnet(),
    LunchChopFade(),
    ClosingMomentumSprint(),
    ATMPremiumAcceleration(),
    IVExpansionScalp(),
]


def _get_session() -> str:
    now = datetime.now(IST)
    t = now.hour * 60 + now.minute
    if 9 * 60 <= t < 9 * 60 + 15:
        return "premarket"
    if 9 * 60 + 15 <= t < 10 * 60:
        return "open_drive"
    if 11 * 60 + 30 <= t < 13 * 60:
        return "midday_chop"
    if 14 * 60 + 30 <= t < 15 * 60 + 15:
        return "closing_momentum"
    return "normal"


def run_all_strategies(
    symbol: str,
    spot: float,
    atm: float,
    chain: list[dict[str, Any]],
    orderflow: Orderflow,
    greeks: Greeks,
    breadth: Breadth,
    profile: MarketProfile,
    regime: Regime,
    heatmap: list,
    tqs: float,
    explosion_events: Optional[list] = None,
) -> tuple[list[StrategySignal], list[dict[str, Any]]]:
    """Evaluate all strategies, ML-rank, return top signals + strategy matrix."""
    session = _get_session()
    ml = get_ml_engine()
    pcr = compute_pcr(chain)

    # Inject explosion events into premium explosion strategy
    if explosion_events:
        _premium_explosion.set_events(explosion_events)

    context = {
        "tqs": tqs,
        "delta_velocity": orderflow.deltaVelocity,
        "volume_accel": orderflow.volumeAcceleration,
        "breakout_vel": orderflow.breakoutVelocity,
        "tick_momentum": orderflow.tickMomentum,
        "breadth_score": breadth.score,
        "iv_expansion": greeks.ivExpansion,
        "iv_rank": greeks.ivRank,
        "pcr": pcr,
        "liquidity_score": max((h.liquidityScore for h in heatmap), default=50),
        "velocity_pct": 0,
        "regime": regime.value,
        "session": session,
        "hour_ist": datetime.now(IST).hour + datetime.now(IST).minute / 60,
    }

    signals: list[StrategySignal] = []
    matrix: list[dict[str, Any]] = []

    for strategy in ALL_STRATEGIES:
        try:
            signal = strategy.evaluate(
                symbol, spot, atm, chain, orderflow, greeks, breadth,
                profile, regime, session, heatmap,
            )
            status = "active" if signal else "no_signal"
            ml_prob = 0.0
            conf = 0.0

            if signal:
                features = ml.extract_features(signal, context)
                ml_prob = ml.predict_win_probability(features)
                signal.ml_score = ml_prob
                combined = signal.confidence * 0.5 + ml_prob * 100 * 0.5
                # Explosion strategy gets priority boost
                if strategy.id == "premium_explosion":
                    combined = min(99, combined + 15)
                signal.confidence = min(99, combined)
                if combined >= 50:
                    signals.append(signal)
                conf = signal.confidence

            matrix.append({
                "id": strategy.id,
                "name": strategy.name,
                "status": status,
                "confidence": round(conf, 1),
                "mlProbability": round(ml_prob, 3),
                "preferredSession": strategy.preferred_sessions,
                "preferredRegime": [r.value for r in strategy.preferred_regimes],
                "sessionMatch": session in strategy.preferred_sessions,
            })
        except Exception as e:
            logger.warning("Strategy %s failed: %s", strategy.id, e)
            matrix.append({
                "id": strategy.id,
                "name": strategy.name,
                "status": "error",
                "error": str(e),
            })

    # Sort by combined confidence
    signals.sort(key=lambda s: s.confidence, reverse=True)
    matrix.sort(key=lambda m: m.get("confidence", 0), reverse=True)

    return signals[:5], matrix


def signals_to_suggested_trades(signals: list[StrategySignal], tqs: float) -> list[SuggestedTrade]:
    import uuid
    trades = []
    for sig in signals:
        trades.append(SuggestedTrade(
            id=str(uuid.uuid4())[:8],
            symbol=sig.symbol,
            side=sig.side,
            strike=sig.strike,
            lastPremium=sig.premium,
            tqs=tqs,
            strategyType=StrategyType.SCALP,
            confidence=sig.confidence,
            adaptiveTarget=sig.target_points,
            runnerSignal=None,
        ))
    return trades
