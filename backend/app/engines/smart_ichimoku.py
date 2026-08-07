"""GainzAlgo-style Smart Ichimoku — HMA cloud + logistic cloud-break classifier.

Public methodology (TradingView Smart Ichimoku | GainzAlgo):
- Replace Donchian midlines with Hull MA (9 / 26 / 52, displace 26)
- On cloud break, score RSI + Stochastic + Z-score + ATR break depth
- Sigmoid probability; confirm when P ≥ threshold (default 0.60)
"""

from __future__ import annotations

import math
from typing import Any, Optional

from app.config import get_settings  # noqa: E402 — typed settings via getattr
from app.engines.chart_indicators import (
    compute_atr,
    compute_rsi,
    compute_stochastic,
    compute_zscore,
    hull_ma_series,
)
from app.models.schemas import Side, SymbolSnapshot


def _ichimoku_mid(
    highs: list[float], lows: list[float], end: int, period: int, fallback: float
) -> float:
    if end < 0 or not highs or not lows:
        return fallback
    start = max(0, end - period + 1)
    window_h = highs[start : end + 1]
    window_l = lows[start : end + 1]
    if not window_h or not window_l:
        return fallback
    return (max(window_h) + min(window_l)) / 2


def _sigmoid(z: float) -> float:
    z = max(-20.0, min(20.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def _vs_cloud(px: float, top: float, bottom: float) -> str:
    if px > top:
        return "ABOVE"
    if px < bottom:
        return "BELOW"
    return "INSIDE"


def compute_smart_ichimoku(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    spot: float,
) -> dict[str, Any]:
    """Full smart Ichimoku read (HMA cloud + break classifier + composite bias)."""
    settings = get_settings()
    use_hma = bool(getattr(settings, "smart_ichimoku_use_hma", True))
    tenkan_p = int(getattr(settings, "smart_ichimoku_tenkan_period", 9) or 9)
    kijun_p = int(getattr(settings, "smart_ichimoku_kijun_period", 26) or 26)
    senkou_b_p = int(getattr(settings, "smart_ichimoku_senkou_b_period", 52) or 52)
    displace = int(getattr(settings, "smart_ichimoku_displacement", 26) or 26)
    break_thr = float(getattr(settings, "smart_ichimoku_break_min_probability", 0.60) or 0.60)
    cont_thr = float(
        getattr(settings, "smart_ichimoku_continuation_min_probability", 0.55) or 0.55
    )

    n = min(len(highs), len(lows), len(closes))
    empty = {
        "tenkan": round(spot, 2),
        "kijun": round(spot, 2),
        "senkouA": round(spot, 2),
        "senkouB": round(spot, 2),
        "cloudTop": round(spot, 2),
        "cloudBottom": round(spot, 2),
        "cloudBias": "NEUTRAL",
        "tkCross": "NEUTRAL",
        "priceVsCloud": "INSIDE",
        "smartBias": "NEUTRAL",
        "smartScore": 50.0,
        "smartLabel": "Ichimoku neutral",
        "reasons": [],
        "engine": "hma_logistic" if use_hma else "donchian",
        "breakProbability": 0.0,
        "breakConfirmed": False,
        "breakSide": "NONE",
        "breakEvent": False,
        "breakRisk": "HIGH",
    }
    if n <= 0:
        return empty

    highs = [float(x) for x in highs[-n:]]
    lows = [float(x) for x in lows[-n:]]
    closes = [float(x) for x in closes[-n:]]
    last = n - 1
    px = float(spot or closes[last] or 0)

    if use_hma:
        tenkan_series = hull_ma_series(closes, tenkan_p)
        kijun_series = hull_ma_series(closes, kijun_p)
        senkou_b_series = hull_ma_series(closes, senkou_b_p)
        tenkan = tenkan_series[last]
        kijun = kijun_series[last]
        future_a = (tenkan + kijun) / 2
        future_b = senkou_b_series[last]
        if last >= displace:
            past = last - displace
            senkou_a = (tenkan_series[past] + kijun_series[past]) / 2
            senkou_b = senkou_b_series[past]
            cloud_displaced = True
        else:
            senkou_a, senkou_b = future_a, future_b
            cloud_displaced = False

        def _tk_at(i: int) -> tuple[float, float]:
            return tenkan_series[i], kijun_series[i]

        def _cloud_at(i: int) -> tuple[float, float]:
            if i >= displace:
                p = i - displace
                a = (tenkan_series[p] + kijun_series[p]) / 2
                b = senkou_b_series[p]
            else:
                a = (tenkan_series[i] + kijun_series[i]) / 2
                b = senkou_b_series[i]
            return max(a, b), min(a, b)
    else:
        tenkan = _ichimoku_mid(highs, lows, last, tenkan_p, px)
        kijun = _ichimoku_mid(highs, lows, last, kijun_p, px)
        future_a = (tenkan + kijun) / 2
        future_b = _ichimoku_mid(highs, lows, last, senkou_b_p, px)
        if last >= displace:
            past = last - displace
            senkou_a = (
                _ichimoku_mid(highs, lows, past, tenkan_p, px)
                + _ichimoku_mid(highs, lows, past, kijun_p, px)
            ) / 2
            senkou_b = _ichimoku_mid(highs, lows, past, senkou_b_p, px)
            cloud_displaced = True
        else:
            senkou_a, senkou_b = future_a, future_b
            cloud_displaced = False

        def _tk_at(i: int) -> tuple[float, float]:
            return (
                _ichimoku_mid(highs, lows, i, tenkan_p, px),
                _ichimoku_mid(highs, lows, i, kijun_p, px),
            )

        def _cloud_at(i: int) -> tuple[float, float]:
            if i >= displace:
                p = i - displace
                a = (
                    _ichimoku_mid(highs, lows, p, tenkan_p, px)
                    + _ichimoku_mid(highs, lows, p, kijun_p, px)
                ) / 2
                b = _ichimoku_mid(highs, lows, p, senkou_b_p, px)
            else:
                t, k = _tk_at(i)
                a = (t + k) / 2
                b = _ichimoku_mid(highs, lows, i, senkou_b_p, px)
            return max(a, b), min(a, b)

    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    cloud_thickness = max(cloud_top - cloud_bottom, 0.0)
    cloud_thickness_pct = (cloud_thickness / px * 100.0) if px > 0 else 0.0
    price_vs = _vs_cloud(px, cloud_top, cloud_bottom)
    cloud_bias = (
        "BULLISH" if price_vs == "ABOVE" else "BEARISH" if price_vs == "BELOW" else "NEUTRAL"
    )
    tk_cross = "BULLISH" if tenkan > kijun else "BEARISH" if tenkan < kijun else "NEUTRAL"

    tk_cross_age = 0
    if tk_cross != "NEUTRAL" and n >= 3:
        for lookback in range(1, min(n, 40)):
            t_i, k_i = _tk_at(last - lookback)
            state = "BULLISH" if t_i > k_i else "BEARISH" if t_i < k_i else "NEUTRAL"
            if state != tk_cross:
                break
            tk_cross_age = lookback
        tk_cross_age = max(1, tk_cross_age)

    chikou_bias = "NEUTRAL"
    chikou_vs = "FLAT"
    if last >= displace:
        lag_px = closes[last - displace]
        if lag_px > 0:
            if px > lag_px * 1.0005:
                chikou_bias, chikou_vs = "BULLISH", "ABOVE"
            elif px < lag_px * 0.9995:
                chikou_bias, chikou_vs = "BEARISH", "BELOW"

    cloud_twist = "NONE"
    if last >= displace + 3:
        states: list[str] = []
        for lookback in range(0, 6):
            i = last - displace - lookback
            if i < 0:
                break
            t_i, k_i = _tk_at(i)
            a_i = (t_i + k_i) / 2
            if use_hma:
                b_i = senkou_b_series[i]
            else:
                b_i = _ichimoku_mid(highs, lows, i, senkou_b_p, px)
            states.append("BULLISH" if a_i >= b_i else "BEARISH")
        if len(states) >= 2 and states[0] != states[1]:
            cloud_twist = states[0]

    future_cloud = (
        "BULLISH" if future_a > future_b else "BEARISH" if future_a < future_b else "NEUTRAL"
    )

    # --- Logistic cloud-break classifier (GainzAlgo-style) ---
    prev_top, prev_bot = _cloud_at(last - 1) if last >= 1 else (cloud_top, cloud_bottom)
    prev_vs = _vs_cloud(closes[last - 1] if last >= 1 else px, prev_top, prev_bot)
    break_side = "NONE"
    break_event = False
    if price_vs == "ABOVE" and prev_vs != "ABOVE":
        break_side = "BULLISH"
        break_event = True
    elif price_vs == "BELOW" and prev_vs != "BELOW":
        break_side = "BEARISH"
        break_event = True
    elif price_vs == "ABOVE":
        break_side = "BULLISH"  # continuation
    elif price_vs == "BELOW":
        break_side = "BEARISH"

    rsi = compute_rsi(closes, 14).value
    stoch = compute_stochastic(highs, lows, closes, 14)
    zscore = compute_zscore(closes, 20)
    atr = compute_atr(highs, lows, closes, 14)
    if break_side == "BULLISH":
        depth = max(0.0, px - cloud_top)
        f_rsi = (rsi - 50.0) / 25.0
        f_stoch = (stoch - 50.0) / 25.0
        f_z = zscore
        f_depth = (depth / atr) if atr > 1e-9 else 0.0
    elif break_side == "BEARISH":
        depth = max(0.0, cloud_bottom - px)
        f_rsi = (50.0 - rsi) / 25.0
        f_stoch = (50.0 - stoch) / 25.0
        f_z = -zscore
        f_depth = (depth / atr) if atr > 1e-9 else 0.0
    else:
        f_rsi = f_stoch = f_z = f_depth = 0.0
        depth = 0.0

    w_rsi = float(getattr(settings, "smart_ichimoku_weight_rsi", 0.85) or 0.85)
    w_stoch = float(getattr(settings, "smart_ichimoku_weight_stoch", 0.65) or 0.65)
    w_z = float(getattr(settings, "smart_ichimoku_weight_zscore", 0.90) or 0.90)
    w_depth = float(getattr(settings, "smart_ichimoku_weight_depth", 1.10) or 1.10)
    # Mild self-calibration: shrink features that are extreme noise when ATR tiny.
    z_logit = w_rsi * f_rsi + w_stoch * f_stoch + w_z * f_z + w_depth * max(-1.0, min(3.0, f_depth))
    break_p = _sigmoid(z_logit) if break_side != "NONE" else 0.0

    thr = break_thr if break_event else cont_thr
    break_confirmed = bool(break_side != "NONE" and break_p >= thr)
    if break_side == "NONE":
        break_risk = "HIGH"
    elif break_p >= break_thr:
        break_risk = "LOW"
    elif break_p >= cont_thr:
        break_risk = "MODERATE"
    else:
        break_risk = "HIGH"

    # Composite smart score (legacy UI/confidence) blended with break P.
    score = 50.0
    reasons: list[str] = []
    if use_hma:
        reasons.append("hma_cloud")
    if price_vs == "ABOVE":
        score += 12
        reasons.append("price_above_cloud")
    elif price_vs == "BELOW":
        score -= 12
        reasons.append("price_below_cloud")
    else:
        reasons.append("price_inside_cloud")

    if tk_cross == "BULLISH":
        score += 8 if tk_cross_age <= 5 else 5
        reasons.append(f"tk_bullish_age_{tk_cross_age}")
    elif tk_cross == "BEARISH":
        score -= 8 if tk_cross_age <= 5 else 5
        reasons.append(f"tk_bearish_age_{tk_cross_age}")

    if chikou_bias == "BULLISH":
        score += 8
        reasons.append("chikou_above")
    elif chikou_bias == "BEARISH":
        score -= 8
        reasons.append("chikou_below")

    if cloud_twist == "BULLISH":
        score += 6
        reasons.append("cloud_twist_bullish")
    elif cloud_twist == "BEARISH":
        score -= 6
        reasons.append("cloud_twist_bearish")

    # Blend break probability into score (±15).
    if break_side == "BULLISH":
        score += (break_p - 0.5) * 30.0
        reasons.append(f"break_p_{break_p:.2f}")
    elif break_side == "BEARISH":
        score -= (break_p - 0.5) * 30.0
        reasons.append(f"break_p_{break_p:.2f}")

    if break_confirmed:
        reasons.append("break_confirmed")
    elif break_side != "NONE":
        reasons.append(f"break_risk_{break_risk.lower()}")

    score = max(0.0, min(100.0, score))
    if score >= 62:
        smart_bias = "BULLISH"
    elif score <= 38:
        smart_bias = "BEARISH"
    else:
        smart_bias = "NEUTRAL"

    if break_confirmed and break_side == "BULLISH":
        smart_label = f"Smart Ichimoku break ↑ P={break_p:.0%}"
    elif break_confirmed and break_side == "BEARISH":
        smart_label = f"Smart Ichimoku break ↓ P={break_p:.0%}"
    elif smart_bias == "BULLISH":
        smart_label = "Smart Ichimoku bullish"
    elif smart_bias == "BEARISH":
        smart_label = "Smart Ichimoku bearish"
    else:
        smart_label = "Smart Ichimoku mixed"

    return {
        "tenkan": round(tenkan, 2),
        "kijun": round(kijun, 2),
        "senkouA": round(senkou_a, 2),
        "senkouB": round(senkou_b, 2),
        "futureSenkouA": round(future_a, 2),
        "futureSenkouB": round(future_b, 2),
        "cloudTop": round(cloud_top, 2),
        "cloudBottom": round(cloud_bottom, 2),
        "cloudBias": cloud_bias,
        "tkCross": tk_cross,
        "tkCrossAge": int(tk_cross_age),
        "priceVsCloud": price_vs,
        "chikouBias": chikou_bias,
        "chikouVs": chikou_vs,
        "cloudTwist": cloud_twist,
        "cloudThickness": round(cloud_thickness, 2),
        "cloudThicknessPct": round(cloud_thickness_pct, 3),
        "futureCloud": future_cloud,
        "cloudDisplaced": cloud_displaced,
        "smartBias": smart_bias,
        "smartScore": round(score, 1),
        "smartLabel": smart_label,
        "reasons": reasons[:10],
        "engine": "hma_logistic" if use_hma else "donchian_logistic",
        "breakProbability": round(break_p, 3),
        "breakConfirmed": break_confirmed,
        "breakSide": break_side,
        "breakEvent": break_event,
        "breakRisk": break_risk,
        "breakThreshold": thr,
        "breakFeatures": {
            "rsi": round(rsi, 2),
            "stoch": round(stoch, 2),
            "zscore": round(zscore, 3),
            "atr": round(atr, 3),
            "depth": round(depth, 3),
            "depthAtr": round(f_depth, 3),
        },
    }


def ichimoku_break_supports_side(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    require_confirmed: bool = True,
) -> tuple[bool, str]:
    """True when smart Ichimoku break-P agrees with CALL/PUT for flat→vertical."""
    settings = get_settings()
    if not bool(getattr(settings, "smart_ichimoku_flat_vertical_confirm_enabled", True)):
        return True, "smart_ichimoku_confirm_disabled"
    if snap is None:
        return True, "no_snap"
    analysis = getattr(snap, "chartAnalysis", None)
    ich = getattr(analysis, "ichimoku", None) if analysis is not None else None
    if not isinstance(ich, dict) or not ich:
        return True, "no_ichimoku"  # fail-open without candles
    side_v = side.value if isinstance(side, Side) else str(side or "").upper()
    target = "BULLISH" if side_v == "CALL" else "BEARISH" if side_v == "PUT" else ""
    if not target:
        return True, "bad_side"
    break_side = str(ich.get("breakSide") or "NONE").upper()
    # Prefer HMA cloud position when classic levels are used for SL/TP.
    price_vs = str(
        ich.get("smartPriceVsCloud") or ich.get("priceVsCloud") or ""
    ).upper()
    p = float(ich.get("breakProbability") or 0)
    confirmed = bool(ich.get("breakConfirmed"))
    smart = str(ich.get("smartBias") or "NEUTRAL").upper()

    # Must be on the correct side of the (smart) cloud for the option.
    if target == "BULLISH" and price_vs != "ABOVE":
        return False, f"smart_ichimoku_cloud_{price_vs.lower()}_not_above"
    if target == "BEARISH" and price_vs != "BELOW":
        return False, f"smart_ichimoku_cloud_{price_vs.lower()}_not_below"
    if break_side not in (target, "NONE"):
        return False, f"smart_ichimoku_break_{break_side.lower()}_oppose"
    if require_confirmed and not confirmed:
        return False, f"smart_ichimoku_break_p_{p:.2f}_unconfirmed"
    if break_side == target and (confirmed or p >= cont_thr_fallback(settings)):
        return True, f"smart_ichimoku_break_{target.lower()}_p_{p:.2f}"
    if smart == target and p >= cont_thr_fallback(settings):
        return True, f"smart_ichimoku_smart_{target.lower()}_p_{p:.2f}"
    return False, f"smart_ichimoku_weak_p_{p:.2f}"


def cont_thr_fallback(settings: Any = None) -> float:
    settings = settings or get_settings()
    return float(
        getattr(settings, "smart_ichimoku_continuation_min_probability", 0.55) or 0.55
    )
