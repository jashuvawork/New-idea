"""Block a side when today's index candles are stepping off the local extreme.

On from 09:15 until 09:45 IST. After 09:45 this check is idle and the composite
chart gate stands on its own.

The 5-minute composite can stay bullish while price is already leaving the high.
Oct 23 Nifty 22800 CE filled at 09:28 with a bullish 3-bar chart (+0.15%) and the
open-side tape still above the open, while the index was stepping down off
22,763. Oct 26 Nifty 22350 PE filled at 09:40 on a 5-bar bearish stamp while the
cash tape was already lifting off the low.

A call needs the last few session candles to still be holding the high. A put
needs them still holding the low. First-lift, elite, and premium-rip waivers
do not skip this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side
from app.services.upstox import _candle_ts

IST = ZoneInfo("Asia/Kolkata")
_SESSION_OPEN_MINUTES = 9 * 60 + 15


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _session_rows(candles: list[Any] | None, now: datetime) -> list[Any]:
    today = now.astimezone(IST).date()
    kept: list[Any] = []
    for row in candles or []:
        ts = _candle_ts(row)
        if ts is None:
            continue
        local = ts.astimezone(IST)
        minutes = local.hour * 60 + local.minute
        if local.date() == today and minutes >= _SESSION_OPEN_MINUTES:
            kept.append(row)
    return kept


def cash_session_candles(
    candles: list[Any] | None,
    now: datetime | None = None,
) -> list[Any]:
    """Today's bars from 09:15 IST. A bar with no timestamp is not today's bar."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    return _session_rows(candles, current.astimezone(IST))


def _row_close(row: Any) -> float:
    try:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            return float(row[4] or 0)
        if isinstance(row, dict):
            return float(row.get("close") or row.get("c") or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def prior_close_before_cash_session(
    candles: list[Any] | None,
    now: datetime | None = None,
) -> float:
    """Last close before today's 09:15. Zero when the series has no timestamps."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    current = current.astimezone(IST)
    today = current.date()
    last = 0.0
    for row in candles or []:
        ts = _candle_ts(row)
        if ts is None:
            continue
        local = ts.astimezone(IST)
        minutes = local.hour * 60 + local.minute
        before_cash = local.date() < today or (
            local.date() == today and minutes < _SESSION_OPEN_MINUTES
        )
        if not before_cash:
            continue
        close = _row_close(row)
        if close > 0:
            last = close
    return last


def _ohlc(row: Any) -> tuple[float, float, float, float] | None:
    if isinstance(row, (list, tuple)) and len(row) >= 5:
        o, h, l, c = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
    elif isinstance(row, dict):
        o = float(row.get("open") or 0)
        h = float(row.get("high") or 0)
        l = float(row.get("low") or 0)
        c = float(row.get("close") or 0)
    else:
        return None
    if min(o, h, l, c) <= 0:
        return None
    return o, h, l, c


def _series_rollover(
    rows: list[Any],
    *,
    side: str,
    spot: float,
    steps: int,
    min_giveback_pct: float,
) -> dict[str, Any] | None:
    bars = [bar for bar in (_ohlc(row) for row in rows) if bar is not None]
    if len(bars) < steps or spot <= 0:
        return None
    opens, highs, lows, closes = (list(col) for col in zip(*bars))
    closes[-1] = spot
    highs[-1] = max(highs[-1], spot)
    lows[-1] = min(lows[-1], spot)
    window = max(steps + 3, 6)
    recent_high = max(highs[-window:])
    recent_low = min(lows[-window:])
    tail = closes[-steps:]
    falling = all(tail[i] > tail[i + 1] for i in range(steps - 1))
    rising = all(tail[i] < tail[i + 1] for i in range(steps - 1))
    giveback_high = (recent_high - spot) / recent_high * 100.0 if recent_high > 0 else 0.0
    giveback_low = (spot - recent_low) / recent_low * 100.0 if recent_low > 0 else 0.0
    meta = {
        "closes": [round(c, 2) for c in tail],
        "localHigh": round(recent_high, 2),
        "localLow": round(recent_low, 2),
        "spot": round(spot, 2),
        "givebackFromHighPct": round(giveback_high, 3),
        "givebackFromLowPct": round(giveback_low, 3),
    }
    if side == "CALL" and falling and giveback_high >= min_giveback_pct:
        return meta
    if side == "PUT" and rising and giveback_low >= min_giveback_pct:
        return meta
    return None


def _inside_open_window(now: datetime, settings: Any) -> bool:
    """Same window as macro open-side index confirmation (default 09:25–09:45)."""
    from app.engines.open_side_confirmation import open_side_index_confirmation_window_active

    return open_side_index_confirmation_window_active(now, settings)


def cash_candle_side_window_active(
    now: datetime | None = None,
    settings: Any = None,
) -> bool:
    """True from the cash open until 09:45 IST (09:15:00–09:44:59)."""
    settings = settings or get_settings()
    current = (now or datetime.now(IST)).astimezone(IST)
    minutes = current.hour * 60 + current.minute + current.second / 60.0
    end = (
        int(getattr(settings, "open_caution_until_hour", 9) or 9) * 60
        + int(getattr(settings, "open_caution_until_minute", 45) or 45)
    )
    return _SESSION_OPEN_MINUTES <= minutes < end


def open_caution_window_active(
    now: datetime | None = None,
    settings: Any = None,
) -> bool:
    """True during macro open-side confirmation (default 09:25–09:44:59 IST)."""
    settings = settings or get_settings()
    current = (now or datetime.now(IST)).astimezone(IST)
    return _inside_open_window(current, settings)


def index_candle_rollover_blocked(
    side: Side | str,
    candles_1m: list[Any] | None = None,
    candles_5m: list[Any] | None = None,
    *,
    spot: float = 0.0,
    now: Optional[datetime] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, meta). Either 1m or 5m stepping off the extreme blocks.

    Active from 09:15 until 09:45. The same move after 09:45 does not block.
    Callers must run this before first-lift and premium-rip bypasses.
    """
    settings = settings or get_settings()
    if getattr(settings, "index_candle_rollover_block_enabled", True) is not True:
        return False, "", {}
    side_v = _side_val(side)
    if side_v not in ("CALL", "PUT"):
        return False, "", {}
    now = (now or datetime.now(IST)).astimezone(IST)
    if not cash_candle_side_window_active(now, settings):
        return False, "", {}
    steps = int(getattr(settings, "index_candle_rollover_steps", 3) or 3)
    min_giveback = float(
        getattr(settings, "index_candle_rollover_min_giveback_pct", 0.04) or 0.04
    )
    for label, candles in (("1m", candles_1m), ("5m", candles_5m)):
        rows = _session_rows(candles, now)
        hit = _series_rollover(
            rows,
            side=side_v,
            spot=float(spot or 0),
            steps=max(steps, 2),
            min_giveback_pct=min_giveback,
        )
        if hit is None:
            continue
        reason = (
            "index_falling_from_local_high"
            if side_v == "CALL"
            else "index_rising_from_local_low"
        )
        return True, reason, {"timeframe": label, **hit}
    return False, "", {}
