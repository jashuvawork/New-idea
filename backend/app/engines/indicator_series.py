"""Pick OHLC series per job — session vs prior-session warmup (676-style parity)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.engines.spot_direction import _candle_rows, _patch_live_close


def extended_5m_candles(
    candles_1m: list[Any] | None,
    candles_5m: list[Any] | None,
    *,
    timeframe_minutes: int | None = None,
) -> list[Any]:
    """Longest 5m series: resampled 1m seed (prior session) vs native intraday 5m."""
    settings = get_settings()
    tf = int(
        timeframe_minutes
        or getattr(settings, "spot_chart_timeframe_minutes", 5)
        or 5
    )
    native = list(candles_5m or [])
    ext: list[Any] = []
    if candles_1m:
        from app.engines.mtf_chart_analysis import resample_candles

        ext = resample_candles(candles_1m, tf)
    if len(ext) >= len(native):
        return ext
    return native


def session_5m_candles(
    candles_1m: list[Any] | None,
    candles_5m: list[Any] | None,
) -> list[Any]:
    """Today's intraday 5m for momentum / recentCloses — never yesterday's warmup bars."""
    native = list(candles_5m or [])
    if native:
        return native
    if not candles_1m:
        return []
    settings = get_settings()
    tf = int(getattr(settings, "spot_chart_timeframe_minutes", 5) or 5)
    from app.engines.index_candle_rollover import cash_session_candles
    from app.engines.mtf_chart_analysis import resample_candles

    session_1m = cash_session_candles(candles_1m)
    return resample_candles(session_1m, tf) if session_1m else []


def warmup_ohlc(
    candles_1m: list[Any] | None,
    candles_5m: list[Any] | None,
    spot: float,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """OHLC rows for indicators that need full history (Ichimoku, MACD stack, ADX, …)."""
    warmup = extended_5m_candles(candles_1m, candles_5m)
    o, h, l, c = _candle_rows(warmup)
    if not c or spot <= 0:
        return o, h, l, c
    c = _patch_live_close(c, spot)
    if h:
        h = list(h)
        h[-1] = max(h[-1], spot)
    if l:
        l = list(l)
        l[-1] = min(l[-1], spot)
    return o, h, l, c


def session_ohlc(
    candles_1m: list[Any] | None,
    candles_5m: list[Any] | None,
    spot: float,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """OHLC for session-scoped reads (decisive candle, short momentum context)."""
    session = session_5m_candles(candles_1m, candles_5m)
    o, h, l, c = _candle_rows(session)
    if not c or spot <= 0:
        return o, h, l, c
    c = _patch_live_close(c, spot)
    if h:
        h = list(h)
        h[-1] = max(h[-1], spot)
    if l:
        l = list(l)
        l[-1] = min(l[-1], spot)
    return o, h, l, c


def mtf_1m_bar_count(settings: Any | None = None) -> int:
    """1m depth for MTF — at least spot-chart warmup so each TF MACD can settle."""
    settings = settings or get_settings()
    warmup = int(
        getattr(settings, "spot_chart_indicator_warmup_1m_bars", 400) or 400
    )
    base = int(getattr(settings, "execution_mtf_1m_bars", 300) or 300)
    return max(base, warmup)
