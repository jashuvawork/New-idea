"""Block a side when today's index candles are stepping off the local extreme.

The 5-minute composite can stay bullish while price is already leaving the high.
Oct 23 Nifty 22800 CE filled at 09:28 with a bullish 3-bar chart (+0.15%) and the
open-side tape still above the open, while the index was stepping down off
22,763. PR 676 has the same composite chart gate and no candle-by-candle check,
so that fill would have passed there too.

A call needs the last few session candles to stop making lower closes. A put is
the mirror. First-lift and base-call waivers do not skip this.
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
    saw_ts = False
    for row in candles or []:
        ts = _candle_ts(row)
        if ts is None:
            continue
        saw_ts = True
        local = ts.astimezone(IST)
        minutes = local.hour * 60 + local.minute
        if local.date() == today and minutes >= _SESSION_OPEN_MINUTES:
            kept.append(row)
    if not saw_ts:
        return list(candles or [])
    return kept


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


def index_candle_rollover_blocked(
    side: Side | str,
    candles_1m: list[Any] | None = None,
    candles_5m: list[Any] | None = None,
    *,
    spot: float = 0.0,
    now: Optional[datetime] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, meta). Either 1m or 5m stepping off the extreme blocks."""
    settings = settings or get_settings()
    if getattr(settings, "index_candle_rollover_block_enabled", True) is not True:
        return False, "", {}
    side_v = _side_val(side)
    if side_v not in ("CALL", "PUT"):
        return False, "", {}
    now = (now or datetime.now(IST)).astimezone(IST)
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
