"""Powerful OHLC(V) indicators for explosion capture and chop avoidance.

All pure-Python, list-based (no numpy), matching chart_indicators.py style:
- Bollinger Bands + Keltner Channels
- TTM Squeeze (compression -> expansion) with regression momentum + direction
- ADX / +DI / -DI (trend strength + direction, chop filter)
- Supertrend (ATR trend follow, clean flips for trailing/direction)
- VWAP with bands + reclaim/loss (fast institutional turn signal)

The Squeeze is the highest-fit signal for a flat base -> vertical rip: a
compression (BB inside KC) that then *releases* with momentum is the explosion
starting — caught AT the base rather than 30%+ into the move.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.engines.chart_indicators import _ema_series, compute_rsi


@dataclass(frozen=True)
class BollingerRead:
    upper: float = 0.0
    middle: float = 0.0
    lower: float = 0.0
    bandwidth: float = 0.0  # (upper-lower)/middle*100


@dataclass(frozen=True)
class KeltnerRead:
    upper: float = 0.0
    middle: float = 0.0
    lower: float = 0.0


@dataclass(frozen=True)
class SqueezeRead:
    on: bool = False           # currently compressed (BB inside KC)
    fired: bool = False        # released on this exact bar (explosion trigger)
    bars_on: int = 0           # consecutive bars in squeeze (coil length)
    bars_since_fired: int = -1  # bars since the coil released (-1 = no recent squeeze)
    momentum: float = 0.0      # regression momentum of de-trended price
    direction: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL (break direction)
    state: str = "NONE"        # SQUEEZE | FIRED | OFF | NONE

    def fresh_fire(self, side: str = "", *, window: int = 3) -> bool:
        """True when the coil released within ``window`` bars and momentum is expanding
        toward ``side`` (CALL->BULLISH, PUT->BEARISH). The practical entry-at-base signal."""
        if self.bars_since_fired < 0 or self.bars_since_fired > window:
            return False
        s = (side or "").upper()
        if s == "CALL":
            return self.direction == "BULLISH"
        if s == "PUT":
            return self.direction == "BEARISH"
        return self.direction in ("BULLISH", "BEARISH")


@dataclass(frozen=True)
class AdxRead:
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    regime: str = "CHOP"       # TREND | TRANSITION | CHOP
    direction: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL


@dataclass(frozen=True)
class SupertrendRead:
    value: float = 0.0
    direction: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    flipped: bool = False       # direction changed on the latest bar


@dataclass(frozen=True)
class VwapRead:
    vwap: float = 0.0
    upper: float = 0.0
    lower: float = 0.0
    position: str = "AT"        # ABOVE | BELOW | AT
    reclaim: str = "NONE"       # BULLISH_RECLAIM | BEARISH_LOSS | NONE
    volume_weighted: bool = False  # False = price-anchored fallback (index has no volume)


@dataclass(frozen=True)
class DecisiveCandleRead:
    """GainzAlgo-style decisive reversal bar — a fast, non-repainting ignition confirm.

    The last CLOSED bar is a strong-bodied engulfing candle (body/range high = conviction,
    not a wick), RSI agrees and is not exhausted, and it follows a recent counter move (a
    genuine turn off a base, not chop continuation). Fires right as the coil breaks — earlier
    than the 45s smoothed index drift on a modest grind-then-pop move.
    """
    direction: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    decisive: bool = False      # all conditions aligned on the latest closed bar
    body_ratio: float = 0.0     # |close-open| / (high-low) of the latest bar
    engulfing: bool = False
    after_pullback: bool = False
    rsi: float = 50.0


def index_squeeze_confirms_side(side: Any, snap: Any) -> bool:
    """True when the index chart's squeeze released recently with momentum toward the
    option side (CALL->BULLISH, PUT->BEARISH) — a fresh base->explosion confirmation.

    Reads the already-computed chartAnalysis.squeeze dict on the snapshot, so it adds no
    recompute cost. Additive only (used for a rank bonus), never a gate.
    """
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "squeeze_rank_bonus_enabled", True)):
        return False
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    sq = getattr(ca, "squeeze", None) if ca is not None else None
    if not isinstance(sq, dict) or not sq:
        return False
    bsf = sq.get("bars_since_fired", -1)
    try:
        bsf = int(bsf)
    except (TypeError, ValueError):
        return False
    window = int(getattr(settings, "squeeze_fresh_window_bars", 3) or 3)
    if bsf < 0 or bsf > window:
        return False
    direction = str(sq.get("direction") or "NEUTRAL").upper()
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    if side_v == "CALL":
        return direction == "BULLISH"
    if side_v == "PUT":
        return direction == "BEARISH"
    return False


def index_adx_rank_adjust(side: Any, snap: Any) -> float:
    """Rank delta from the index ADX regime: + when a real TREND is aligned with the side,
    − on CHOP (nudge selection toward trend days, away from chop). Additive, never a gate."""
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "adx_rank_enabled", True)):
        return 0.0
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    adx = getattr(ca, "adx", None) if ca is not None else None
    if not isinstance(adx, dict) or not adx:
        return 0.0
    regime = str(adx.get("regime") or "").upper()
    direction = str(adx.get("direction") or "NEUTRAL").upper()
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    target = "BULLISH" if side_v == "CALL" else "BEARISH" if side_v == "PUT" else ""
    if regime == "CHOP":
        return -float(getattr(settings, "adx_chop_rank_penalty", 8.0) or 8.0)
    if regime == "TREND" and target and direction == target:
        return float(getattr(settings, "adx_trend_rank_bonus", 6.0) or 6.0)
    return 0.0


def index_vwap_confirms_side(side: Any, snap: Any) -> bool:
    """True when the index VWAP just reclaimed toward the side (bullish reclaim for CALL,
    bearish loss for PUT) — a fast institutional turn confirmation for a rank bonus."""
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "vwap_reclaim_rank_bonus_enabled", True)):
        return False
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    vw = getattr(ca, "vwap", None) if ca is not None else None
    if not isinstance(vw, dict) or not vw:
        return False
    reclaim = str(vw.get("reclaim") or "NONE").upper()
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    if side_v == "CALL":
        return reclaim == "BULLISH_RECLAIM"
    if side_v == "PUT":
        return reclaim == "BEARISH_LOSS"
    return False


def option_instrument_key(snap: Any, strike: Any, side: Any) -> Optional[str]:
    """Resolve the CE/PE Upstox instrument key for a strike from the snapshot heatmap."""
    hm = getattr(snap, "heatmap", None) if snap is not None else None
    if not hm:
        return None
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    field = "callInstrumentKey" if side_v == "CALL" else "putInstrumentKey"
    try:
        target = float(strike)
    except (TypeError, ValueError):
        return None
    for row in hm:
        try:
            if abs(float(getattr(row, "strike", 0) or 0) - target) < 0.5:
                return getattr(row, field, None)
        except (TypeError, ValueError):
            continue
    return None


def option_cvd_confirms_buying(snap: Any, strike: Any, side: Any) -> bool:
    """True when the option we're buying shows net BUYING on recent CVD — real demand
    behind the rip (fade a hollow print). Additive confirmation, never a gate."""
    from app.config import get_settings
    from app.services.cvd_store import get_cvd

    settings = get_settings()
    if not bool(getattr(settings, "cvd_confirm_enabled", True)):
        return False
    ik = option_instrument_key(snap, strike, side)
    if not ik:
        return False
    read = get_cvd(
        str(ik),
        window_seconds=float(getattr(settings, "cvd_window_seconds", 90.0) or 90.0),
        min_recent_qty=float(getattr(settings, "cvd_min_recent_qty", 0.0) or 0.0),
    )
    return read is not None and read.direction == "BUYING"


def option_cvd_acceleration_read(snap: Any, strike: Any, side: Any) -> Any:
    """Return short-window option CVD acceleration, or None when unavailable."""
    from app.config import get_settings
    from app.services.cvd_store import get_cvd_acceleration

    settings = get_settings()
    if not bool(getattr(settings, "cvd_acceleration_enabled", True)):
        return None
    ik = option_instrument_key(snap, strike, side)
    if not ik:
        return None
    return get_cvd_acceleration(
        str(ik),
        slice_seconds=float(
            getattr(settings, "cvd_acceleration_slice_seconds", 15.0) or 15.0
        ),
        min_samples_per_slice=int(
            getattr(settings, "cvd_acceleration_min_samples_per_slice", 2) or 2
        ),
        min_delta_qty_per_second=float(
            getattr(
                settings,
                "cvd_acceleration_min_delta_qty_per_second",
                0.25,
            )
            or 0.25
        ),
    )


def option_cvd_acceleration_confirms_buying(
    snap: Any,
    strike: Any,
    side: Any,
) -> bool:
    """True only when option buying CVD is accelerating on sufficiently dense ticks."""
    read = option_cvd_acceleration_read(snap, strike, side)
    return read is not None and read.direction == "BUYING_ACCELERATING"


def build_entry_confluence(snap: Any, event: Any) -> dict[str, Any]:
    """One unified record of every confirmation signal for the side at entry, + a count.

    Stamped on each trade so winners vs losers can be correlated to which signals fired
    (squeeze at base, ADX trend, VWAP reclaim, Supertrend, option CVD buying, live turn) —
    the data needed to tune the scattered rank bonuses instead of guessing. Read-only.
    """
    side = getattr(event, "side", "")
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    target = "BULLISH" if side_v == "CALL" else "BEARISH" if side_v == "PUT" else ""
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    sq = (getattr(ca, "squeeze", None) or {}) if ca is not None else {}
    adx = (getattr(ca, "adx", None) or {}) if ca is not None else {}
    vw = (getattr(ca, "vwap", None) or {}) if ca is not None else {}
    st = (getattr(ca, "supertrend", None) or {}) if ca is not None else {}

    squeeze_ok = index_squeeze_confirms_side(side, snap)
    adx_ok = index_adx_rank_adjust(side, snap) > 0
    vwap_ok = index_vwap_confirms_side(side, snap)
    cvd_ok = option_cvd_confirms_buying(snap, getattr(event, "strike", None), side)
    cvd_acceleration = option_cvd_acceleration_read(
        snap, getattr(event, "strike", None), side,
    )
    cvd_acceleration_ok = bool(
        cvd_acceleration is not None
        and cvd_acceleration.direction == "BUYING_ACCELERATING"
    )
    st_ok = bool(target) and str(st.get("direction") or "").upper() == target
    try:
        from app.engines.local_base_chart_bypass import local_base_momentum_turn

        turn_ok = bool(local_base_momentum_turn(side, snap, event=event))
    except Exception:
        turn_ok = False

    score = int(
        sum([
            squeeze_ok,
            adx_ok,
            vwap_ok,
            cvd_ok,
            cvd_acceleration_ok,
            st_ok,
            turn_ok,
        ])
    )
    return {
        "score": score,
        "squeeze": {
            "state": sq.get("state"),
            "direction": sq.get("direction"),
            "aligned": bool(squeeze_ok),
        },
        "adx": {
            "adx": adx.get("adx"),
            "regime": adx.get("regime"),
            "direction": adx.get("direction"),
            "aligned": bool(adx_ok),
        },
        "vwap": {
            "position": vw.get("position"),
            "reclaim": vw.get("reclaim"),
            "aligned": bool(vwap_ok),
        },
        "supertrend": {"direction": st.get("direction"), "aligned": bool(st_ok)},
        "cvd": {"aligned": bool(cvd_ok)},
        "cvdAcceleration": {
            "aligned": cvd_acceleration_ok,
            "direction": (
                cvd_acceleration.direction if cvd_acceleration is not None else "UNAVAILABLE"
            ),
            "currentRate": (
                cvd_acceleration.current_rate if cvd_acceleration is not None else None
            ),
            "previousRate": (
                cvd_acceleration.previous_rate if cvd_acceleration is not None else None
            ),
            "acceleration": (
                cvd_acceleration.acceleration if cvd_acceleration is not None else None
            ),
            "currentSamples": (
                cvd_acceleration.current_samples if cvd_acceleration is not None else 0
            ),
            "previousSamples": (
                cvd_acceleration.previous_samples if cvd_acceleration is not None else 0
            ),
        },
        "turn": {"aligned": bool(turn_ok)},
    }


def squeeze_early_base_active(event: Any, snap: Any) -> bool:
    """True when a top-tier explosion has a fresh index-squeeze release toward its side —
    the caller uses this to let it enter closer to the local base (catch it at the base)."""
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "explosion_squeeze_early_base_enabled", True)):
        return False
    tier = str(getattr(event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    return index_squeeze_confirms_side(getattr(event, "side", ""), snap)


def _sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    p = min(period, len(values))
    return sum(values[-p:]) / p


def _stdev(values: list[float], period: int) -> float:
    if len(values) < 2:
        return 0.0
    p = min(period, len(values))
    window = values[-p:]
    mean = sum(window) / p
    var = sum((v - mean) ** 2 for v in window) / p
    return math.sqrt(var) if var > 0 else 0.0


def _atr_series(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float]:
    """Wilder ATR at each bar (index aligned to closes; [0] = 0)."""
    n = min(len(highs), len(lows), len(closes))
    if n < 2:
        return [0.0] * n
    trs = [0.0]
    for i in range(1, n):
        h, l, pc = float(highs[i]), float(lows[i]), float(closes[i - 1])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [0.0] * n
    if n <= period:
        # not enough for Wilder seed — use running mean
        run = 0.0
        for i in range(1, n):
            run = (run * (i - 1) + trs[i]) / i
            out[i] = run
        return out
    seed = sum(trs[1 : period + 1]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    for i in range(1, period):
        out[i] = sum(trs[1 : i + 1]) / i
    return out


def _linreg_last(values: list[float]) -> float:
    """Endpoint value of a least-squares line through ``values`` (TTM momentum)."""
    n = len(values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(values[0])
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom <= 1e-12:
        return float(values[-1])
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
    intercept = mean_y - slope * mean_x
    return slope * (n - 1) + intercept


def compute_bollinger(closes: list[float], period: int = 20, mult: float = 2.0) -> BollingerRead:
    if not closes:
        return BollingerRead()
    mid = _sma(closes, period)
    sd = _stdev(closes, period)
    upper = mid + mult * sd
    lower = mid - mult * sd
    bw = ((upper - lower) / mid * 100.0) if mid else 0.0
    return BollingerRead(round(upper, 2), round(mid, 2), round(lower, 2), round(bw, 3))


def compute_keltner(
    highs: list[float], lows: list[float], closes: list[float],
    period: int = 20, mult: float = 1.5,
) -> KeltnerRead:
    if not closes:
        return KeltnerRead()
    ema = _ema_series(closes, period)
    mid = ema[-1] if ema else closes[-1]
    atr = _atr_series(highs, lows, closes, period)
    a = atr[-1] if atr else 0.0
    return KeltnerRead(round(mid + mult * a, 2), round(mid, 2), round(mid - mult * a, 2))


def _squeeze_on_at(
    highs: list[float], lows: list[float], closes: list[float], end: int,
    period: int, bb_mult: float, kc_mult: float,
) -> bool:
    sl_c = closes[: end + 1]
    sl_h = highs[: end + 1]
    sl_l = lows[: end + 1]
    if len(sl_c) < period:
        return False
    bb = compute_bollinger(sl_c, period, bb_mult)
    kc = compute_keltner(sl_h, sl_l, sl_c, period, kc_mult)
    return bb.upper < kc.upper and bb.lower > kc.lower


def compute_squeeze(
    highs: list[float], lows: list[float], closes: list[float],
    period: int = 20, bb_mult: float = 2.0, kc_mult: float = 1.5,
) -> SqueezeRead:
    """TTM-style squeeze: Bollinger inside Keltner = compression; release = explosion."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return SqueezeRead()
    highs = [float(x) for x in highs[:n]]
    lows = [float(x) for x in lows[:n]]
    closes = [float(x) for x in closes[:n]]
    on_now = _squeeze_on_at(highs, lows, closes, n - 1, period, bb_mult, kc_mult)
    bars_on = 0
    bars_since_fired = -1
    if on_now:
        i = n - 1
        while i >= period and _squeeze_on_at(highs, lows, closes, i, period, bb_mult, kc_mult):
            bars_on += 1
            i -= 1
    else:
        # count trailing OFF bars, then the coil that preceded the release (if any)
        off_run = 0
        i = n - 1
        while i >= period and not _squeeze_on_at(highs, lows, closes, i, period, bb_mult, kc_mult):
            off_run += 1
            i -= 1
        if i >= period:  # an ON coil released off_run bars ago
            bars_since_fired = off_run - 1
            j = i
            while j >= period and _squeeze_on_at(highs, lows, closes, j, period, bb_mult, kc_mult):
                bars_on += 1
                j -= 1

    # Regression momentum on de-trended price (TTM): close - avg(mid-donchian, sma)
    p = min(period, n)
    hh = max(highs[-p:])
    ll = min(lows[-p:])
    donch_mid = (hh + ll) / 2.0
    sma_c = _sma(closes, p)
    baseline = (donch_mid + sma_c) / 2.0
    detr = [closes[i] - baseline for i in range(n - p, n)]
    momentum = _linreg_last(detr)

    fired = bars_since_fired == 0
    if momentum > 0:
        direction = "BULLISH"
    elif momentum < 0:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    if on_now:
        state = "SQUEEZE"
    elif fired:
        state = "FIRED"
    else:
        state = "OFF"
    return SqueezeRead(
        on=on_now, fired=fired, bars_on=bars_on, bars_since_fired=bars_since_fired,
        momentum=round(momentum, 4), direction=direction, state=state,
    )


def compute_adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14,
    trend_min: float = 25.0, chop_max: float = 20.0,
) -> AdxRead:
    """Wilder ADX with +DI/-DI and a trend/chop regime label."""
    n = min(len(highs), len(lows), len(closes))
    if n < period * 2:
        return AdxRead()
    highs = [float(x) for x in highs[:n]]
    lows = [float(x) for x in lows[:n]]
    closes = [float(x) for x in closes[:n]]
    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    trs: list[float] = [0.0]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))

    def _wilder_smooth(vals: list[float]) -> list[float]:
        out = [0.0] * len(vals)
        if len(vals) <= period:
            return out
        seed = sum(vals[1 : period + 1])
        out[period] = seed
        for i in range(period + 1, len(vals)):
            out[i] = out[i - 1] - (out[i - 1] / period) + vals[i]
        return out

    sm_tr = _wilder_smooth(trs)
    sm_plus = _wilder_smooth(plus_dm)
    sm_minus = _wilder_smooth(minus_dm)

    dxs: list[float] = []
    for i in range(period, n):
        tr = sm_tr[i] or 1e-9
        pdi = 100.0 * sm_plus[i] / tr
        mdi = 100.0 * sm_minus[i] / tr
        denom = (pdi + mdi) or 1e-9
        dxs.append(100.0 * abs(pdi - mdi) / denom)

    if len(dxs) < period:
        return AdxRead()
    adx = sum(dxs[:period]) / period
    for i in range(period, len(dxs)):
        adx = (adx * (period - 1) + dxs[i]) / period

    tr_last = sm_tr[-1] or 1e-9
    plus_di = 100.0 * sm_plus[-1] / tr_last
    minus_di = 100.0 * sm_minus[-1] / tr_last
    if adx >= trend_min:
        regime = "TREND"
    elif adx <= chop_max:
        regime = "CHOP"
    else:
        regime = "TRANSITION"
    if plus_di > minus_di:
        direction = "BULLISH"
    elif minus_di > plus_di:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    return AdxRead(
        adx=round(adx, 2), plus_di=round(plus_di, 2), minus_di=round(minus_di, 2),
        regime=regime, direction=direction,
    )


def compute_supertrend(
    highs: list[float], lows: list[float], closes: list[float],
    period: int = 10, mult: float = 3.0,
) -> SupertrendRead:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return SupertrendRead()
    highs = [float(x) for x in highs[:n]]
    lows = [float(x) for x in lows[:n]]
    closes = [float(x) for x in closes[:n]]
    atr = _atr_series(highs, lows, closes, period)
    final_upper = [0.0] * n
    final_lower = [0.0] * n
    st = [0.0] * n
    dir_up = [True] * n  # True = bullish (close above supertrend)
    for i in range(n):
        hl2 = (highs[i] + lows[i]) / 2.0
        bu = hl2 + mult * atr[i]
        bl = hl2 - mult * atr[i]
        if i == 0:
            final_upper[i] = bu
            final_lower[i] = bl
            st[i] = bu
            dir_up[i] = True
            continue
        final_upper[i] = bu if (bu < final_upper[i - 1] or closes[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        final_lower[i] = bl if (bl > final_lower[i - 1] or closes[i - 1] < final_lower[i - 1]) else final_lower[i - 1]
        if closes[i] > final_upper[i - 1]:
            dir_up[i] = True
        elif closes[i] < final_lower[i - 1]:
            dir_up[i] = False
        else:
            dir_up[i] = dir_up[i - 1]
        st[i] = final_lower[i] if dir_up[i] else final_upper[i]
    direction = "BULLISH" if dir_up[-1] else "BEARISH"
    flipped = n >= 2 and dir_up[-1] != dir_up[-2]
    return SupertrendRead(value=round(st[-1], 2), direction=direction, flipped=flipped)


def compute_decisive_candle(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float],
    *,
    body_ratio_min: float = 0.6,
    rsi_period: int = 14,
    rsi_ceiling: float = 80.0,
    pullback_lookback: int = 5,
) -> DecisiveCandleRead:
    """GainzAlgo V2 Alpha-style decisive reversal bar on the latest CLOSED candle.

    Bullish: bullish engulfing + strong body (body/range >= body_ratio_min) + RSI below the
    ceiling (not exhausted) + price came DOWN over the last ``pullback_lookback`` bars (a real
    turn, not continuation). Bearish is the mirror. Non-repainting: uses the last closed bar.
    """
    n = min(len(opens), len(highs), len(lows), len(closes))
    if n < max(pullback_lookback + 1, rsi_period + 2):
        return DecisiveCandleRead()
    o = [float(x) for x in opens[:n]]
    h = [float(x) for x in highs[:n]]
    low = [float(x) for x in lows[:n]]
    c = [float(x) for x in closes[:n]]

    rng = max(1e-9, h[-1] - low[-1])
    body_ratio = abs(c[-1] - o[-1]) / rng
    decisive_body = body_ratio >= body_ratio_min
    rsi = compute_rsi(c, rsi_period).value

    bull_engulf = c[-2] < o[-2] and c[-1] > o[-1] and c[-1] > o[-2]
    bear_engulf = c[-2] > o[-2] and c[-1] < o[-1] and c[-1] < o[-2]
    came_down = c[-1] < c[-1 - pullback_lookback]
    came_up = c[-1] > c[-1 - pullback_lookback]

    bull = bull_engulf and decisive_body and rsi < rsi_ceiling and came_down
    bear = bear_engulf and decisive_body and rsi > (100.0 - rsi_ceiling) and came_up

    if bull:
        direction, after_pullback, engulfing = "BULLISH", came_down, True
    elif bear:
        direction, after_pullback, engulfing = "BEARISH", came_up, True
    else:
        direction = "NEUTRAL"
        after_pullback = came_down or came_up
        engulfing = bull_engulf or bear_engulf
    return DecisiveCandleRead(
        direction=direction,
        decisive=bool(bull or bear),
        body_ratio=round(body_ratio, 3),
        engulfing=engulfing,
        after_pullback=after_pullback,
        rsi=round(rsi, 2),
    )


def index_decisive_breakout_confirms_side(side: Any, snap: Any) -> bool:
    """True when the index printed a decisive reversal bar toward the option side.

    Reads the pre-computed chartAnalysis.decisiveCandle dict (no recompute). Additive only —
    a coil-predictor direction vote / rank input, never a hard gate.
    """
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "decisive_candle_enabled", True)):
        return False
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    dc = getattr(ca, "decisiveCandle", None) if ca is not None else None
    if not isinstance(dc, dict) or not dc:
        return False
    if not bool(dc.get("decisive")):
        return False
    direction = str(dc.get("direction") or "NEUTRAL").upper()
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    if side_v == "CALL":
        return direction == "BULLISH"
    if side_v == "PUT":
        return direction == "BEARISH"
    return False


def _bucket_ohlc(
    series: list[tuple[float, float]], *, bucket_seconds: float
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Bucket a (epoch, value) series into OHLC bars of ``bucket_seconds``."""
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    if not series:
        return opens, highs, lows, closes
    cur_bucket = None
    o = h = low = c = 0.0
    for ts, v in series:
        b = int(ts // bucket_seconds)
        if cur_bucket is None:
            cur_bucket = b
            o = h = low = c = v
        elif b != cur_bucket:
            opens.append(o); highs.append(h); lows.append(low); closes.append(c)
            cur_bucket = b
            o = h = low = c = v
        else:
            h = max(h, v); low = min(low, v); c = v
    opens.append(o); highs.append(h); lows.append(low); closes.append(c)
    return opens, highs, lows, closes


def option_decisive_breakout_confirms(
    symbol: Any, strike: Any, side: Any, *, settings: Any = None,
) -> bool:
    """GainzAlgo V2 Alpha on the OPTION premium — a decisive breakout bar off the base.

    The index-level decisive candle barely registers a huge option rip (₹15->100 is a small %
    on the index). Bucketing the contract's own premium tape into OHLC and running the same
    strong-bodied-engulfing-after-pullback detector gives a real "the option just broke
    decisively" confirmation. We always BUY the option, so a BULLISH decisive bar on the
    premium confirms the break for either CE or PE. Additive — a coil-predictor vote, not a gate.
    """
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "option_decisive_breakout_enabled", True)):
        return False
    try:
        from app.engines.explosion_detector import option_premium_series
    except Exception:
        return False
    lookback = float(
        getattr(settings, "option_decisive_breakout_lookback_seconds", 900.0) or 900.0
    )
    bucket = float(
        getattr(settings, "option_decisive_breakout_bucket_seconds", 30.0) or 30.0
    )
    try:
        series = option_premium_series(
            str(symbol or ""), float(strike or 0), side, lookback_seconds=lookback
        )
    except Exception:
        return False
    opens, highs, lows, closes = _bucket_ohlc(series, bucket_seconds=bucket)
    read = compute_decisive_candle(
        opens, highs, lows, closes,
        body_ratio_min=float(
            getattr(settings, "decisive_candle_body_ratio_min", 0.6) or 0.6
        ),
        rsi_ceiling=float(getattr(settings, "decisive_candle_rsi_ceiling", 80.0) or 80.0),
        pullback_lookback=int(
            getattr(settings, "decisive_candle_pullback_lookback", 5) or 5
        ),
    )
    # Premium rises for the side we buy → a BULLISH decisive bar on the premium = the break.
    return bool(read.decisive and read.direction == "BULLISH")


def compute_vwap(
    highs: list[float], lows: list[float], closes: list[float], volumes: list[float],
    band_mult: float = 1.5,
) -> VwapRead:
    """Session VWAP with std-dev bands + reclaim/loss cross of the latest bar."""
    n = min(len(highs), len(lows), len(closes), len(volumes))
    if n < 2:
        return VwapRead()
    typ = [(float(highs[i]) + float(lows[i]) + float(closes[i])) / 3.0 for i in range(n)]
    vols = [max(0.0, float(volumes[i])) for i in range(n)]
    cum_v = sum(vols)
    volume_weighted = cum_v > 0
    if not volume_weighted:
        # Pure indices carry no candle volume — fall back to a price-anchored session mean.
        # The reclaim/position signal (price crossing the session reference) still holds.
        vwap = sum(typ) / n
        var = sum((t - vwap) ** 2 for t in typ) / n
    else:
        vwap = sum(t * v for t, v in zip(typ, vols)) / cum_v
        var = sum(v * (t - vwap) ** 2 for t, v in zip(typ, vols)) / cum_v
    sd = math.sqrt(var) if var > 0 else 0.0
    upper = vwap + band_mult * sd
    lower = vwap - band_mult * sd
    c_now = float(closes[-1])
    c_prev = float(closes[-2])
    if c_now > vwap * 1.0002:
        position = "ABOVE"
    elif c_now < vwap * 0.9998:
        position = "BELOW"
    else:
        position = "AT"
    reclaim = "NONE"
    if c_prev <= vwap and c_now > vwap * 1.0002:
        reclaim = "BULLISH_RECLAIM"
    elif c_prev >= vwap and c_now < vwap * 0.9998:
        reclaim = "BEARISH_LOSS"
    return VwapRead(
        vwap=round(vwap, 2), upper=round(upper, 2), lower=round(lower, 2),
        position=position, reclaim=reclaim, volume_weighted=volume_weighted,
    )
