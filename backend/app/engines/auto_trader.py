"""Auto trader — paper execution with simple profit mode."""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.daily_profit_strategy import DailyCalibration
from app.engines.ai_learning import get_ai_learning
from app.engines.risk_engine import RiskEngine
from app.engines.explosion_profit import evaluate_explosion_exit, record_explosion_stop
from app.engines.swing_profit import evaluate_swing_exit
from app.engines.adaptive_exits import (
    AdaptiveExitPlan,
    compute_adaptive_exit_plan,
    evaluate_adaptive_explosion_exit,
    evaluate_adaptive_scalp_exit,
    evaluate_adaptive_swing_exit,
)
from app.engines.capital_allocator import (
    compute_lots,
    compute_session_pnl,
    get_capital_snapshot,
    get_lot_sizes_meta,
    lot_multiplier,
    refresh_capital_from_upstox,
    tune_exit_plan_for_position,
    update_daily_profit_gate,
)
from app.engines.symbol_cooldown import record_symbol_result, reset_symbol_cooldowns
from app.engines.trade_selector import EntryCandidate, diagnose_missed_entries, find_best_entry
from app.engines.paper_slippage import (
    apply_entry_fill,
    exit_premium_for_trade,
    finalize_closed_pnl_inr,
    mark_to_market,
    should_simulate_slippage,
)
from app.engines.simple_profit import (
    evaluate_exit,
    get_session_targets,
)
from app.models.schemas import (
    AutoTraderState,
    PaperTrade,
    Side,
    StrategyType,
    SymbolSnapshot,
    TradeMastermind,
)
from app.engines.session_timing import entries_allowed_now, entry_window_label
from app.services import trade_store
from app.services.order_executor import place_entry_order, place_exit_order
from app.services.paper_broker import simulate_entry_order, simulate_exit_order
from app.services.upstox import UpstoxClient, UpstoxError, get_market_phase

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Singleton state
_auto_trader_state: Optional[AutoTraderState] = None
_risk_engine = RiskEngine()
_calibration = DailyCalibration()
_capital_inr: float = 500_000


async def refresh_trading_capital(client) -> None:
    """Pull Upstox margin and sync risk engine exposure limits."""
    settings = get_settings()
    if settings.use_upstox_capital_for_sizing:
        snap = await refresh_capital_from_upstox(client)
    else:
        snap = get_capital_snapshot()
    global _capital_inr
    _capital_inr = snap.availableMarginInr
    from app.models.schemas import RiskProfile
    profile = _risk_engine.profile
    profile.maxExposureInr = snap.maxExposureInr
    profile.maxOpenTrades = settings.aggressive_max_open_scalps if settings.aggressive_lot_sizing else profile.maxOpenTrades
    _risk_engine.set_profile(profile)


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


def _execution_mode(settings) -> str:
    if settings.enable_live_trading and settings.auto_trading_enabled:
        return "LIVE"
    if settings.paper_live_parity_enabled:
        return "PAPER_LIVE_PARITY"
    return "PAPER"


def _uses_paper_live_parity(settings) -> bool:
    is_live = settings.enable_live_trading and settings.auto_trading_enabled
    return (
        settings.paper_live_parity_enabled
        and settings.paper_simulate_broker_orders
        and not is_live
    )


async def _open_from_candidate(
    candidate: EntryCandidate,
    state: AutoTraderState,
    client: Optional[UpstoxClient] = None,
    news: Optional[list[dict]] = None,
) -> tuple[bool, str]:
    """Open one trade from best-ranked setup — paper journal + optional live broker order."""
    settings = get_settings()
    symbol = candidate.symbol
    snap = candidate.snap
    profile = snap.optimizedProfile or get_session_targets()
    stop_pts = 8.0 if candidate.strategy_type == StrategyType.SWING else profile.stopPoints

    signal_premium = candidate.premium
    is_live = settings.enable_live_trading and settings.auto_trading_enabled
    use_parity = _uses_paper_live_parity(settings)
    tier = candidate.tier if candidate.mode == "explosion" else None

    # Entry fill: parity paper applies MARKET-entry slippage; legacy paper optional; live uses signal LTP
    if use_parity or (
        settings.paper_slippage_enabled and not is_live and not use_parity
    ):
        fill_premium, slip_meta = apply_entry_fill(
            signal_premium, candidate.strategy_type, tier=tier,
        )
    else:
        fill_premium = signal_premium
        slip_meta = {
            "enabled": False,
            "signalPremium": round(signal_premium, 2),
            "fillPremium": round(signal_premium, 2),
        }

    lots = compute_lots(
        symbol, fill_premium, stop_pts,
        tqs=candidate.tqs,
        strategy_type=candidate.strategy_type,
        confidence=candidate.confidence,
        tier=candidate.tier,
    )
    lot_mult = lot_multiplier(symbol)

    ok, risk_reason = _risk_engine.check_new_entry(
        state, symbol, candidate.side, lots, fill_premium, lot_mult,
        strategy_type=candidate.strategy_type,
    )
    if not ok:
        return False, risk_reason

    exit_plan = _attach_exit_plan(
        snap, candidate.strategy_type, candidate.side.value,
        candidate.confidence, news,
    )
    exit_plan = tune_exit_plan_for_position(exit_plan, lots, fill_premium, symbol)

    ctx_extra: dict[str, Any] = {
        "selectionScore": round(candidate.score, 2),
        "selectionMode": candidate.mode,
        "lots": lots,
        "tradeBudgetInr": exit_plan.get("tradeBudgetInr"),
        "exitPlan": exit_plan,
        "executionMode": _execution_mode(settings),
        "optionExpiry": snap.optionExpiry,
        "slippage": slip_meta,
        "signalPremium": signal_premium,
        "paperLiveParity": use_parity,
    }
    if candidate.mode == "explosion" and candidate.explosion_event:
        ev = candidate.explosion_event
        ctx_extra.update({
            "explosionTier": ev.tier,
            "velocity3s": ev.velocity_3s,
            "explosionScore": ev.explosion_score,
        })
    elif candidate.mode == "scalp" and candidate.suggestion:
        ctx_extra.update({
            "tqs": candidate.suggestion.tqs,
            "confidence": candidate.suggestion.confidence,
        })
    elif candidate.mode == "swing" and candidate.alert:
        ctx_extra.update({
            "swingType": candidate.alert.get("swingType"),
            "confidence": candidate.confidence,
            "targetPct": candidate.alert.get("targetPct"),
            "stopPct": candidate.alert.get("stopPct"),
            "maxHoldDays": candidate.alert.get("maxHoldDays"),
            "reason": candidate.swing_setup.reason if candidate.swing_setup else "",
        })

    if is_live or use_parity:
        if not client:
            return False, "broker client required for live / paper-live-parity"
        try:
            if is_live:
                order = await place_entry_order(
                    client, snap, candidate.strike, candidate.side, lots,
                )
                ctx_extra.update({
                    "instrumentKey": order["instrument_key"],
                    "brokerOrderId": order["order_id"],
                    "brokerQuantity": order["quantity"],
                    "lotSize": order.get("lot_size", lot_mult),
                    "brokerSimulated": False,
                })
                state.liveOrdersPlaced += 1
            else:
                order = await simulate_entry_order(
                    client,
                    snap,
                    candidate.strike,
                    candidate.side,
                    lots,
                    signal_premium,
                    candidate.strategy_type,
                    tier=tier,
                )
                fill_premium = order["fill_premium"]
                slip_meta = order.get("slippage", slip_meta)
                ctx_extra["slippage"] = slip_meta
                ctx_extra.update({
                    "instrumentKey": order["instrument_key"],
                    "brokerOrderId": order["order_id"],
                    "brokerQuantity": order["quantity"],
                    "lotSize": order.get("lot_size", lot_mult),
                    "brokerSimulated": True,
                    "orderType": order.get("order_type"),
                    "product": order.get("product"),
                })
        except UpstoxError as e:
            logger.error("Entry failed for %s (%s): %s", symbol, _execution_mode(settings), e)
            return False, f"entry failed: {e}"

    paper = PaperTrade(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        side=candidate.side,
        strike=candidate.strike,
        entryPremium=fill_premium,
        currentPremium=fill_premium,
        lots=lots,
        openedAt=datetime.now(IST),
        strategyType=candidate.strategy_type,
        sessionDate=datetime.now(IST).strftime("%Y-%m-%d"),
    )

    ctx = _build_context(snap, ctx_extra)
    paper.entryContext = ctx
    state.openPaperTrades.append(paper)
    trade_store.record_trade_opened(paper, ctx)
    get_ai_learning().record_trade_open(
        paper.id,
        [
            float(candidate.tqs or 0),
            float(candidate.confidence or 0),
            float(candidate.score or 0),
        ],
        candidate.strategy_type.value,
    )
    state.lastEntry = {
        "tradeId": paper.id,
        "symbol": symbol,
        "side": candidate.side.value,
        "strike": candidate.strike,
        "lots": lots,
        "mode": candidate.mode,
        "score": round(candidate.score, 2),
        "executionMode": ctx_extra["executionMode"],
        "brokerOrderId": ctx_extra.get("brokerOrderId"),
        "at": datetime.now(IST).isoformat(),
    }
    logger.info(
        "BEST %s trade [%s]: %s %s %s signal=%.2f fill=%.2f ×%d lots (score %.1f)",
        candidate.mode, ctx_extra["executionMode"], symbol, candidate.side.value,
        candidate.strike, signal_premium, fill_premium, lots, candidate.score,
    )
    return True, "opened"


def get_state() -> AutoTraderState:
    global _auto_trader_state
    if _auto_trader_state is None:
        settings = get_settings()
        _auto_trader_state = AutoTraderState(
            paperTrading=settings.paper_trading,
            liveTradingEnabled=settings.enable_live_trading,
            autoTradingEnabled=settings.auto_trading_enabled,
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


def reset_session_calibration() -> None:
    """Clear side blocks and per-symbol loss streaks without wiping trade history."""
    _calibration.reset()
    reset_symbol_cooldowns()


def reset_session() -> None:
    global _auto_trader_state
    closed_ids = trade_store.close_open_trades_on_reset()
    trade_store.record_session_reset(open_trade_ids=closed_ids)
    reset_session_calibration()
    settings = get_settings()
    _auto_trader_state = AutoTraderState(
        paperTrading=settings.paper_trading,
        liveTradingEnabled=settings.enable_live_trading,
        autoTradingEnabled=settings.auto_trading_enabled,
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


async def process(
    snapshots: dict[str, SymbolSnapshot],
    news: Optional[list[dict[str, Any]]] = None,
    client: Optional[UpstoxClient] = None,
) -> AutoTraderState:
    """Process open/update/close trades from snapshot candidates."""
    state = get_state()
    settings = get_settings()
    skipped: list[dict[str, Any]] = []

    state.calibrationBlocks = _calibration.get_blocks()
    state.autoTradingEnabled = settings.auto_trading_enabled
    state.liveTradingEnabled = settings.enable_live_trading
    state.paperTrading = settings.paper_trading

    # Update open trades with current premiums
    for trade in list(state.openPaperTrades):
        lot_mult = lot_multiplier(trade.symbol)
        snap = snapshots.get(trade.symbol)
        if not snap or not snap.dataAvailable:
            continue

        current = _find_premium(snap, trade.strike, trade.side)
        if current is None:
            continue

        trade.currentPremium = current
        eval_premium = exit_premium_for_trade(trade, current)
        if should_simulate_slippage(trade):
            mtm_pts, mtm_inr = mark_to_market(
                trade.entryPremium, eval_premium, trade.lots, lot_mult,
            )
            trade.pnlPoints = mtm_pts
            trade.pnlInr = mtm_inr
            trade.bestPnlPoints = max(trade.bestPnlPoints, mtm_pts)
        else:
            trade.pnlPoints = current - trade.entryPremium
            trade.pnlInr = trade.pnlPoints * trade.lots * lot_mult
            trade.bestPnlPoints = max(trade.bestPnlPoints, trade.pnlPoints)
            eval_premium = current

        profile = snap.optimizedProfile or get_session_targets()
        is_explosion = trade.strategyType == StrategyType.EXPLOSIVE
        is_swing = trade.strategyType == StrategyType.SWING

        plan_dict = (trade.entryContext or {}).get("exitPlan")
        use_adaptive = settings.adaptive_exits_enabled and plan_dict

        if is_swing and settings.swing_trading_enabled:
            if trade.entryContext is None:
                trade.entryContext = {}
            pct = ((eval_premium - trade.entryPremium) / trade.entryPremium * 100) if trade.entryPremium else 0
            trade.entryContext["bestPnlPct"] = max(trade.entryContext.get("bestPnlPct", 0), pct)
            if use_adaptive:
                exit_reason, pnl = evaluate_adaptive_swing_exit(
                    trade, eval_premium, AdaptiveExitPlan.from_dict(plan_dict), lot_mult,
                )
            else:
                exit_reason, pnl = evaluate_swing_exit(trade, eval_premium, lot_mult)
        elif is_explosion and settings.explosion_capture_mode:
            tier = "ELITE" if (trade.bestPnlPoints or 0) >= 10 else "EXPLODING"
            if use_adaptive:
                exit_reason, pnl = evaluate_adaptive_explosion_exit(
                    trade, eval_premium, AdaptiveExitPlan.from_dict(plan_dict), tier, lot_mult,
                )
            else:
                exit_reason, pnl = evaluate_explosion_exit(trade, eval_premium, tier, lot_mult)
        elif use_adaptive:
            exit_reason, pnl = evaluate_adaptive_scalp_exit(
                trade, eval_premium, AdaptiveExitPlan.from_dict(plan_dict), profile, lot_mult,
            )
        else:
            exit_reason, pnl = evaluate_exit(trade, eval_premium, profile, lot_mult)
        if exit_reason:
            broker_ctx = dict(trade.entryContext or {})
            is_live = settings.enable_live_trading and settings.auto_trading_enabled
            use_parity = _uses_paper_live_parity(settings)
            needs_broker_exit = (is_live or use_parity) and broker_ctx.get("instrumentKey")

            if needs_broker_exit and not broker_ctx.get("brokerExitOrderId"):
                try:
                    trade.exitReason = exit_reason
                    if is_live:
                        exit_result = await place_exit_order(client, trade)
                    else:
                        exit_result = await simulate_exit_order(client, trade, current)
                        sim_fill = exit_result.get("fill_premium", eval_premium)
                        gross_pts, gross_inr = mark_to_market(
                            trade.entryPremium, sim_fill, trade.lots, lot_mult,
                        )
                        pnl = finalize_closed_pnl_inr(gross_inr)
                        eval_premium = sim_fill
                    broker_ctx["brokerExitOrderId"] = exit_result.get("order_id")
                    broker_ctx["brokerExitSimulated"] = use_parity
                    trade.entryContext = broker_ctx
                    if is_live:
                        state.liveOrdersPlaced += 1
                except UpstoxError as e:
                    logger.error(
                        "Exit failed for %s (%s): %s — will retry",
                        trade.id, _execution_mode(settings), e,
                    )
                    skipped.append({
                        "symbol": trade.symbol,
                        "reason": "exit_pending",
                        "message": str(e),
                        "tradeId": trade.id,
                    })
                    continue
            elif should_simulate_slippage(trade):
                pnl = finalize_closed_pnl_inr(pnl)

            trade.status = "CLOSED"
            trade.exitReason = exit_reason
            trade.pnlInr = pnl
            trade.pnlPoints = pnl / (trade.lots * lot_mult) if trade.lots else 0
            trade.closedAt = datetime.now(IST)
            trade.sessionDate = datetime.now(IST).strftime("%Y-%m-%d")
            if trade.strategyType == StrategyType.EXPLOSIVE and exit_reason in (
                "explosion_stop_loss",
                "explosion_emergency_stop",
                "explosion_time_stop",
                "explosion_trail_sl",
                "adaptive_sl",
            ) and pnl < 0:
                cooldown = (
                    settings.explosion_emergency_cooldown_seconds
                    if exit_reason == "explosion_emergency_stop"
                    else None
                )
                record_explosion_stop(trade.symbol, cooldown_seconds=cooldown)
            ctx = _build_context(snap, {
                "exitReason": exit_reason,
                "instrumentKey": broker_ctx.get("instrumentKey"),
                "brokerOrderId": broker_ctx.get("brokerOrderId"),
                "brokerExitOrderId": broker_ctx.get("brokerExitOrderId"),
                "executionMode": broker_ctx.get("executionMode", _execution_mode(settings)),
            })
            trade.entryContext = ctx
            state.closedPaperTrades.append(trade)
            _calibration.record_trade(trade)
            record_symbol_result(trade.symbol, pnl, exit_reason or "")
            trade_store.record_trade_closed(trade, ctx)
            get_ai_learning().record_trade_close(trade)
            state.lastExit = {
                "tradeId": trade.id,
                "symbol": trade.symbol,
                "reason": exit_reason,
                "pnlInr": round(pnl, 2),
                "executionMode": ctx.get("executionMode"),
                "brokerExitOrderId": broker_ctx.get("brokerExitOrderId"),
                "at": datetime.now(IST).isoformat(),
            }
            logger.info("Trade closed: %s reason=%s pnl=%.2f", trade.id, exit_reason, pnl)

    state.openPaperTrades = [t for t in state.openPaperTrades if t.status == "OPEN"]

    market_live = get_market_phase() == "LIVE_MARKET"
    profit_gate = update_daily_profit_gate(state)
    cap_snap = get_capital_snapshot()
    state.capitalAllocation = {**cap_snap.to_dict(), **get_lot_sizes_meta()}
    state.dailyProfitGate = profit_gate.to_dict()

    if not profit_gate.newEntriesAllowed:
        skipped.append({
            "symbol": "SESSION",
            "reason": profit_gate.status,
            "message": profit_gate.message,
        })

    # Try new entries — best setup only, max lots on 85% sizing capital
    entries_ok, entry_window_reason = entries_allowed_now()
    if market_live and not entries_ok:
        skipped.append({
            "symbol": "SESSION",
            "reason": entry_window_reason,
            "message": f"Entries from {entry_window_label()} — skipping open auction minute",
        })

    if (
        state.running
        and settings.auto_trading_enabled
        and market_live
        and profit_gate.newEntriesAllowed
        and entries_ok
    ):
        best = find_best_entry(snapshots, state)
        if best:
            opened, reason = await _open_from_candidate(best, state, client, news)
            if not opened:
                skipped.append({
                    "symbol": best.symbol,
                    "reason": reason,
                    "mode": best.mode,
                    "score": best.score,
                })
        else:
            skipped.extend(diagnose_missed_entries(snapshots, state))

    state.skipped = skipped
    state.dailyReport = _calibration.build_report(state.closedPaperTrades)
    _risk_engine.update_daily_pnl(compute_session_pnl(state))

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
