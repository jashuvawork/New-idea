"""Auto trader — paper execution with simple profit mode."""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.daily_profit_strategy import DailyCalibration
from app.engines.ai_learning import get_ai_learning
from app.engines.dual_strategy import filter_dual_candidates
from app.engines.risk_engine import RiskEngine
from app.engines.explosion_profit import (
    check_explosion_entry,
    compute_explosion_lots,
    evaluate_explosion_exit,
)
from app.engines.swing_profit import (
    check_swing_entry,
    compute_swing_lots,
    evaluate_swing_exit,
)
from app.engines.adaptive_exits import (
    AdaptiveExitPlan,
    compute_adaptive_exit_plan,
    evaluate_adaptive_explosion_exit,
    evaluate_adaptive_scalp_exit,
    evaluate_adaptive_swing_exit,
)
from app.engines.swing_engine import SwingSetup
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
from app.services import trade_store

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Singleton state
_auto_trader_state: Optional[AutoTraderState] = None
_risk_engine = RiskEngine()
_calibration = DailyCalibration()
_capital_inr: float = 500_000
_state_loaded: bool = False


def _ensure_state_loaded() -> None:
    """Restore open paper trades from persistent store after restart."""
    global _auto_trader_state, _state_loaded
    if _state_loaded:
        return
    _state_loaded = True
    saved = trade_store.load_open_trades()
    if saved and _auto_trader_state:
        for raw in saved:
            try:
                trade = PaperTrade(**raw)
                if trade.status == "OPEN":
                    _auto_trader_state.openPaperTrades.append(trade)
            except Exception as e:
                logger.warning("Failed to restore trade: %s", e)
        if saved:
            logger.info("Restored %d open paper trades from store", len(saved))


def _build_context(snap: Optional[SymbolSnapshot], extra: Optional[dict] = None) -> dict:
    ctx: dict = extra or {}
    if snap:
        ctx.update({
            "tqs": snap.tradeQualityScore,
            "regime": snap.regime.value if hasattr(snap.regime, "value") else snap.regime,
            "breadth": snap.breadth.bias,
            "spot": snap.spot,
            "session": snap.optimizedProfile.sessionLabel if snap.optimizedProfile else "",
        })
        if snap.psychology:
            ctx["psychology"] = snap.psychology.get("label")
    return ctx


def _attach_exit_plan(
    snap: SymbolSnapshot,
    strategy_type: StrategyType,
    side: str,
    confidence: float,
    news: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Build ML + psychology adaptive SL/TP plan for a new trade."""
    settings = get_settings()
    if not settings.adaptive_exits_enabled:
        return {}

    from app.engines.psychology_engine import PsychologyState, analyze_psychology

    ps_data = snap.psychology or {}
    if ps_data:
        psychology = PsychologyState(
            score=ps_data.get("score", 0),
            label=ps_data.get("label", "NEUTRAL"),
            exit_bias=ps_data.get("exitBias", "BALANCED"),
            news_bias=ps_data.get("newsBias", "NEUTRAL"),
            breadth_bias=ps_data.get("breadthBias", "NEUTRAL"),
        )
    else:
        psychology = analyze_psychology(snap, news)

    profile = snap.optimizedProfile or get_session_targets()
    plan = compute_adaptive_exit_plan(
        snap, strategy_type, psychology, profile, side=side, confidence=confidence, news=news,
    )
    return plan.to_dict()


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
                swingTradingEnabled=settings.swing_trading_enabled,
                simpleMaxLots=settings.simple_max_lots,
                simpleTargetLots=settings.simple_target_lots,
                simpleMinLots=settings.simple_min_lots,
                simpleMicroTargetPoints=settings.enhanced_micro_target_points,
                enhancedMode=True,
                adaptiveTargets=settings.adaptive_target_enabled,
            ),
        )
    _ensure_state_loaded()
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
            swingTradingEnabled=settings.swing_trading_enabled,
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
    news: Optional[list[dict[str, Any]]] = None,
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
        is_explosion = trade.strategyType == StrategyType.EXPLOSIVE
        is_swing = trade.strategyType == StrategyType.SWING

        plan_dict = (trade.entryContext or {}).get("exitPlan")
        use_adaptive = settings.adaptive_exits_enabled and plan_dict

        if is_swing and settings.swing_trading_enabled:
            if trade.entryContext is None:
                trade.entryContext = {}
            pct = ((current - trade.entryPremium) / trade.entryPremium * 100) if trade.entryPremium else 0
            trade.entryContext["bestPnlPct"] = max(trade.entryContext.get("bestPnlPct", 0), pct)
            if use_adaptive:
                exit_reason, pnl = evaluate_adaptive_swing_exit(
                    trade, current, AdaptiveExitPlan.from_dict(plan_dict), lot_mult,
                )
            else:
                exit_reason, pnl = evaluate_swing_exit(trade, current, lot_mult)
        elif is_explosion and settings.explosion_capture_mode:
            tier = "ELITE" if (trade.bestPnlPoints or 0) >= 10 else "EXPLODING"
            if use_adaptive:
                exit_reason, pnl = evaluate_adaptive_explosion_exit(
                    trade, current, AdaptiveExitPlan.from_dict(plan_dict), tier, lot_mult,
                )
            else:
                exit_reason, pnl = evaluate_explosion_exit(trade, current, tier, lot_mult)
        elif use_adaptive:
            exit_reason, pnl = evaluate_adaptive_scalp_exit(
                trade, current, AdaptiveExitPlan.from_dict(plan_dict), profile, lot_mult,
            )
        else:
            exit_reason, pnl = evaluate_exit(trade, current, profile, lot_mult)
        if exit_reason:
            trade.status = "CLOSED"
            trade.exitReason = exit_reason
            trade.pnlInr = pnl
            trade.pnlPoints = pnl / (trade.lots * lot_mult) if trade.lots else 0
            trade.closedAt = datetime.now(IST)
            trade.sessionDate = datetime.now(IST).strftime("%Y-%m-%d")
            ctx = _build_context(snap, {"exitReason": exit_reason})
            trade.entryContext = ctx
            state.closedPaperTrades.append(trade)
            _calibration.record_trade(trade)
            trade_store.record_trade_closed(trade, ctx)
            get_ai_learning().record_trade_close(trade)
            logger.info("Paper trade closed: %s reason=%s pnl=%.2f", trade.id, exit_reason, pnl)

    state.openPaperTrades = [t for t in state.openPaperTrades if t.status == "OPEN"]

    # Try new entries — explosion mode takes priority
    if state.running:
        for symbol, snap in snapshots.items():
            if not snap.dataAvailable:
                continue

            entered = False

            # EXPLOSION CAPTURE — primary mode for daily chart moments
            if settings.explosion_capture_mode and snap.explosionAlerts:
                for alert in snap.explosionAlerts:
                    if not alert.get("tradeable"):
                        continue

                    from app.engines.explosion_detector import ExplosionEvent
                    from app.models.schemas import Side as SideEnum

                    event = ExplosionEvent(
                        symbol=symbol,
                        side=SideEnum(alert["side"]),
                        strike=alert["strike"],
                        premium=alert["premium"],
                        velocity_3s=alert.get("velocity3s", 0),
                        velocity_9s=alert.get("velocity9s", 0),
                        velocity_15s=alert.get("velocity15s", 0),
                        volume_surge=alert.get("volumeSurge", 1),
                        explosion_score=alert.get("explosionScore", 0),
                        tier=alert.get("tier", "WATCH"),
                        reason=alert.get("reason", ""),
                    )

                    suggestion = SuggestedTrade(
                        id=alert.get("id", str(uuid.uuid4())[:8]),
                        symbol=symbol,
                        side=event.side,
                        strike=event.strike,
                        lastPremium=event.premium,
                        tqs=snap.tradeQualityScore,
                        strategyType=StrategyType.EXPLOSIVE,
                        confidence=event.explosion_score,
                    )

                    blocked = state.calibrationBlocks.get(event.side.value, False)
                    passed, reason = check_explosion_entry(event, suggestion, snap.breadth, blocked)
                    if not passed:
                        skipped.append({"symbol": symbol, "reason": reason, "strike": event.strike})
                        continue

                    lots = compute_explosion_lots(event, snap.tradeQualityScore)
                    ok, risk_reason = _risk_engine.check_new_entry(
                        state, symbol, event.side, lots, event.premium, lot_mult
                    )
                    if not ok:
                        skipped.append({"symbol": symbol, "reason": risk_reason, "strike": event.strike})
                        continue

                    paper = PaperTrade(
                        id=str(uuid.uuid4())[:8],
                        symbol=symbol,
                        side=event.side,
                        strike=event.strike,
                        entryPremium=event.premium,
                        currentPremium=event.premium,
                        lots=lots,
                        openedAt=datetime.now(IST),
                        strategyType=StrategyType.EXPLOSIVE,
                        sessionDate=datetime.now(IST).strftime("%Y-%m-%d"),
                    )
                    ctx = _build_context(snap, {
                        "explosionTier": event.tier,
                        "velocity3s": event.velocity_3s,
                        "explosionScore": event.explosion_score,
                        "exitPlan": _attach_exit_plan(
                            snap, StrategyType.EXPLOSIVE, event.side.value,
                            event.explosion_score, news,
                        ),
                    })
                    paper.entryContext = ctx
                    state.openPaperTrades.append(paper)
                    trade_store.record_trade_opened(paper, ctx)
                    logger.info(
                        "EXPLOSION trade opened: %s %s %s @ %.2f tier=%s vel=%.1f%%",
                        symbol, event.side.value, event.strike, event.premium,
                        event.tier, event.velocity_3s,
                    )
                    entered = True
                    break

            # Fallback: simple profit mode for non-explosion signals
            if not entered and settings.paper_simple_profit_mode:
                for suggestion in snap.suggestedTrades:
                    if suggestion.strategyType == StrategyType.EXPLOSIVE:
                        continue  # already handled above
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
                        sessionDate=datetime.now(IST).strftime("%Y-%m-%d"),
                    )
                    ctx = _build_context(snap, {
                        "tqs": suggestion.tqs,
                        "confidence": suggestion.confidence,
                        "exitPlan": _attach_exit_plan(
                            snap, suggestion.strategyType, suggestion.side.value,
                            suggestion.confidence, news,
                        ),
                    })
                    paper.entryContext = ctx
                    state.openPaperTrades.append(paper)
                    trade_store.record_trade_opened(paper, ctx)
                    logger.info(
                        "Paper trade opened: %s %s %s @ %.2f lots=%d",
                        symbol, suggestion.side.value, suggestion.strike,
                        suggestion.lastPremium, lots,
                    )
                    break

            # SWING — multi-day paper holds (separate from scalp lane)
            if settings.swing_trading_enabled and snap.swingAlerts:
                swing_open_keys = {
                    (t.symbol, t.side.value)
                    for t in state.openPaperTrades
                    if t.strategyType == StrategyType.SWING
                }
                for alert in snap.swingAlerts:
                    if not alert.get("tradeable"):
                        continue
                    setup = SwingSetup(
                        symbol=symbol,
                        side=Side(alert["side"]),
                        strike=alert["strike"],
                        premium=alert["premium"],
                        swingType=alert.get("swingType", "swing"),
                        confidence=alert.get("confidence", 0),
                        reason=alert.get("reason", ""),
                        metadata=alert.get("metadata", {}),
                    )
                    blocked = state.calibrationBlocks.get(setup.side.value, False)
                    passed, reason = check_swing_entry(setup, swing_open_keys, blocked)
                    if not passed:
                        skipped.append({"symbol": symbol, "reason": reason, "mode": "swing"})
                        continue

                    lots = compute_swing_lots(setup.confidence)
                    ok, risk_reason = _risk_engine.check_new_entry(
                        state, symbol, setup.side, lots, setup.premium, lot_mult,
                        strategy_type=StrategyType.SWING,
                    )
                    if not ok:
                        skipped.append({"symbol": symbol, "reason": risk_reason, "mode": "swing"})
                        continue

                    paper = PaperTrade(
                        id=str(uuid.uuid4())[:8],
                        symbol=symbol,
                        side=setup.side,
                        strike=setup.strike,
                        entryPremium=setup.premium,
                        currentPremium=setup.premium,
                        lots=lots,
                        openedAt=datetime.now(IST),
                        strategyType=StrategyType.SWING,
                        sessionDate=datetime.now(IST).strftime("%Y-%m-%d"),
                    )
                    ctx = _build_context(snap, {
                        "swingType": setup.swingType,
                        "confidence": setup.confidence,
                        "targetPct": alert.get("targetPct"),
                        "stopPct": alert.get("stopPct"),
                        "maxHoldDays": alert.get("maxHoldDays"),
                        "reason": setup.reason,
                        "exitPlan": _attach_exit_plan(
                            snap, StrategyType.SWING, setup.side.value,
                            setup.confidence, news,
                        ),
                    })
                    paper.entryContext = ctx
                    state.openPaperTrades.append(paper)
                    trade_store.record_trade_opened(paper, ctx)
                    swing_open_keys.add((symbol, setup.side.value))
                    logger.info(
                        "SWING trade opened: %s %s %s @ %.2f type=%s hold≤%dd",
                        symbol, setup.side.value, setup.strike, setup.premium,
                        setup.swingType, alert.get("maxHoldDays", 5),
                    )
                    break

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
