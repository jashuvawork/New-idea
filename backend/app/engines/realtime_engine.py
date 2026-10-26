"""Real-time market intelligence engine — full snapshot pipeline."""

import asyncio
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

_constituent_cache: dict[str, tuple[float, Any]] = {}

# Premium history for velocity calc
_premium_history: dict[str, dict[float, float]] = {}
_premium_history_updated_at: dict[str, float] = {}


def reset_realtime_detector_state() -> None:
    """Clear cached runner premiums so tests/restarts never inherit stale velocity."""
    _premium_history.clear()
    _premium_history_updated_at.clear()


def constituents_due(symbol: str) -> bool:
    """Throttle heavy constituent REST fetches — reuse cache between snapshot builds."""
    import time

    settings = get_settings()
    if not settings.fetch_constituents_in_snapshot:
        return False
    sym = symbol.upper()
    cached = _constituent_cache.get(sym)
    if not cached:
        return True
    fetched_at, _ = cached
    return (time.monotonic() - fetched_at) >= max(15, settings.fetch_constituents_interval_seconds)


def last_constituent_heatmap(symbol: str):
    cached = _constituent_cache.get(symbol.upper())
    return cached[1] if cached else None


def record_constituent_heatmap(symbol: str, heatmap) -> None:
    import time

    if heatmap is not None:
        _constituent_cache[symbol.upper()] = (time.monotonic(), heatmap)


def _atm_strike(spot: float, symbol: str) -> float:
    from app.engines.moneyness import atm_strike

    return atm_strike(spot, symbol)


def _cash_rows_or_raw(candles: list) -> list:
    """Today's 09:15 IST bars when the series is timestamped.

    Live Upstox charts are ~300 bars so RSI and MACD can warm up. The head of
    that series is yesterday. Rows with no timestamp (tests, replays) stay as
    given, because there is no session date to filter.
    """
    if not candles:
        return []
    from app.engines.index_candle_rollover import cash_session_candles
    from app.services.upstox import _candle_ts

    if any(_candle_ts(row) is not None for row in candles):
        return cash_session_candles(candles)
    return list(candles)


def _bar_hlc(row: Any) -> tuple[float, float, float] | None:
    try:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            high, low, close = float(row[2] or 0), float(row[3] or 0), float(row[4] or 0)
        elif isinstance(row, dict):
            high = float(row.get("high") or 0)
            low = float(row.get("low") or 0)
            close = float(row.get("close") or 0)
        else:
            return None
    except (TypeError, ValueError):
        return None
    if high <= 0 or low <= 0 or close <= 0:
        return None
    return high, low, close


def _quoted_float(raw: Any) -> float | None:
    if raw is None or raw is False or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _detect_regime(candles: list, spot: float = 0.0) -> Regime:
    rows = _cash_rows_or_raw(candles)
    if not rows or len(rows) < 10:
        return Regime.RANGE_BOUND

    closes = [c[4] if isinstance(c, list) else c.get("close", 0) for c in rows[-20:]]
    if not closes:
        return Regime.RANGE_BOUND

    if spot > 0:
        from app.engines.spot_direction import _patch_live_close
        closes = _patch_live_close(closes, spot)

    high, low = max(closes), min(closes)
    range_pct = ((high - low) / low) * 100 if low else 0
    recent_move = abs(closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] else 0

    # Thresholds for ~20×1m bars (not session %). Old 1.5%/0.4% needed ~370 NIFTY pts
    # in 20 minutes — almost never fired TREND/VOL on live index.
    if range_pct > 0.45 and recent_move > 0.12:
        return Regime.TREND_EXPANSION
    if range_pct > 0.80:
        return Regime.VOLATILITY_SPIKE
    if range_pct < 0.12:
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
    # Price and volume pace from today's cash bars. The chart tail at 09:20
    # still contains yesterday, and that gap is not a 5-minute impulse.
    candles = _cash_rows_or_raw(candles)

    if candles and len(candles) >= 5:
        volumes = [c[5] if isinstance(c, list) else c.get("volume", 0) for c in candles[-10:]]
        closes = [
            float(c[4] if isinstance(c, list) else c.get("close", 0) or 0)
            for c in candles[-10:]
        ]
        # Live spot into the forming bar — stale last close was pinning tickMomentum at 0.
        # Only when spot is on the same instrument scale (avoid synthetic/mismatched tests).
        if spot > 0 and closes and closes[-1] > 0:
            if abs(spot - closes[-1]) / closes[-1] <= 0.05:
                closes[-1] = float(spot)

        if len(volumes) >= 3:
            recent_vol = sum(float(v or 0) for v in volumes[-3:])
            prior_vol = sum(float(v or 0) for v in volumes[-6:-3]) or 1.0
            if prior_vol > 0 and recent_vol > 0:
                vol_accel = min(100, (recent_vol / prior_vol) * 40)

        if len(closes) >= 5 and closes[-5]:
            move = closes[-1] - closes[-5]
            pct = (move / closes[-5]) * 100
            # Same class of bug as tick: *5/*8 mapped NIFTY 40–80pt/5m to ~1–2 → UI 0.
            # *120/*160: ~60pt impulse → delta≈30, breakout≈40 (strategy gates reachable).
            delta_vel = min(100.0, abs(pct) * 120)
            breakout_vel = min(100.0, abs(pct) * 160)
            signed_mom = round(pct, 3)

        # Tick momentum 0–100. Old *2000 mapped NIFTY 5–20pt bars to 0.4–1.6 → UI "0".
        # *25000 ≈ 1 score per index point at ~25k; 3-bar burst catches short rips.
        tick_1 = tick_3 = 0.0
        if len(closes) >= 2 and closes[-2] > 0:
            tick_1 = abs(closes[-1] - closes[-2]) / closes[-2] * 25000
        if len(closes) >= 4 and closes[-4] > 0:
            tick_3 = abs(closes[-1] - closes[-4]) / closes[-4] * 12000
        tick_mom = min(100.0, max(tick_1, tick_3))

    if spot_chart is not None:
        mom5 = abs(float(getattr(spot_chart, "momentum5Pct", 0) or 0))
        mom15 = abs(float(getattr(spot_chart, "momentum15Pct", 0) or 0))
        trend = float(getattr(spot_chart, "trendStrength", 0) or 0)
        if delta_vel < 8:
            delta_vel = max(delta_vel, min(100, mom5 * 120 + trend * 0.2))
        if breakout_vel < 8:
            breakout_vel = max(breakout_vel, min(100, mom15 * 100 + trend * 0.25))
        if tick_mom < 8:
            # 0.25% 5m → ~20; was *20 which left quiet sessions stuck at 0–2.
            tick_mom = max(tick_mom, min(100, mom5 * 80 + mom15 * 15))
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
    """POC, value area, and opening range from today's 09:15 cash bars.

    The first 15 bars of the 300-bar chart are yesterday. Using them made the
    open look like a break of a range that was not today's. A series with no
    cash-session print does not invent a ±50 point value area around spot.
    """
    spot_px = float(spot or 0)
    blank = MarketProfile(poc=round(spot_px, 2) if spot_px > 0 else 0.0)
    session = _cash_rows_or_raw(candles)
    bars = [hlc for row in session if (hlc := _bar_hlc(row)) is not None]
    if not bars:
        return blank

    highs = [bar[0] for bar in bars]
    lows = [bar[1] for bar in bars]
    closes = [bar[2] for bar in bars]
    poc = sum(closes) / len(closes)
    # Opening range is the first 15 cash minutes. Before that many bars
    # exist, the range printed so far is still today's range.
    or_n = min(15, len(bars))
    return MarketProfile(
        poc=round(poc, 2),
        vah=round(max(highs), 2),
        val=round(min(lows), 2),
        openingRangeHigh=round(max(highs[:or_n]), 2),
        openingRangeLow=round(min(lows[:or_n]), 2),
    )


def _build_greeks(chain: list, atm: float, spot: float, *, symbol: str = "") -> Greeks:
    """Approximate greeks from chain ATM row."""
    from app.engines.moneyness import strike_step

    # SENSEX/BANKNIFTY step=100 — hardcoded 50pt window skipped every off-ATM row.
    near = max(50.0, float(strike_step(symbol) if symbol else 100.0))
    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(float(strike or 0) - atm) > near:
            continue
        ce = row.get("call_options", {}) or row.get("CE", {}) or {}
        raw_greeks = ce.get("greeks") or {}
        greeks = raw_greeks if isinstance(raw_greeks, dict) else {}
        iv = _quoted_float(ce.get("implied_volatility"))
        if iv is None or iv <= 0:
            iv = _quoted_float(greeks.get("iv"))
            if iv is not None and iv <= 0:
                iv = None
        delta = _quoted_float(greeks.get("delta"))
        gamma = _quoted_float(greeks.get("gamma"))
        theta = _quoted_float(greeks.get("theta"))
        vega = _quoted_float(greeks.get("vega"))
        if iv is None and delta is None and gamma is None and theta is None and vega is None:
            continue
        # ivRank is a scale of the quoted IV. Upstox does not send a rank,
        # and a missing IV is not rank 50 or IV 15.
        return Greeks(
            delta=0.0 if delta is None else delta,
            gamma=0.0 if gamma is None else gamma,
            theta=0.0 if theta is None else theta,
            vega=0.0 if vega is None else vega,
            ivExpansion=(1.0 + (iv - 15.0) / 100.0) if iv else 1.0,
            ivRank=min(100.0, max(0.0, iv * 3.0)) if iv else 0.0,
        )
    return Greeks(ivRank=0.0)


def _scan_runners(
    chain: list, spot: float, atm: float, symbol: str
) -> tuple[ExplosiveRunner, list[dict[str, Any]]]:
    import time

    settings = get_settings()
    watchlist: list[dict[str, Any]] = []
    best_score = 0.0
    best_side = None
    best_strike = None
    best_premium = None
    best_vel = 0.0

    hist_key = symbol.upper()
    now_mono = time.monotonic()
    last_update = _premium_history_updated_at.get(hist_key)
    max_age = float(
        getattr(settings, "runner_velocity_history_max_age_seconds", 15.0) or 15.0
    )
    if last_update is not None and (
        now_mono < last_update or now_mono - last_update > max_age
    ):
        _premium_history.pop(hist_key, None)
    if hist_key not in _premium_history:
        _premium_history[hist_key] = {}

    # Expiry ITM monitor widens the band so most ITM CE/PE stay on the runner list.
    scan_pts = 800.0
    try:
        from app.engines.explosion_detector import resolve_explosion_scan_range

        scan_pts = float(resolve_explosion_scan_range(symbol) or 800)
    except Exception:
        scan_pts = 800.0

    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(strike - atm) > scan_pts:
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

    _premium_history_updated_at[hist_key] = now_mono
    watchlist.sort(key=lambda x: x["score"], reverse=True)

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
            from app.engines.indicator_series import (
                indicator_seed_lookback_days,
                mtf_1m_bar_count,
            )

            candles_1m = await client.get_candles(
                symbol,
                count=mtf_1m_bar_count(),
                lookback_days=indicator_seed_lookback_days(),
            )
        candles = candles_1m

        if not chain:
            raise UpstoxError("Empty option chain")

        if is_ws_active():
            chain = overlay_chain_ltps(chain, max_age_seconds=1.0)
            spot = overlay_index_ltp(symbol, spot, max_age_seconds=1.0)

        atm = _atm_strike(spot, symbol)
        heatmap = build_heatmap(chain, spot, atm, symbol=symbol)
        profile = _build_profile(candles, spot)
        spot_chart = build_spot_chart(candles_5m, spot, profile, indicator_candles_1m=candles_1m)
        orderflow = _build_orderflow(
            candles, chain, spot=spot, atm=atm, symbol=symbol, spot_chart=spot_chart,
        )

        chart_analysis = None
        day_from_open_pct = 0.0
        qctx: dict = {}
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
                from app.engines.index_candle_rollover import (
                    cash_session_candles,
                    prior_close_before_cash_session,
                )

                rows = cash_session_candles(candles_1m)
                opens, highs, lows, _closes = _candle_rows(rows)
                if opens and highs and lows:
                    qctx = {
                        "dayOpen": float(opens[0]),
                        "dayHigh": float(max(highs)),
                        "dayLow": float(min(lows)),
                    }
                    day_high = qctx["dayHigh"]
                    day_low = qctx["dayLow"]
                    if spot > 0 and qctx["dayOpen"] > 0:
                        day_from_open_pct = (spot - qctx["dayOpen"]) / qctx["dayOpen"] * 100.0
                        qctx["fromOpenPct"] = day_from_open_pct
                prev_close = prior_close_before_cash_session(candles_1m)

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
            if chart_analysis is not None and float(qctx.get("dayOpen") or 0) > 0:
                inst = dict(chart_analysis.institutional or {})
                inst["dayOpen"] = qctx["dayOpen"]
                inst["dayHigh"] = qctx["dayHigh"]
                inst["dayLow"] = qctx["dayLow"]
                chart_analysis.institutional = inst
        except Exception as exc:
            logger.debug("Chart analysis skipped for %s: %s", symbol, exc)

        option_breadth = build_breadth(chain, spot)

        from app.services.upstox import rate_limit_active

        settings = get_settings()
        constituent_hm = None
        if settings.fetch_constituents_in_snapshot:
            if constituents_due(symbol):
                if rate_limit_active():
                    constituent_hm = await build_constituent_heatmap(symbol, client, cache_only=True)
                else:
                    constituent_hm = await build_constituent_heatmap(symbol, client)
                record_constituent_heatmap(symbol, constituent_hm)
            else:
                constituent_hm = last_constituent_heatmap(symbol)
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

        greeks = _build_greeks(chain, atm, spot, symbol=symbol)
        regime = _detect_regime(candles, spot)
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
        # Best-effort India VIX for the day-type regime — never break the snapshot on failure.
        try:
            vix = await client.get_india_vix()
            if vix:
                snap.indiaVix = float(vix.get("value") or 0.0)
                snap.indiaVixRef = float(vix.get("ref") or 0.0)
        except Exception:
            pass
        try:
            from app.services.radar_archive import record_top_radars
            from app.services.radar_learning import record_market_observations

            await asyncio.to_thread(
                record_top_radars,
                {symbol: snap},
                source="rest_snapshot",
            )
            await asyncio.to_thread(
                record_market_observations,
                {symbol: snap},
                source="rest_snapshot",
            )
            from app.services.radar_health import record_component_success

            record_component_success(
                "radarPipeline",
                detail={"source": "rest_snapshot", "symbol": symbol},
            )
        except Exception as exc:
            logger.warning("Failed to archive %s radar snapshot: %s", symbol, exc)
            try:
                from app.services.radar_health import record_component_error

                record_component_error("radarPipeline", exc)
            except Exception:
                pass
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
