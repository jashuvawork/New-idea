"""Auto trader — paper execution with simple profit mode."""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.daily_18pct_strategy import (
    compute_trading_limits,
    scale_lots_for_limits,
    set_session_limits,
    get_session_limits,
)
from app.engines.daily_profit_strategy import DailyCalibration
from app.engines.capital_allocator import _capital_base_for_stages
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
from app.engines.chart_exit_levels import refresh_open_trade_chart_plan, update_live_chart_trail
from app.engines.capital_allocator import (
    compute_lots,
    compute_session_pnl,
    get_capital_snapshot,
    get_lot_sizes_meta,
    lot_multiplier,
    refresh_capital_from_upstox,
    reset_session_profit_gate,
    tune_exit_plan_for_position,
    update_daily_profit_gate,
)
from app.engines.symbol_cooldown import record_symbol_result, reset_symbol_cooldowns
from app.engines.instrument_cooldown import record_instrument_close, record_instrument_entry
from app.engines.chop_day_guards import (
    apply_tiered_lot_cap,
    chop_guard_summary,
    record_session_trade_close,
    reset_session_guards,
    session_pause_active,
    trades_cap_reached,
)
from app.engines.whipsaw_guards import (
    check_session_whipsaw_pause,
    record_trade_close as record_whipsaw_close,
)
from app.engines.edge_engine import (
    check_edge_realtime_exit,
    compute_entry_edge,
    scale_lots_by_edge,
    session_pf_feedback,
    tune_plan_with_edge,
)
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
from app.engines.quick_sideways import (
    cap_quick_sideways_lots,
    evaluate_quick_sideways_exit,
    get_quick_sideways_profile,
    snapshot_in_chop,
)
from app.engines.session_timing import entries_allowed_now, entry_window_label, explosion_entries_allowed_now
from app.engines.snapshot_fast import resolve_trade_premium
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
    """Restore open + today's closed paper trades from persistent store after restart."""
    global _auto_trader_state, _state_loaded
    if _state_loaded:
        return
    _state_loaded = True
    if not _auto_trader_state:
        return

    saved = trade_store.load_open_trades()
    if saved:
        for raw in saved:
            try:
                trade = PaperTrade(**raw)
                if trade.status == "OPEN":
                    _auto_trader_state.openPaperTrades.append(trade)
            except Exception as e:
                logger.warning("Failed to restore open trade: %s", e)
        if saved:
            logger.info("Restored %d open paper trades from store", len(_auto_trader_state.openPaperTrades))

    try:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        reset_at = trade_store.get_session_reset_at()
        day = trade_store.get_day_detail(today)
        restored_closed = 0
        seen_ids = {t.id for t in _auto_trader_state.closedPaperTrades}
        for row in day.get("trades", []):
            if row.get("status") != "CLOSED":
                continue
            exit_reason = str(row.get("exitReason") or "")
            if exit_reason in ("SESSION_RESET", "manual_reset"):
                continue
            tid = str(row.get("id", ""))
            if tid and tid in seen_ids:
                continue
            closed_raw = row.get("closedAt")
            if reset_at and closed_raw:
                try:
                    closed_at = datetime.fromisoformat(str(closed_raw))
                    if closed_at <= reset_at:
                        continue
                except ValueError:
                    pass
            try:
                side_raw = str(row.get("side", "CALL")).upper()
                _auto_trader_state.closedPaperTrades.append(PaperTrade(
                    id=tid or f"restored-{restored_closed}",
                    symbol=str(row.get("symbol", "")),
                    side=Side(side_raw),
                    strike=float(row.get("strike") or 0),
                    entryPremium=float(row.get("entryPremium") or 0),
                    currentPremium=float(row.get("currentPremium") or row.get("exitPremium") or row.get("entryPremium") or 0),
                    lots=int(row.get("lots") or 1),
                    exitPremium=float(row.get("exitPremium") or row.get("entryPremium") or 0),
                    pnlInr=float(row.get("pnlInr") or 0),
                    openedAt=datetime.fromisoformat(str(row.get("openedAt"))) if row.get("openedAt") else datetime.now(IST),
                    closedAt=datetime.fromisoformat(str(closed_raw)) if closed_raw else None,
                    status="CLOSED",
                    exitReason=exit_reason,
                    strategyType=StrategyType(str(row.get("strategyType") or "EXPLOSIVE")),
                    sessionDate=today,
                ))
                restored_closed += 1
            except Exception as e:
                logger.warning("Failed to restore closed trade %s: %s", tid, e)
        if restored_closed:
            logger.info("Restored %d closed paper trades for %s", restored_closed, today)
            _auto_trader_state.dailyReport = _calibration.build_report(_auto_trader_state.closedPaperTrades)
    except Exception as e:
        logger.warning("Failed to hydrate closed trades: %s", e)


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
    *,
    entry_premium: Optional[float] = None,
    entry_velocity_3s: Optional[float] = None,
    explosion_tier: Optional[str] = None,
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
        snap,
        strategy_type,
        psychology,
        profile,
        side=side,
        confidence=confidence,
        news=news,
        entry_premium=entry_premium,
        entry_velocity_3s=entry_velocity_3s,
        explosion_tier=explosion_tier,
    )
    from app.engines.adaptive_exits import apply_chart_exit_tuning

    tuned = apply_chart_exit_tuning(
        plan, snap, side, float(entry_premium or snap.spot or 50),
    )
    return tuned.to_dict()


def _trade_premium_velocity(snap: SymbolSnapshot, trade: PaperTrade) -> float:
    """Live premium velocity % for this leg — used to avoid adaptive SL during expansion."""
    side_v = trade.side.value
    strike = trade.strike
    for entry in snap.explosiveRunnerWatchlist or []:
        if str(entry.get("side", "")).upper() != side_v:
            continue
        if abs(float(entry.get("strike") or 0) - strike) > 0.5:
            continue
        return float(entry.get("premiumVelocityPct") or 0)
    runner = snap.explosiveRunner
    if runner and runner.side == trade.side and runner.signal:
        if abs(float(runner.strike or 0) - strike) <= 0.5:
            return float(runner.signal.premiumVelocityPct or 0)
    top = snap.topExplosion or {}
    if str(top.get("side", "")).upper() == side_v:
        if abs(float(top.get("strike") or 0) - strike) <= 50:
            return float(top.get("velocity3s") or 0)
    return 0.0


def _exit_plan_for_trade(
    trade: PaperTrade,
    snap: SymbolSnapshot,
    news: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Resolve or rebuild per-trade adaptive exit plan."""
    ctx = trade.entryContext or {}
    plan_dict = ctx.get("exitPlan")
    if plan_dict:
        return plan_dict
    if not get_settings().adaptive_exits_enabled:
        return {}
    confidence = float(
        ctx.get("explosionScore") or ctx.get("confidence") or ctx.get("selectionScore") or 70,
    )
    return _attach_exit_plan(
        snap,
        trade.strategyType,
        trade.side.value,
        confidence,
        news,
        entry_premium=trade.entryPremium,
        entry_velocity_3s=float(ctx.get("velocity3s") or 0) or None,
        explosion_tier=ctx.get("explosionTier"),
    )


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
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str]:
    """Open one trade from best-ranked setup — paper journal + optional live broker order."""
    settings = get_settings()
    symbol = candidate.symbol
    snap = candidate.snap

    from app.engines.worst_day_guard import worst_day_blocks_live

    if snapshots:
        live_blocked, live_reason, _ = worst_day_blocks_live(state, snapshots)
        if live_blocked and settings.enable_live_trading:
            return False, live_reason

        from app.engines.worst_day_guard import worst_day_allows_candidate
        from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass

        if not is_extreme_explosion_all_in_bypass(candidate=candidate):
            wd_ok, wd_reason, _ = worst_day_allows_candidate(candidate, state, snapshots)
            if not wd_ok:
                return False, wd_reason

    if snapshots and settings.controlled_trading_enabled:
        from app.engines.pretrade_validator import validate_candidate

        vt_ok, vt_reason, _ = validate_candidate(candidate, state, snapshots=snapshots)
        if not vt_ok:
            return False, vt_reason

    profile = snap.optimizedProfile or get_session_targets()
    if candidate.mode in ("quick_sideways", "slow_bounce"):
        profile = get_quick_sideways_profile(candidate.premium)
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
    if candidate.mode == "explosion":
        from app.engines.explosion_profit import cap_explosion_lots

        lots = cap_explosion_lots(lots, fill_premium)
    elif candidate.mode in ("quick_sideways", "slow_bounce"):
        lots = cap_quick_sideways_lots(lots, fill_premium)
    from app.engines.bad_day_routing import bad_day_lot_cap

    snap_map = snapshots or {symbol: snap}
    lots = bad_day_lot_cap(fill_premium, lots, state, snap_map)
    from app.engines.explosion_profit import expiry_session_lot_cap

    lots = expiry_session_lot_cap(lots, fill_premium, snap.tradeQualityScore, snap_map)
    lots = apply_tiered_lot_cap(
        lots, candidate.score, snap.breadth.aligned, symbol,
        velocity_pct=(
            (candidate.explosion_event.velocity_3s if candidate.explosion_event else 0)
            or (candidate.suggestion.runnerSignal.premiumVelocityPct
                if candidate.suggestion and candidate.suggestion.runnerSignal else 0)
        ),
        volume_surge=(candidate.explosion_event.volume_surge if candidate.explosion_event else 1.0),
    )
    limits = get_session_limits()
    if limits is not None:
        lots = scale_lots_for_limits(lots, limits)
    if lots <= 0:
        return False, "tiered_lot_cap_zero"

    entry_velocity_3s = 0.0
    if candidate.explosion_event:
        entry_velocity_3s = float(candidate.explosion_event.velocity_3s or 0)
    elif candidate.suggestion and candidate.suggestion.runnerSignal:
        entry_velocity_3s = float(candidate.suggestion.runnerSignal.premiumVelocityPct or 0)

    edge = compute_entry_edge(candidate, snap, state)
    lots = scale_lots_by_edge(lots, edge)
    if lots <= 0:
        return False, "edge_lot_scale_zero"
    lot_mult = lot_multiplier(symbol)

    ok, risk_reason = _risk_engine.check_new_entry(
        state, symbol, candidate.side, lots, fill_premium, lot_mult,
        strategy_type=candidate.strategy_type,
    )
    if not ok:
        return False, risk_reason

    from app.engines.snapshot_fast import _heatmap_instrument_key

    instrument_key = _heatmap_instrument_key(snap, candidate.strike, candidate.side)

    from app.engines.pretrade_validator import candidate_trade_score

    trade_score = candidate_trade_score(candidate)

    if settings.execution_chart_gate_enabled:
        if client:
            from app.engines.execution_chart_monitor import monitor_trade_chart_before_execution

            chart_ok, chart_reason, chart_meta = await monitor_trade_chart_before_execution(
                client,
                symbol,
                candidate.side,
                candidate.strike,
                snap,
                trade_score=trade_score,
                instrument_key=instrument_key,
                mode=candidate.mode or "",
                explosion_event=candidate.explosion_event,
            )
            if not chart_ok:
                return False, chart_reason
        else:
            from app.engines.expiry_day_guards import expiry_pm_itm_chart_bypass_allowed
            from app.engines.aligned_explosion_bypass import expiry_chart_bypass_for_candidate
            from app.engines.morning_premium_capture import premium_led_bypass_for_snap
            from app.engines.spot_direction import chart_blocks_side, side_aligned_with_chart

            breadth_bypass = expiry_pm_itm_chart_bypass_allowed(
                candidate.side, snap, mode=candidate.mode or "",
            )
            premium_bypass = premium_led_bypass_for_snap(
                candidate.side, snap, explosion_event=candidate.explosion_event,
            )
            expiry_chart_bypass = expiry_chart_bypass_for_candidate(candidate, snap)
            blocked, chart_reason = chart_blocks_side(
                candidate.side, snap.spotChart, trade_score=trade_score,
                breadth_aligned_bypass=breadth_bypass,
                premium_led_bypass=premium_bypass,
                expiry_explosion_bypass=expiry_chart_bypass,
            )
            if blocked:
                return False, f"exec_{chart_reason}"
            chart_meta = {
                "enabled": True,
                "source": "snapshot_only",
                "indexChart": snap.spotChart.model_dump() if snap.spotChart else {},
                "snapshotChart": snap.spotChart.model_dump() if snap.spotChart else {},
                "snapshotAligned": side_aligned_with_chart(candidate.side, snap.spotChart),
                "alignedWithChart": side_aligned_with_chart(candidate.side, snap.spotChart),
                "chartBypassUsed": bool(
                    premium_bypass or expiry_chart_bypass or breadth_bypass
                ),
                "premiumLedBypass": premium_bypass,
                "expiryExplosionBypass": expiry_chart_bypass,
            }
    else:
        chart_meta = {"enabled": False}

    exit_plan = _attach_exit_plan(
        snap, candidate.strategy_type, candidate.side.value,
        candidate.confidence, news,
        entry_premium=fill_premium,
        entry_velocity_3s=entry_velocity_3s or None,
        explosion_tier=(
            candidate.explosion_event.tier if candidate.explosion_event else None
        ),
    )
    exit_plan = tune_exit_plan_for_position(exit_plan, lots, fill_premium, symbol)
    if exit_plan and settings.edge_engine_enabled:
        plan_obj = AdaptiveExitPlan.from_dict(exit_plan)
        plan_obj = tune_plan_with_edge(
            plan_obj, edge, snap.spotChart, entry_velocity_3s,
        )
        exit_plan = plan_obj.to_dict()

    entry_chart_conf = float(exit_plan.get("chartConfidence") or 0)
    if entry_chart_conf <= 0:
        from app.engines.chart_exit_levels import chart_trade_confidence
        entry_chart_conf, _ = chart_trade_confidence(snap, candidate.side)

    ctx_extra: dict[str, Any] = {
        "selectionScore": round(candidate.score, 2),
        "selectionMode": candidate.mode,
        "lots": lots,
        "edgeScore": edge.to_dict(),
        "tradeBudgetInr": exit_plan.get("tradeBudgetInr"),
        "exitPlan": exit_plan,
        "entryChartConfidence": round(entry_chart_conf, 1),
        "chartConfidence": round(entry_chart_conf, 1),
        "executionMode": _execution_mode(settings),
        "optionExpiry": snap.optionExpiry,
        "slippage": slip_meta,
        "signalPremium": signal_premium,
        "paperLiveParity": use_parity,
        "executionChart": chart_meta,
    }
    from app.engines.moneyness import classify_moneyness

    if snap.spot and snap.spot > 0:
        ctx_extra["moneyness"] = classify_moneyness(
            candidate.side,
            candidate.strike,
            float(snap.spot),
            symbol=symbol,
            atm=float(snap.atmStrike) if snap.atmStrike else None,
        )
        ctx_extra["atmStrike"] = snap.atmStrike
    if snap.psychology:
        ctx_extra["psychology"] = snap.psychology.get("label", "NEUTRAL")
        ctx_extra["psychologyLabel"] = snap.psychology.get("label", "NEUTRAL")
        ctx_extra["psychologyExitBias"] = snap.psychology.get("exitBias", "BALANCED")
    if getattr(candidate, "pretrade_meta", None):
        ctx_extra["pretrade"] = candidate.pretrade_meta
    if entry_velocity_3s > 0:
        ctx_extra["velocity3s"] = entry_velocity_3s
        ctx_extra["entryVelocity3s"] = entry_velocity_3s
    if candidate.mode == "explosion" and candidate.explosion_event:
        ev = candidate.explosion_event
        from app.engines.extreme_explosion_moment import (
            extreme_all_in_meta,
            is_extreme_explosion_all_in_bypass,
        )
        from app.engines.morning_premium_capture import is_afternoon_capture_event

        afternoon = is_afternoon_capture_event(ev, chart=snap.spotChart)
        ctx_extra.update({
            "explosionTier": ev.tier,
            "explosionScore": ev.explosion_score,
            "afternoonCapture": afternoon,
            "dailyMovePct": float(ev.daily_move_pct or 0),
        })
        if is_extreme_explosion_all_in_bypass(candidate=candidate):
            ctx_extra.update(extreme_all_in_meta(candidate=candidate))
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
    elif candidate.mode in ("quick_sideways", "slow_bounce"):
        regime = snap.regime
        ctx_extra["inChop"] = snapshot_in_chop(snap)
        ctx_extra["regime"] = regime.value if hasattr(regime, "value") else str(regime)
        if candidate.mode == "slow_bounce":
            ctx_extra.update(candidate.pretrade_meta or {})

    if not ctx_extra.get("instrumentKey"):
        if instrument_key:
            ctx_extra["instrumentKey"] = instrument_key
        else:
            ik = _heatmap_instrument_key(snap, candidate.strike, candidate.side)
            if ik:
                ctx_extra["instrumentKey"] = ik

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
    record_instrument_entry(symbol, candidate.side, candidate.strike)
    from app.engines.directional_lock import record_trade_side

    record_trade_side(symbol, candidate.side, snap)
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
        "chartDirection": (
            (chart_meta.get("snapshotChart") or {}).get("direction")
            or chart_meta.get("indexChart", {}).get("direction")
        ),
        "execChartDirection": chart_meta.get("indexChart", {}).get("direction"),
        "chartAligned": (
            chart_meta.get("snapshotAligned")
            if chart_meta.get("snapshotAligned") is not None
            else chart_meta.get("alignedWithChart")
        ),
        "chartBypass": (
            "expiry explosion"
            if chart_meta.get("expiryExplosionBypass")
            else "premium-led"
            if chart_meta.get("premiumLedBypass")
            else "breadth-aligned"
            if chart_meta.get("chartBypassUsed")
            else None
        ),
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
    reset_session_guards()
    reset_session_profit_gate()


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


async def _process_open_trades(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    client: Optional[UpstoxClient],
) -> list[dict[str, Any]]:
    """Evaluate exits on open trades — safe for tick-fast path."""
    settings = get_settings()
    skipped: list[dict[str, Any]] = []

    for trade in list(state.openPaperTrades):
        lot_mult = lot_multiplier(trade.symbol)
        snap = snapshots.get(trade.symbol)
        if not snap or not snap.dataAvailable:
            continue

        broker_ctx = dict(trade.entryContext or {})
        current = resolve_trade_premium(
            snap, trade.strike, trade.side, broker_ctx.get("instrumentKey"),
        )
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
        use_adaptive = settings.adaptive_exits_enabled and (
            plan_dict or trade.strategyType == StrategyType.EXPLOSIVE
        )

        live_vel = _trade_premium_velocity(snap, trade)
        refresh_open_trade_chart_plan(trade, snap)
        update_live_chart_trail(trade, snap)
        plan_dict = (trade.entryContext or {}).get("exitPlan") or plan_dict
        if settings.edge_engine_enabled:
            edge_exit, edge_pnl = check_edge_realtime_exit(
                trade, eval_premium, snap,
                current_velocity_3s=live_vel,
                lot_multiplier=lot_mult,
            )
            if edge_exit:
                exit_reason, pnl = edge_exit, edge_pnl
            else:
                exit_reason, pnl = None, 0.0
        else:
            exit_reason, pnl = None, 0.0

        if not exit_reason and is_swing and settings.swing_trading_enabled:
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
        elif not exit_reason and is_explosion and settings.explosion_capture_mode:
            tier = (trade.entryContext or {}).get("explosionTier") or (
                "ELITE" if (trade.bestPnlPoints or 0) >= 10 else "EXPLODING"
            )
            if use_adaptive:
                plan_dict = _exit_plan_for_trade(trade, snap, news=None)
                exit_reason, pnl = evaluate_adaptive_explosion_exit(
                    trade,
                    eval_premium,
                    AdaptiveExitPlan.from_dict(plan_dict),
                    tier,
                    lot_mult,
                    current_velocity_3s=live_vel,
                )
            else:
                from app.engines.morning_premium_capture import afternoon_capture_exit_params

                exit_params = None
                if (trade.entryContext or {}).get("afternoonCapture"):
                    exit_params = afternoon_capture_exit_params(tier)
                exit_reason, pnl = evaluate_explosion_exit(
                    trade, eval_premium, tier, lot_mult, params=exit_params,
                )
        elif not exit_reason and (trade.entryContext or {}).get("selectionMode") in (
            "quick_sideways", "slow_bounce",
        ):
            from app.engines.chart_exit_levels import should_promote_quick_to_trailing

            best_pts = max(trade.bestPnlPoints, eval_premium - trade.entryPremium)
            if should_promote_quick_to_trailing(
                trade, snap, best_pts=best_pts, live_velocity=live_vel,
            ) and plan_dict:
                exit_reason, pnl = evaluate_adaptive_scalp_exit(
                    trade,
                    eval_premium,
                    AdaptiveExitPlan.from_dict(plan_dict),
                    profile,
                    lot_mult,
                )
            else:
                exit_reason, pnl = evaluate_quick_sideways_exit(
                    trade, eval_premium, lot_mult, snap=snap,
                )
        elif not exit_reason and use_adaptive:
            exit_reason, pnl = evaluate_adaptive_scalp_exit(
                trade, eval_premium, AdaptiveExitPlan.from_dict(plan_dict), profile, lot_mult,
            )
        elif not exit_reason:
            exit_reason, pnl = evaluate_exit(trade, eval_premium, profile, lot_mult)

        if not exit_reason:
            continue

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
            "adaptive_stop_loss",
            "adaptive_trail_sl",
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
        record_instrument_close(trade.symbol, trade.side, trade.strike, pnl, exit_reason or "")
        record_session_trade_close(pnl)
        record_whipsaw_close(trade.symbol, trade.side, pnl, exit_reason or "")
        from app.engines.confidence_hold import record_high_confidence_close, trade_entry_score

        record_high_confidence_close(
            trade.symbol,
            trade.side,
            trade.strike,
            trade_entry_score(trade),
            pnl,
            exit_reason or "",
        )
        trade_store.record_trade_closed(trade, ctx)
        from app.engines.snapshot_lag_analyzer import build_trade_close_report
        from app.services import trade_store as ts

        report = build_trade_close_report(trade, snapshots, state)
        report["sessionDate"] = trade.sessionDate or datetime.now(IST).strftime("%Y-%m-%d")
        ts.record_trade_report(report)
        get_ai_learning().record_trade_close(trade)
        state.lastExit = {
            "tradeId": trade.id,
            "symbol": trade.symbol,
            "side": trade.side.value if hasattr(trade.side, "value") else str(trade.side),
            "reason": exit_reason,
            "pnlInr": round(pnl, 2),
            "executionMode": ctx.get("executionMode"),
            "brokerExitOrderId": broker_ctx.get("brokerExitOrderId"),
            "at": datetime.now(IST).isoformat(),
        }
        logger.info("Trade closed: %s reason=%s pnl=%.2f", trade.id, exit_reason, pnl)

    state.openPaperTrades = [t for t in state.openPaperTrades if t.status == "OPEN"]
    return skipped


async def process_exits_only(
    snapshots: dict[str, SymbolSnapshot],
    client: Optional[UpstoxClient] = None,
) -> AutoTraderState:
    """Tick-fast path — WS LTP overlay + exit evaluation only."""
    state = get_state()
    settings = get_settings()
    state.calibrationBlocks = _calibration.get_blocks()
    state.autoTradingEnabled = settings.auto_trading_enabled
    state.liveTradingEnabled = settings.enable_live_trading
    state.paperTrading = settings.paper_trading

    exit_skipped = await _process_open_trades(state, snapshots, client)
    profit_gate = update_daily_profit_gate(state)
    cap_snap = get_capital_snapshot()
    state.capitalAllocation = {**cap_snap.to_dict(), **get_lot_sizes_meta()}
    state.dailyProfitGate = profit_gate.to_dict()
    state.chopGuards = chop_guard_summary(state, snapshots)
    state.skipped = exit_skipped
    state.dailyReport = _calibration.build_report(state.closedPaperTrades)
    _risk_engine.update_daily_pnl(compute_session_pnl(state))
    return state


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

    skipped.extend(await _process_open_trades(state, snapshots, client))

    market_live = get_market_phase() == "LIVE_MARKET"
    profit_gate = update_daily_profit_gate(state)
    cap_snap = get_capital_snapshot()
    state.capitalAllocation = {**cap_snap.to_dict(), **get_lot_sizes_meta()}
    state.dailyProfitGate = profit_gate.to_dict()

    from app.engines.pretrade_validator import collect_session_trades
    session_pnl = compute_session_pnl(state)
    trading_limits = compute_trading_limits(
        snapshots,
        state,
        session_pnl=session_pnl,
        capital_base=_capital_base_for_stages(),
        trades_today=len(collect_session_trades(state)),
    )
    edge_fb = session_pf_feedback(state)
    from app.engines.day_adaptive_engine import build_day_adaptive_profile

    day_adaptive = build_day_adaptive_profile(
        trading_limits.dayMode,
        trading_limits.confidenceTier,
        snapshots,
        phase=trading_limits.phase,
        state=state,
    )
    state.dailyStrategy = {
        **trading_limits.to_dict(),
        "edgeSession": {
            "profitFactor": round(edge_fb.profit_factor, 2),
            "winRate": round(edge_fb.win_rate, 1),
            "tradeCount": edge_fb.trade_count,
            "lotScale": round(edge_fb.lot_scale, 2),
            "rankPenalty": round(edge_fb.rank_penalty, 1),
            "tightenExits": edge_fb.tighten_exits,
            "pauseQuickScalps": edge_fb.pause_quick_scalps,
            "message": edge_fb.message,
            "pfTarget": settings.edge_session_pf_target,
        },
        "dayAdaptive": day_adaptive.to_dict(),
    }
    set_session_limits(trading_limits)

    state.chopGuards = chop_guard_summary(state, snapshots)

    if not profit_gate.newEntriesAllowed:
        skipped.append({
            "symbol": "SESSION",
            "reason": profit_gate.status,
            "message": profit_gate.message,
        })

    # Try new entries — best setup only, max lots on 85% sizing capital
    entries_ok, entry_window_reason = entries_allowed_now()
    explosion_early_ok, _ = explosion_entries_allowed_now()
    if market_live and not entries_ok and not explosion_early_ok:
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
        and (entries_ok or explosion_early_ok)
    ):
        paused, pause_reason = session_pause_active()
        if paused:
            skipped.append({
                "symbol": "SESSION",
                "reason": pause_reason,
                "message": "Loss streak pause — no new entries",
            })
        cap_hit, cap_reason = trades_cap_reached(state, snapshots)
        if cap_hit:
            skipped.append({
                "symbol": "SESSION",
                "reason": cap_reason,
                "message": "Daily trade cap on chop session",
            })
        from app.engines.pretrade_validator import controlled_daily_cap_reached, check_last_n_trades_pause
        ctrl_cap, ctrl_reason = controlled_daily_cap_reached(state, snapshots)
        if ctrl_cap:
            skipped.append({
                "symbol": "SESSION",
                "reason": ctrl_reason,
                "message": "Controlled trading daily cap",
            })
        last_n_paused, last_n_reason, last_n_meta = check_last_n_trades_pause(state, snapshots)
        if last_n_paused:
            skipped.append({
                "symbol": "SESSION",
                "reason": last_n_reason,
                "message": f"Last {last_n_meta.get('lookback', 5)} trades: "
                f"{last_n_meta.get('losses', 0)} losses, net ₹{last_n_meta.get('netPnlInr', 0):,.0f}",
            })
        whipsaw_paused, whipsaw_reason, whipsaw_meta = check_session_whipsaw_pause(state, snapshots)
        if whipsaw_paused:
            skipped.append({
                "symbol": "SESSION",
                "reason": whipsaw_reason,
                "message": whipsaw_meta.get("dualLegWhipsaw")
                or f"Whipsaw/churn pause — CE↔PE flip-flops in bearish sideways",
            })
        from app.engines.expiry_day_guards import check_expiry_entry_allowed
        from app.engines.worst_day_guard import session_entry_policy, worst_day_blocks_live

        policy, policy_meta = session_entry_policy(state, snapshots)
        from app.engines.extreme_explosion_moment import snapshots_have_all_in_explosion

        extreme_session = snapshots_have_all_in_explosion(snapshots)
        if policy == "PAUSED" and not extreme_session:
            skipped.append({
                "symbol": "SESSION",
                "reason": policy_meta.get("pauseReason", "worst_day_paused"),
                "message": f"Worst day — trading paused ({', '.join(policy_meta.get('worstDay', {}).get('reasons', []))})",
            })
        live_blocked, live_reason, _ = worst_day_blocks_live(state, snapshots)
        if live_blocked:
            skipped.append({
                "symbol": "SESSION",
                "reason": live_reason,
                "message": "Worst day — live trading blocked until conditions improve",
            })

        expiry_ok, expiry_reason, expiry_meta = check_expiry_entry_allowed(state, snapshots)
        if not expiry_ok:
            skipped.append({
                "symbol": "SESSION",
                "reason": expiry_reason,
                "message": expiry_meta.get("worstDayReasons")
                and f"Expiry guard — {', '.join(expiry_meta.get('worstDayReasons', []))}"
                or "Expiry-day entry blocked",
            })
        if (
            not paused and not cap_hit and not ctrl_cap and not last_n_paused
            and not whipsaw_paused and expiry_ok and policy != "PAUSED" and not live_blocked
        ):
            best = find_best_entry(snapshots, state, trading_limits)
            if best and explosion_early_ok and not entries_ok and best.mode != "explosion":
                best = None
            if best:
                opened, reason = await _open_from_candidate(best, state, client, news, snapshots)
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
    return resolve_trade_premium(snap, strike, side)


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
