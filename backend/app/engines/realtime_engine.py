"""Real-time market intelligence engine — full snapshot pipeline."""

import logging
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.ai_engine import (
    build_breadth,
    build_heatmap,
    rank_runner,
    score_tqs,
)
from app.engines.premium_filter import premium_in_band
from app.models.schemas import (
    ExplosiveRunner,
    Greeks,
    MarketPhase,
    MarketProfile,
    Orderflow,
    OptimizedProfile,
    Regime,
    RunnerSignal,
    Side,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)
from app.engines.constituent_engine import (
    build_constituent_heatmap,
    resolve_snapshot_breadth,
)
from app.engines.simple_profit import get_session_targets
from app.engines.strategy_orchestrator import run_all_strategies, signals_to_suggested_trades
from app.engines.strategies.base import compute_max_pain, compute_pcr
from app.engines.explosion_detector import event_to_dict, scan_chain_explosions
from app.engines.swing_engine import scan_swing_setups, setup_to_dict
from app.engines.premarket_engine import (
    attach_premarket_to_snapshot,
    build_premarket_snapshot,
)
from app.engines.ml_engine import get_ml_engine
from app.services.tick_store import get_index_spot, overlay_chain_ltps, overlay_index_ltp
from app.services.upstox import UpstoxClient, UpstoxError, get_market_phase
from app.services.upstox_ws import is_ws_active

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Premium history for velocity calc
_premium_history: dict[str, dict[float, float]] = {}


def _atm_strike(spot: float, symbol: str) -> float:
    step = 100 if symbol in ("NIFTY", "BANKNIFTY") else 100
    if symbol == "BANKNIFTY":
        step = 100
    return round(spot / step) * step


def _detect_regime(candles: list) -> Regime:
    if not candles or len(candles) < 10:
        return Regime.RANGE_BOUND

    closes = [c[4] if isinstance(c, list) else c.get("close", 0) for c in candles[-20:]]
    if not closes:
        return Regime.RANGE_BOUND

    high, low = max(closes), min(closes)
    range_pct = ((high - low) / low) * 100 if low else 0
    recent_move = abs(closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] else 0

    if range_pct > 1.5 and recent_move > 0.4:
        return Regime.TREND_EXPANSION
    if range_pct > 2.0:
        return Regime.VOLATILITY_SPIKE
    if range_pct < 0.3:
        return Regime.CHOP
    return Regime.RANGE_BOUND


def _build_orderflow(
    candles: list,
    chain: list,
    *,
    spot: float = 0.0,
    atm: float = 0.0,
    symbol: str = "",
    spot_chart: Optional[Any] = None,
) -> Orderflow:
    """Build orderflow metrics from candles, option chain, and chart momentum."""
    delta_vel = vol_accel = breakout_vel = tick_mom = 0.0
    signed_mom = 0.0
    bid_ask_imb = 50.0

    if candles and len(candles) >= 5:
        volumes = [c[5] if isinstance(c, list) else c.get("volume", 0) for c in candles[-10:]]
        closes = [c[4] if isinstance(c, list) else c.get("close", 0) for c in candles[-10:]]

        if len(volumes) >= 3:
            recent_vol = sum(float(v or 0) for v in volumes[-3:])
            prior_vol = sum(float(v or 0) for v in volumes[-6:-3]) or 1.0
            if prior_vol > 0 and recent_vol > 0:
                vol_accel = min(100, (recent_vol / prior_vol) * 40)

        if len(closes) >= 5 and closes[-5]:
            move = closes[-1] - closes[-5]
            pct = (move / closes[-5]) * 100
            delta_vel = min(100, abs(pct) * 5)
            breakout_vel = min(100, abs(pct) * 8)
            if len(closes) >= 2 and closes[-2]:
                tick_mom = min(100, abs(closes[-1] - closes[-2]) / closes[-2] * 2000)
            signed_mom = round(pct, 3)

    if spot_chart is not None:
        mom5 = abs(float(getattr(spot_chart, "momentum5Pct", 0) or 0))
        mom15 = abs(float(getattr(spot_chart, "momentum15Pct", 0) or 0))
        trend = float(getattr(spot_chart, "trendStrength", 0) or 0)
        if delta_vel < 8:
            delta_vel = max(delta_vel, min(100, mom5 * 30 + trend * 0.15))
        if breakout_vel < 8:
            breakout_vel = max(breakout_vel, min(100, mom15 * 40 + trend * 0.2))
        if tick_mom < 8:
            tick_mom = max(tick_mom, min(100, mom5 * 20))
        if not signed_mom and mom5:
            signed_mom = round(float(getattr(spot_chart, "momentum5Pct", 0) or 0), 3)

    from app.engines.moneyness import strike_step

    step = strike_step(symbol) if symbol else 100.0
    scan_steps = 3
    call_vol = put_vol = 0.0
    chain_total = 0.0
    for row in chain:
        strike = float(row.get("strike_price") or row.get("strike") or 0)
        ce = row.get("call_options", {}) or row.get("CE", {}) or {}
        pe = row.get("put_options", {}) or row.get("PE", {}) or {}
        cv = float(ce.get("volume") or 0)
        pv = float(pe.get("volume") or 0)
        chain_total += cv + pv
        if atm > 0 and abs(strike - atm) <= step * scan_steps:
            call_vol += cv
            put_vol += pv

    if call_vol + put_vol <= 0 and chain_total > 0:
        for row in sorted(
            chain,
            key=lambda r: float((r.get("call_options") or r.get("CE") or {}).get("volume") or 0)
            + float((r.get("put_options") or r.get("PE") or {}).get("volume") or 0),
            reverse=True,
        )[:8]:
            ce = row.get("call_options", {}) or row.get("CE", {}) or {}
            pe = row.get("put_options", {}) or row.get("PE", {}) or {}
            call_vol += float(ce.get("volume") or 0)
            put_vol += float(pe.get("volume") or 0)

    total = call_vol + put_vol
    if total > 0:
        bid_ask_imb = (call_vol / total) * 100
        if vol_accel < 10:
            vol_accel = max(vol_accel, min(100, total / 5000))

    return Orderflow(
        deltaVelocity=round(delta_vel, 1),
        volumeAcceleration=round(vol_accel, 1),
        breakoutVelocity=round(breakout_vel, 1),
        bidAskImbalance=round(bid_ask_imb, 1),
        tickMomentum=round(tick_mom, 1),
        signedMomentumPct=signed_mom if candles or spot_chart else 0.0,
    )


def _build_profile(candles: list, spot: float) -> MarketProfile:
    if not candles:
        return MarketProfile(poc=spot, vah=spot + 50, val=spot - 50)

    highs = [c[2] if isinstance(c, list) else c.get("high", 0) for c in candles]
    lows = [c[3] if isinstance(c, list) else c.get("low", 0) for c in candles]
    closes = [c[4] if isinstance(c, list) else c.get("close", 0) for c in candles]

    poc = sum(closes) / len(closes) if closes else spot
    vah = max(highs) if highs else spot + 50
    val = min(lows) if lows else spot - 50
    or_high = max(highs[:15]) if len(highs) >= 15 else vah
    or_low = min(lows[:15]) if len(lows) >= 15 else val

    return MarketProfile(
        poc=round(poc, 2),
        vah=round(vah, 2),
        val=round(val, 2),
        openingRangeHigh=round(or_high, 2),
        openingRangeLow=round(or_low, 2),
    )


def _build_greeks(chain: list, atm: float, spot: float) -> Greeks:
    """Approximate greeks from chain ATM row."""
    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(strike - atm) > 50:
            continue
        ce = row.get("call_options", {}) or row.get("CE", {})
        greeks = ce.get("greeks", {}) or {}
        iv = ce.get("implied_volatility") or greeks.get("iv", 15)
        return Greeks(
            delta=greeks.get("delta", 0.45),
            gamma=greeks.get("gamma", 0.002),
            theta=greeks.get("theta", -5),
            vega=greeks.get("vega", 10),
            ivExpansion=1.0 + (iv - 15) / 100 if iv else 1.0,
            ivRank=min(100, max(0, iv * 3)) if iv else 50,
        )
    return Greeks()


def _scan_runners(
    chain: list, spot: float, atm: float, symbol: str
) -> tuple[ExplosiveRunner, list[dict[str, Any]]]:
    watchlist: list[dict[str, Any]] = []
    best_score = 0.0
    best_side = None
    best_strike = None
    best_premium = None
    best_vel = 0.0

    hist_key = f"{symbol}"
    if hist_key not in _premium_history:
        _premium_history[hist_key] = {}

    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(strike - atm) > 800:
            continue

        for side, key in [(Side.CALL, "call_options"), (Side.PUT, "put_options")]:
            opt = row.get(key, {}) or row.get("CE" if side == Side.CALL else "PE", {})
            if not opt:
                continue
            prev = _premium_history[hist_key].get(strike if side == Side.CALL else -strike)
            score, vel = rank_runner(opt, side, prev)
            ltp = opt.get("ltp") or opt.get("last_price", 0)
            if not premium_in_band(ltp, mode="explosion"):
                continue

            entry = {
                "strike": strike,
                "side": side.value,
                "score": round(score, 1),
                "premiumVelocityPct": round(vel, 2),
                "premium": ltp,
                "elite": score >= 85 and vel >= 2.5,
            }
            watchlist.append(entry)

            if score > best_score:
                best_score = score
                best_side = side
                best_strike = strike
                best_premium = ltp
                best_vel = vel

            # Update history
            hist_key_strike = strike if side == Side.CALL else -strike
            _premium_history[hist_key][hist_key_strike] = ltp

    watchlist.sort(key=lambda x: x["score"], reverse=True)

    settings = get_settings()
    candidate = best_score >= settings.enhanced_tqs_entry and best_vel >= settings.enhanced_velocity_threshold

    return (
        ExplosiveRunner(
            candidate=candidate,
            score=round(best_score, 1),
            side=best_side,
            strike=best_strike,
            premium=best_premium,
            signal=RunnerSignal(
                score=round(best_score, 1),
                premiumVelocityPct=round(best_vel, 2),
                volumeSurge=best_score * 0.5,
                elite=best_score >= 85 and best_vel >= 2.5,
            ),
        ),
        watchlist[:20],
    )


def _build_suggestions(
    symbol: str,
    spot: float,
    atm: float,
    tqs: float,
    runner: ExplosiveRunner,
    breadth,
    profile: OptimizedProfile,
) -> list[SuggestedTrade]:
    suggestions: list[SuggestedTrade] = []
    settings = get_settings()

    if not runner.candidate or not runner.side or not runner.strike:
        return suggestions

    adaptive_target = profile.targetPoints
    if settings.adaptive_target_enabled and runner.signal:
        if runner.signal.premiumVelocityPct >= 3.0:
            adaptive_target = min(profile.targetPoints + 1.5, 8.0)
        elif runner.signal.premiumVelocityPct < 2.0:
            adaptive_target = max(profile.targetPoints - 1.0, 4.0)

    trade = SuggestedTrade(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        side=runner.side,
        strike=runner.strike,
        lastPremium=runner.premium or 0,
        tqs=tqs,
        strategyType=StrategyType.SCALP,
        runnerSignal=runner.signal,
        confidence=min(100, (tqs + runner.score) / 2),
        adaptiveTarget=adaptive_target,
    )
    suggestions.append(trade)

    # Counter-side if strong breadth divergence (enhanced)
    if breadth.score > 70 and breadth.aligned:
        opp_side = Side.PUT if runner.side == Side.CALL else Side.CALL
        # Only add if TQS supports
        if tqs >= settings.enhanced_tqs_entry + 5:
            suggestions.append(
                SuggestedTrade(
                    id=str(uuid.uuid4())[:8],
                    symbol=symbol,
                    side=opp_side,
                    strike=atm,
                    lastPremium=0,
                    tqs=tqs * 0.9,
                    strategyType=StrategyType.SCALP,
                    confidence=tqs * 0.85,
                )
            )

    return suggestions


def _build_explosion_suggestions(
    symbol: str,
    events: list,
    tqs: float,
) -> list[SuggestedTrade]:
    """Build trade suggestions from explosion events — highest priority."""
    from app.engines.explosion_detector import ExplosionEvent
    trades: list[SuggestedTrade] = []
    for event in events:
        if not isinstance(event, ExplosionEvent):
            continue
        if event.tier not in ("EXPLODING", "ELITE"):
            continue
        trades.append(SuggestedTrade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side=event.side,
            strike=event.strike,
            lastPremium=event.premium,
            tqs=max(tqs, event.explosion_score),
            strategyType=StrategyType.EXPLOSIVE,
            confidence=event.explosion_score,
            adaptiveTarget=25.0 if event.tier == "ELITE" else 12.0,
            runnerSignal=RunnerSignal(
                score=event.explosion_score,
                premiumVelocityPct=event.velocity_3s,
                volumeSurge=event.volume_surge * 50,
                elite=event.tier == "ELITE",
            ),
        ))
        if len(trades) >= 3:
            break
    return trades


async def build_symbol_snapshot(
    symbol: str,
    client: Optional[UpstoxClient] = None,
    news_sentiment: str = "NEUTRAL",
) -> SymbolSnapshot:
    """Full pipeline for one symbol. Returns waiting state if no real data."""
    phase_str = get_market_phase()
    phase = MarketPhase(phase_str) if phase_str in MarketPhase.__members__ else MarketPhase.CLOSED
    now = datetime.now(IST)

    if phase == MarketPhase.CLOSED:
        return SymbolSnapshot(
            symbol=symbol,
            timestamp=now,
            marketPhase=phase,
            dataAvailable=False,
            error="Market closed",
        )

    if not client:
        client = UpstoxClient()

    if phase == MarketPhase.PREMARKET:
        try:
            return await build_premarket_snapshot(symbol, client, news_sentiment)
        except UpstoxError as e:
            logger.warning("Premarket error for %s: %s", symbol, e)
            return SymbolSnapshot(
                symbol=symbol,
                timestamp=now,
                marketPhase=phase,
                dataAvailable=False,
                error=str(e),
            )
        except Exception as e:
            logger.exception("Premarket snapshot error for %s", symbol)
            return SymbolSnapshot(
                symbol=symbol,
                timestamp=now,
                marketPhase=phase,
                dataAvailable=False,
                error=f"Premarket error: {e}",
            )

    try:
        if is_ws_active():
            ws_spot = get_index_spot(symbol, max_age_seconds=3.0)
            spot = ws_spot if ws_spot is not None else await client.get_index_ltp(symbol)
        else:
            spot = await client.get_index_ltp(symbol)
        chain, expiry = await client.get_option_chain_resolved(symbol)
        from app.engines.index_chart_candles import fetch_index_chart_candles
        from app.engines.spot_direction import build_spot_chart

        candles_5m, candles_1m = await fetch_index_chart_candles(client, symbol)
        if not candles_1m:
            candles_1m = await client.get_candles(symbol)
        candles = candles_1m

        if not chain:
            raise UpstoxError("Empty option chain")

        if is_ws_active():
            chain = overlay_chain_ltps(chain, max_age_seconds=1.0)
            spot = overlay_index_ltp(symbol, spot, max_age_seconds=1.0)

        atm = _atm_strike(spot, symbol)
        heatmap = build_heatmap(chain, spot, atm)
        profile = _build_profile(candles, spot)
        spot_chart = build_spot_chart(candles_5m, spot, profile, indicator_candles_1m=candles_1m)
        orderflow = _build_orderflow(
            candles, chain, spot=spot, atm=atm, symbol=symbol, spot_chart=spot_chart,
        )

        chart_analysis = None
        day_from_open_pct = 0.0
        try:
            from app.engines.chart_advanced_analysis import build_chart_analysis
            from app.engines.spot_direction import _candle_rows, pro_index_quote_context

            prev_close = day_high = day_low = 0.0
            try:
                quote = await client.get_index_quote(symbol)
                qctx = pro_index_quote_context(quote, spot)
                prev_close = qctx["prevClose"]
                day_high = qctx["dayHigh"]
                day_low = qctx["dayLow"]
                day_from_open_pct = float(qctx.get("fromOpenPct") or 0)
            except Exception:
                _, highs, lows, closes = _candle_rows(candles_1m)
                if highs and lows:
                    day_high = max(highs)
                    day_low = min(lows)
                if closes:
                    prev_close = closes[0]

            chart_analysis = build_chart_analysis(
                candles_1m,
                candles_5m,
                spot,
                profile,
                prev_close=prev_close,
                day_high=day_high,
                day_low=day_low,
                symbol=symbol,
            )
        except Exception as exc:
            logger.debug("Chart analysis skipped for %s: %s", symbol, exc)

        option_breadth = build_breadth(chain, spot)

        constituent_hm = None
        from app.services.upstox import rate_limit_active

        settings = get_settings()
        if settings.fetch_constituents_in_snapshot:
            if rate_limit_active():
                constituent_hm = await build_constituent_heatmap(symbol, client, cache_only=True)
            else:
                constituent_hm = await build_constituent_heatmap(symbol, client)
        breadth = resolve_snapshot_breadth(
            option_breadth,
            constituent_hm,
            use_constituents=settings.fetch_constituents_in_snapshot,
        )

        if chart_analysis:
            from app.engines.spot_direction import reconcile_spot_chart_with_mtf

            spot_chart = reconcile_spot_chart_with_mtf(
                spot_chart,
                chart_analysis,
                breadth_bias=breadth.bias or "NEUTRAL",
                from_open_pct=day_from_open_pct,
            )

        greeks = _build_greeks(chain, atm, spot)
        regime = _detect_regime(candles)
        runner, watchlist = _scan_runners(chain, spot, atm, symbol)

        tqs, _ = score_tqs(
            orderflow, greeks, breadth, profile, spot, regime,
            runner.signal.premiumVelocityPct if runner.signal else 0,
            news_sentiment,
        )

        session_profile = get_session_targets()
        pcr = compute_pcr(chain)
        max_pain = compute_max_pain(chain)

        # Explosion scan — primary focus for daily chart moments
        from app.engines.expiry_day_guards import _today_str

        expiry_day = bool(expiry and str(expiry)[:10] == _today_str())
        explosion_events = scan_chain_explosions(
            symbol, chain, spot, atm, expiry_day=expiry_day,
        )
        explosion_alerts = [event_to_dict(e) for e in explosion_events[:15]]
        top_explosion = explosion_alerts[0] if explosion_alerts else None

        swing_setups = scan_swing_setups(
            symbol, spot, atm, chain, orderflow, breadth, profile, regime, tqs,
        )
        swing_alerts = [setup_to_dict(s) for s in swing_setups]
        top_swing = swing_alerts[0] if swing_alerts else None

        # Run all strategies (explosion events injected)
        strategy_signals, strategy_matrix = run_all_strategies(
            symbol, spot, atm, chain, orderflow, greeks, breadth,
            profile, regime, heatmap, tqs, explosion_events=explosion_events,
        )
        ml_suggestions = signals_to_suggested_trades(strategy_signals, tqs)

        # Explosion trades get top priority in suggestions
        explosion_suggestions = _build_explosion_suggestions(symbol, explosion_events, tqs)
        seen = {(s.side, s.strike) for s in explosion_suggestions}
        for s in ml_suggestions:
            if (s.side, s.strike) not in seen:
                explosion_suggestions.append(s)
                seen.add((s.side, s.strike))

        runner_suggestions = _build_suggestions(symbol, spot, atm, tqs, runner, breadth, session_profile)
        for rs in runner_suggestions:
            if (rs.side, rs.strike) not in seen:
                explosion_suggestions.append(rs)
                seen.add((rs.side, rs.strike))

        ml = get_ml_engine()
        ml_insights = {
            "featureImportance": ml.get_feature_importance(),
            "modelTrained": ml._trained,
            "activeStrategies": sum(1 for m in strategy_matrix if m.get("status") == "active"),
            "topStrategy": strategy_matrix[0] if strategy_matrix else None,
            "explosionCount": len([e for e in explosion_events if e.tier in ("EXPLODING", "ELITE")]),
        }

        snap = SymbolSnapshot(
            symbol=symbol,
            timestamp=now,
            marketPhase=phase,
            dataAvailable=True,
            tradeQualityScore=tqs,
            regime=regime,
            spot=spot,
            atmStrike=atm,
            optionExpiry=expiry,
            heatmap=heatmap,
            orderflow=orderflow,
            greeks=greeks,
            marketProfile=profile,
            breadth=breadth,
            explosiveRunner=runner,
            explosiveRunnerWatchlist=watchlist,
            suggestedTrades=explosion_suggestions[:5],
            optimizedProfile=session_profile,
            strategyMatrix=strategy_matrix,
            mlInsights=ml_insights,
            pcr=round(pcr, 3),
            maxPain=max_pain,
            explosionAlerts=explosion_alerts,
            topExplosion=top_explosion,
            swingAlerts=swing_alerts,
            topSwing=top_swing,
            constituentHeatmap=constituent_hm if constituent_hm and constituent_hm.dataAvailable else None,
            spotChart=spot_chart,
            chartAnalysis=chart_analysis,
        )
        await attach_premarket_to_snapshot(snap, client, news_sentiment)
        return snap

    except UpstoxError as e:
        logger.warning("Upstox error for %s: %s", symbol, e)
        return SymbolSnapshot(
            symbol=symbol,
            timestamp=now,
            marketPhase=phase,
            dataAvailable=False,
            error=str(e),
        )
    except Exception as e:
        logger.exception("Snapshot error for %s", symbol)
        return SymbolSnapshot(
            symbol=symbol,
            timestamp=now,
            marketPhase=phase,
            dataAvailable=False,
            error=f"Processing error: {e}",
        )
