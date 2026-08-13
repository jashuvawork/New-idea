"""Cumulative Volume Delta (CVD) from WebSocket ticks — trade authenticity signal.

We don't get an explicit buy/sell aggressor flag, but the ltpc feed gives per-tick
last-traded price + quantity. The tick rule signs each trade's quantity by the price
change (uptick = buyer-initiated, downtick = seller-initiated), and accumulates it into
a running CVD per instrument. Net positive CVD on an option we're buying = real demand
(genuine explosion); flat/negative = a hollow print to fade.

Pure in-memory, lightweight (dict + bounded deque), safe to call on every tick.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _CvdState:
    prev_ltp: float = 0.0
    prev_raw_vol: float = 0.0
    last_sign: int = 0
    cvd: float = 0.0
    window: deque = field(default_factory=lambda: deque(maxlen=4000))  # (mono, signed_qty)


_states: dict[str, _CvdState] = {}
_DEFAULT_WINDOW_SECONDS = 90.0


@dataclass(frozen=True)
class CvdRead:
    cvd: float = 0.0          # session cumulative signed volume
    recent: float = 0.0       # signed volume over the recent window
    direction: str = "NEUTRAL"  # BUYING | SELLING | NEUTRAL
    samples: int = 0


def _norm_key(key: str) -> str:
    return key.replace(":", "|")


def record_cvd_tick(
    instrument_key: str,
    ltp: float,
    volume: float,
    *,
    cumulative: bool = False,
) -> None:
    """Accumulate signed volume for one tick using the tick rule.

    ``cumulative`` = True when ``volume`` is the running total traded (full-feed vtt);
    otherwise it is the per-tick last-traded quantity (ltpc ltq, the default).
    """
    if not instrument_key or ltp is None or ltp <= 0 or volume is None:
        return
    key = _norm_key(instrument_key)
    st = _states.get(key)
    if st is None:
        st = _CvdState(prev_ltp=float(ltp), prev_raw_vol=float(volume))
        _states[key] = st
        return  # need a prior tick to sign the first delta
    if cumulative:
        tq = max(0.0, float(volume) - st.prev_raw_vol)
        st.prev_raw_vol = float(volume)
    else:
        tq = max(0.0, float(volume))
    if ltp > st.prev_ltp:
        sign = 1
    elif ltp < st.prev_ltp:
        sign = -1
    else:
        sign = st.last_sign
    st.prev_ltp = float(ltp)
    st.last_sign = sign
    if tq <= 0 or sign == 0:
        return
    signed = sign * tq
    st.cvd += signed
    st.window.append((time.monotonic(), signed))


def get_cvd(
    instrument_key: str,
    *,
    window_seconds: float = _DEFAULT_WINDOW_SECONDS,
    min_recent_qty: float = 0.0,
) -> Optional[CvdRead]:
    """Recent + session CVD for an instrument. None when unseen."""
    key = _norm_key(instrument_key)
    st = _states.get(key)
    if st is None:
        return None
    cutoff = time.monotonic() - window_seconds
    recent = 0.0
    samples = 0
    for ts, signed in reversed(st.window):
        if ts < cutoff:
            break
        recent += signed
        samples += 1
    if recent > max(min_recent_qty, 0.0):
        direction = "BUYING"
    elif recent < -max(min_recent_qty, 0.0):
        direction = "SELLING"
    else:
        direction = "NEUTRAL"
    return CvdRead(cvd=round(st.cvd, 1), recent=round(recent, 1), direction=direction, samples=samples)


def status() -> dict[str, int]:
    return {"cvdInstruments": len(_states)}


def clear() -> None:
    _states.clear()
