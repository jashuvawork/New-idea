"""RSI and MACD indicators for chart analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RsiRead:
    value: float = 50.0
    bias: str = "NEUTRAL"  # OVERBOUGHT | OVERSOLD | NEUTRAL


@dataclass(frozen=True)
class MacdRead:
    line: float = 0.0
    signal: float = 0.0
    histogram: float = 0.0
    bias: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL


def _ema_series(values: list[float], period: int) -> list[float]:
    """Progressive EMA (pandas ewm adjust=False style) — each value used exactly once.

    Prior version seeded with SMA(values[:period]) but then iterated from values[1],
    double-counting the warmup bars and corrupting MACD bias near warmup.
    """
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1)
    out: list[float] = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def compute_rsi(closes: list[float], period: int = 14) -> RsiRead:
    """Wilder RSI from close prices."""
    if len(closes) < period + 1:
        return RsiRead()

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        rsi = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    if rsi >= 70:
        bias = "OVERBOUGHT"
    elif rsi <= 30:
        bias = "OVERSOLD"
    else:
        bias = "NEUTRAL"
    return RsiRead(value=round(rsi, 2), bias=bias)


def compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> MacdRead:
    """MACD line, signal, histogram and bias from close prices."""
    min_bars = slow + signal_period
    if len(closes) < min_bars:
        return MacdRead()

    fast_ema = _ema_series(closes, fast)
    slow_ema = _ema_series(closes, slow)
    offset = len(fast_ema) - len(slow_ema)
    macd_line = [f - s for f, s in zip(fast_ema[offset:], slow_ema)]

    if len(macd_line) < signal_period:
        return MacdRead()

    signal_series = _ema_series(macd_line, signal_period)
    line = macd_line[-1]
    signal = signal_series[-1]
    histogram = line - signal

    if line > signal * 1.0001 and histogram >= 0:
        bias = "BULLISH"
    elif line < signal * 0.9999 and histogram <= 0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return MacdRead(
        line=round(line, 4),
        signal=round(signal, 4),
        histogram=round(histogram, 4),
        bias=bias,
    )
