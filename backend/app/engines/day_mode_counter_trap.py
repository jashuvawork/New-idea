"""Day-mode counter-side fade/trap — BEARISH DAY CE chase, BULLISH DAY PE chase (CE/PE symmetric)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.engines.chop_day_guards import resolve_chop_day_mode_from_state
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def counter_day_mode_side(day_mode: str, side: str) -> bool:
    """True when side fights session day bias (BEARISH DAY → CALL, BULLISH DAY → PUT)."""
    dm = str(day_mode or "").strip().upper()
    s = _side_val(side)
    if not dm or s not in ("CALL", "PUT"):
        return False
    if "BEARISH" in dm:
        return s == "CALL"
    if "BULLISH" in dm:
        return s == "PUT"
    return False


def breadth_confirms_day_bias(snap: SymbolSnapshot | None, day_mode: str) -> bool:
    """Breadth aligned with day bias (bearish breadth on BEARISH DAY, etc.)."""
    if snap is None:
        return False
    br = getattr(snap, "breadth", None)
    if br is None:
        return False
    if isinstance(br, dict):
        bias = str(br.get("bias") or "").upper()
        aligned_flag = bool(br.get("aligned"))
    else:
        bias = str(getattr(br, "bias", "") or "").upper()
        aligned_flag = bool(getattr(br, "aligned", False))
    if not aligned_flag or bias not in ("BULLISH", "BEARISH"):
        return False
    dm = str(day_mode or "").strip().upper()
    if "BEARISH" in dm:
        return bias == "BEARISH"
    if "BULLISH" in dm:
        return bias == "BULLISH"
    return False


def day_mode_counter_side_trap_chopish(
    side: Side | str,
    snap: SymbolSnapshot | None,
    state: Any = None,
    *,
    local_pad: float,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Treat counter-day mid-pad chase as chopish for fake-explosion-trap (Nov27 25750 CE).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(
        getattr(settings, "fake_trap_day_mode_counter_side_chopish_enabled", True)
    ):
        return False, meta
    day_mode = resolve_chop_day_mode_from_state(state)
    if not counter_day_mode_side(day_mode, side):
        return False, meta
    if not breadth_confirms_day_bias(snap, day_mode):
        return False, meta
    min_pad = float(
        getattr(settings, "fake_trap_day_mode_counter_side_min_pad_pct", 10.0) or 10.0
    )
    pad = float(local_pad or 0.0)
    if pad < min_pad - 1e-6:
        meta["dayModeCounterSidePadPct"] = round(pad, 2)
        meta["dayModeCounterSideMinPadPct"] = min_pad
        return False, meta
    meta.update({
        "dayMode": day_mode,
        "dayModeCounterSideTrap": True,
        "dayModeCounterSidePadPct": round(pad, 2),
    })
    return True, meta


def counter_day_suppress_exec_fade_waivers(
    side: Side | str,
    snap: SymbolSnapshot | None,
    state: Any = None,
    *,
    local_pad: float,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """When True, do not apply premium-led / index-turn / first-lift fade waivers at execution."""
    settings = settings or get_settings()
    chopish, meta = day_mode_counter_side_trap_chopish(
        side, snap, state, local_pad=local_pad, settings=settings,
    )
    if not chopish:
        return False, meta
    if not bool(
        getattr(settings, "fake_trap_day_mode_counter_side_suppress_fade_waivers", True)
    ):
        return False, meta
    meta["counterDayFadeWaiverSuppress"] = True
    return True, meta


def counter_day_exec_post_spike_red_candle_blocked(
    side: Side | str,
    snap: SymbolSnapshot | None,
    candles: list,
    ltp: float,
    *,
    state: Any = None,
    local_pad: float,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Dead-cat bounce trap on counter-day mid-pad fills (mirror fast_bullish lane, wider scope)."""
    settings = settings or get_settings()
    if not bool(
        getattr(settings, "counter_day_block_post_spike_red_candle_exec", True)
    ):
        return False, "ok", {}
    chopish, meta = day_mode_counter_side_trap_chopish(
        side, snap, state, local_pad=local_pad, settings=settings,
    )
    if not chopish:
        return False, "ok", meta
    from app.engines.premium_spike_dump_guard import premium_chart_spike_dump_read

    min_red = int(
        getattr(settings, "counter_day_post_spike_min_big_red_bars", 1) or 1
    )
    min_dd = float(
        getattr(settings, "counter_day_post_spike_min_drawdown_pct", 8.0) or 8.0
    )
    min_run = float(
        getattr(settings, "counter_day_post_spike_min_spike_run_pct", 20.0) or 20.0
    )
    read = premium_chart_spike_dump_read(
        candles,
        ltp,
        settings=settings,
        min_big_red_bars=min_red,
        ignore_near_low=True,
    )
    read = dict(read)
    run_ok = float(read.get("spikeRunPct") or 0) >= min_run - 1e-6
    dd_ok = float(read.get("drawdownFromHighPct") or 0) <= -min_dd + 1e-6
    big_red_ok = int(read.get("bigRedBars") or 0) >= min_red
    if run_ok and dd_ok and big_red_ok:
        return True, "exec_counter_day_post_spike_red_candle_trap", {**meta, **read}
    return False, "ok", {**meta, **read}