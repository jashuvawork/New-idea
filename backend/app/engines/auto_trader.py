"""Auto trader — paper execution with simple profit mode."""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.daily_profit_strategy import DailyCalibration
from app.engines.dual_strategy import filter_dual_candidates
from app.engines.risk_engine import RiskEngine
from app.engines.simple_profit import (
    check_entry_gate,
    compute_lot_size,
    evaluate_exit,
    get_session_targets,
)
from app.models.schemas import (
    AutoTraderState,
    MultiSnapshot,
    PaperTrade,
    Side,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
    TradeMastermind,
)

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Singleton state
_auto_trader_state: Optional[AutoTraderState] = None
_risk_engine = RiskEngine()
_calibration = DailyCalibration()
_capital_inr: float = 500_000


def get_state() -> AutoTraderState:
    global _auto_trader_state
    if _auto_trader_state is None:
        settings = get_settings()
        _auto_trader_state = AutoTraderState(
            paperTrading=settings.paper_trading,
            liveTradingEnabled=settings.enable_live_trading,
            running=True,
            tradeMastermind=TradeMastermind(
                simpleProfitMode=settings.paper_simple_profit_mode,
                dualStrategyEnabled=settings.paper_dual_strategy_enabled,
                simpleMaxLots=settings.simple_max_lots,
                simpleTargetLots=settings.simple_target_lots,
                simpleMinLots=settings.simple_min_lots,
                simpleMicroTargetPoints=settings.enhanced_micro_target_points,
                enhancedMode=True,
                adaptiveTargets=settings.adaptive_target_enabled,
            ),
        )
    return _auto_trader_state


def stop_trading() -> None:
    get_state().running = False


def resume_trading() -> None:
    get_state().running = True


def reset_session() -> None:
    global _auto_trader_state
    _calibration.reset()
    settings = get_settings()
    _auto_trader_state = AutoTraderState(
        paperTrading=settings.paper_trading,
        liveTradingEnabled=settings.enable_live_trading,
        running=True,
        tradeMastermind=TradeMastermind(
            simpleProfitMode=settings.paper_simple_profit_mode,
            dualStrategyEnabled=settings.paper_dual_strategy_enabled,
            simpleMaxLots=settings.simple_max_lots,
            simpleTargetLots=settings.simple_target_lots,
            simpleMinLots=settings.simple_min_lots,
            simpleMicroTargetPoints=settings.enhanced_micro_target_points,
            enhancedMode=True,
            adaptiveTargets=settings.adaptive_target_enabled,
        ),
    )


def set_capital(amount: float) -> None:
    global _capital_inr
    _capital_inr = amount


def process(
    snapshots: dict[str, SymbolSnapshot],
) -> AutoTraderState:
    """Process open/update/close paper trades from snapshot candidates."""
    state = get_state()
    settings = get_settings()
    skipped: list[dict[str, Any]] = []

    state.calibrationBlocks = _calibration.get_blocks()
    lot_mult = 25 if settings.symbols[0] != "SENSEX" else 10

    # Update open trades with current premiums
    for trade in state.openPaperTrades:
        snap = snapshots.get(trade.symbol)
        if not snap or not snap.dataAvailable:
            continue

        current = _find_premium(snap, trade.strike, trade.side)
        if current is None:
            continue

        trade.currentPremium = current
        trade.pnlPoints = current - trade.entryPremium
        trade.pnlInr = trade.pnlPoints * trade.lots * lot_mult
        trade.bestPnlPoints = max(trade.bestPnlPoints, trade.pnlPoints)

        profile = snap.optimizedProfile or get_session_targets()
        exit_reason, pnl = evaluate_exit(trade, current, profile, lot_mult)
        if exit_reason:
            trade.status = "CLOSED"
            trade.exitReason = exit_reason
            trade.pnlInr = pnl
            trade.pnlPoints = pnl / (trade.lots * lot_mult) if trade.lots else 0
            state.closedPaperTrades.append(trade)
            _calibration.record_trade(trade)
            logger.info("Paper trade closed: %s reason=%s pnl=%.2f", trade.id, exit_reason, pnl)

    state.openPaperTrades = [t for t in state.openPaperTrades if t.status == "OPEN"]

    # Try new entries from suggestions
    if state.running and settings.paper_simple_profit_mode:
        for symbol, snap in snapshots.items():
            if not snap.dataAvailable:
                continue

            for suggestion in snap.suggestedTrades:
                if not suggestion.lastPremium or suggestion.lastPremium <= 0:
                    skipped.append({"symbol": symbol, "reason": "missing_premium", "trade": suggestion.id})
                    continue

                blocked = state.calibrationBlocks.get(suggestion.side.value, False)
                momentum = (snap.orderflow.volumeAcceleration or 0) > 60
                override = snap.explosiveRunner.candidate and (snap.explosiveRunner.score or 0) >= 80

                passed, reason = check_entry_gate(
                    suggestion,
                    snap.breadth,
                    snap.tradeQualityScore,
                    suggestion.runnerSignal.premiumVelocityPct if suggestion.runnerSignal else 0,
                    blocked,
                    momentum_surge=momentum,
                    alignment_override=override,
                )

                if not passed:
                    skipped.append({"symbol": symbol, "reason": reason, "trade": suggestion.id})
                    continue

                lots = compute_lot_size(suggestion.tqs)
                ok, risk_reason = _risk_engine.check_new_entry(
                    state, symbol, suggestion.side, lots, suggestion.lastPremium, lot_mult
                )
                if not ok:
                    skipped.append({"symbol": symbol, "reason": risk_reason, "trade": suggestion.id})
                    _risk_engine.record_rejection(risk_reason, {"symbol": symbol, "side": suggestion.side.value})
                    continue

                # Open paper trade
                paper = PaperTrade(
                    id=str(uuid.uuid4())[:8],
                    symbol=symbol,
                    side=suggestion.side,
                    strike=suggestion.strike,
                    entryPremium=suggestion.lastPremium,
                    currentPremium=suggestion.lastPremium,
                    lots=lots,
                    openedAt=datetime.now(IST),
                    strategyType=suggestion.strategyType,
                )
                state.openPaperTrades.append(paper)
                logger.info(
                    "Paper trade opened: %s %s %s @ %.2f lots=%d",
                    symbol, suggestion.side.value, suggestion.strike,
                    suggestion.lastPremium, lots,
                )
                break  # one entry per symbol per cycle

    state.skipped = skipped
    state.dailyReport = _calibration.build_report(state.closedPaperTrades)
    _risk_engine.update_daily_pnl(state.dailyReport.netPnlInr)

    return state


def _find_premium(snap: SymbolSnapshot, strike: float, side: Side) -> Optional[float]:
    for row in snap.heatmap:
        if abs(row.strike - strike) < 1:
            if side == Side.CALL:
                return row.callLtp
            return row.putLtp
    if snap.explosiveRunner.strike == strike:
        return snap.explosiveRunner.premium
    return None


def get_performance_analysis() -> dict[str, Any]:
    state = get_state()
    return _calibration.performance_analysis(state.closedPaperTrades)


def get_readiness(symbol: str, snapshots: dict[str, SymbolSnapshot]) -> dict[str, Any]:
    settings = get_settings()
    snap = snapshots.get(symbol)
    checks = {
        "upstoxConnected": snap.dataAvailable if snap else False,
        "marketLive": snap.marketPhase.value == "LIVE_MARKET" if snap else False,
        "tqsAboveThreshold": (snap.tradeQualityScore or 0) >= settings.enhanced_tqs_entry if snap else False,
        "liveTradingEnabled": settings.enable_live_trading,
        "paperTradingActive": settings.paper_trading,
        "riskEngineOk": not _risk_engine.safe_mode,
        "calibrationClear": not any(get_state().calibrationBlocks.values()),
    }
    checks["readyForLive"] = all([
        checks["upstoxConnected"],
        checks["marketLive"],
        checks["riskEngineOk"],
        checks["calibrationClear"],
        settings.enable_live_trading,
    ])
    return {"symbol": symbol, "checks": checks, "allPassed": checks["readyForLive"]}
