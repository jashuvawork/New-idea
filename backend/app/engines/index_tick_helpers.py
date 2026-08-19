"""Index-level tick helpers — NIFTY/SENSEX spot moves that lift strike premiums.

Strike LTP alone is lagging: sudden BUILDING/ELITE lifts are usually driven by
the *index* ticking (spot spike / squeeze / momentum turn). This module:

  1. Observes index WebSocket ticks (thin — not a second radar).
  2. Scores whether the index move confirms an option side.
  3. Wakes the BUILDING LTP cycle when the index spikes so we re-score helpers.

Aug19 lesson: SENSEX spot ticks + bearish chart/breadth helped 76900 PE lift
from the V-base — premium tape alone was too late.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.services.upstox import INDEX_KEYS

# instrument_key -> symbol
_INDEX_SYMBOL_BY_KEY = {
    str(v).replace(":", "|"): k for k, v in INDEX_KEYS.items()
}

# Per-symbol last spike fingerprint (v3 at spike time).
_last_spike: dict[str, dict[str, Any]] = {}
# Pending wake flags — building_ltp_monitor_due consumes these.
_pending_wake_symbols: set[str] = set()
_observer_registered: bool = False


@dataclass
class IndexTickHelpers:
    """Index-level confirmation board for one symbol + option side."""

    symbol: str = ""
    side: str = ""
    velocity_3s: float = 0.0
    velocity_9s: float = 0.0
    tick_align: bool = False
    tick_spike: bool = False
    mom_align: bool = False
    squeeze_align: bool = False
    breadth_align: bool = False
    helpers: list[str] = field(default_factory=list)
    helper_count: int = 0
    confirming: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reset_index_tick_helpers_for_tests() -> None:
    global _observer_registered
    _last_spike.clear()
    _pending_wake_symbols.clear()
    # Keep observer registered across tests once installed.
    _ = _observer_registered


def ensure_index_tick_observer() -> None:
    """Idempotent: register thin index-tick observer on the WS tape."""
    global _observer_registered
    if _observer_registered:
        return
    settings = get_settings()
    if not bool(getattr(settings, "index_tick_helpers_enabled", True)):
        return
    from app.services.tick_store import on_tick

    on_tick(_on_index_tick)
    _observer_registered = True


def _norm_key(key: str) -> str:
    return str(key or "").replace(":", "|")


def _on_index_tick(instrument_key: str, ltp: float) -> None:
    """Lightweight: only act on NIFTY/SENSEX/BANKNIFTY index keys."""
    symbol = _INDEX_SYMBOL_BY_KEY.get(_norm_key(instrument_key))
    if not symbol:
        return
    settings = get_settings()
    if not bool(getattr(settings, "index_tick_helpers_enabled", True)):
        return
    try:
        from app.services.tick_store import get_velocity_pct

        key = INDEX_KEYS.get(symbol)
        if not key:
            return
        v3 = get_velocity_pct(
            key,
            window_seconds=3.0,
            max_age_seconds=3.0,
            min_span_seconds=0.5,
        )
        v9 = get_velocity_pct(
            key,
            window_seconds=9.0,
            max_age_seconds=5.0,
            min_span_seconds=1.0,
        )
    except Exception:
        return
    if v3 is None:
        return
    spike_abs = float(
        getattr(settings, "index_tick_spike_abs_velocity_3s", 0.035) or 0.035
    )
    if abs(float(v3)) < spike_abs:
        return
    _last_spike[symbol] = {
        "v3": float(v3),
        "v9": float(v9 or 0.0),
        "ltp": float(ltp),
    }
    if bool(getattr(settings, "index_tick_wake_building_cycle", True)):
        _pending_wake_symbols.add(symbol)


def peek_index_spike_wake(
    symbols: Optional[set[str]] = None,
) -> tuple[bool, list[str]]:
    """True when an index spike should wake BUILDING re-score for watched symbols."""
    if not _pending_wake_symbols:
        return False, []
    if symbols is None:
        hit = sorted(_pending_wake_symbols)
        return bool(hit), hit
    hit = sorted(s for s in _pending_wake_symbols if s in symbols)
    return bool(hit), hit


def clear_index_spike_wake(symbols: Optional[set[str]] = None) -> None:
    if symbols is None:
        _pending_wake_symbols.clear()
        return
    for s in list(symbols):
        _pending_wake_symbols.discard(s)


def last_index_spike(symbol: str) -> dict[str, Any]:
    return dict(_last_spike.get(str(symbol).upper()) or {})


def _side_str(side: Any) -> str:
    if hasattr(side, "value"):
        return str(side.value).upper()
    return str(side or "").upper()


def evaluate_index_tick_helpers(
    *,
    snap: Any,
    side: Any,
    alert: Optional[dict[str, Any]] = None,
) -> IndexTickHelpers:
    """Score index-level helpers that typically precede a strike premium lift."""
    settings = get_settings()
    out = IndexTickHelpers()
    if not bool(getattr(settings, "index_tick_helpers_enabled", True)):
        return out

    symbol = str(
        getattr(snap, "symbol", "")
        or (alert or {}).get("symbol")
        or ""
    ).upper()
    side_u = _side_str(side) or _side_str((alert or {}).get("side"))
    out.symbol = symbol
    out.side = side_u
    if not symbol or side_u not in ("CALL", "PUT"):
        return out

    # Live index tape velocity (actual spot move, not strike premium).
    key = INDEX_KEYS.get(symbol)
    if key:
        try:
            from app.services.tick_store import get_velocity_pct

            v3 = get_velocity_pct(
                key,
                window_seconds=3.0,
                max_age_seconds=5.0,
                min_span_seconds=0.5,
            )
            v9 = get_velocity_pct(
                key,
                window_seconds=9.0,
                max_age_seconds=8.0,
                min_span_seconds=1.0,
            )
            if v3 is not None:
                out.velocity_3s = float(v3)
            if v9 is not None:
                out.velocity_9s = float(v9)
        except Exception:
            pass
    # Fall back to last spike stamp if live tape is quiet but we just saw a spike.
    if out.velocity_3s == 0.0:
        spike = last_index_spike(symbol)
        if spike:
            out.velocity_3s = float(spike.get("v3") or 0)
            out.velocity_9s = float(spike.get("v9") or out.velocity_9s)

    min_align = float(
        getattr(settings, "index_tick_align_abs_velocity_3s", 0.02) or 0.02
    )
    spike_abs = float(
        getattr(settings, "index_tick_spike_abs_velocity_3s", 0.035) or 0.035
    )
    if side_u == "CALL":
        out.tick_align = out.velocity_3s >= min_align
        out.tick_spike = out.velocity_3s >= spike_abs
    else:
        out.tick_align = out.velocity_3s <= -min_align
        out.tick_spike = out.velocity_3s <= -spike_abs

    # Chart momentum turn (5 vs 15) — index accelerating into the option side.
    chart = getattr(snap, "spotChart", None) if snap is not None else None
    if chart is not None:
        mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
        mom15 = float(getattr(chart, "momentum15Pct", 0) or 0)
        shift = float(
            getattr(settings, "index_tick_mom_shift_pct", 0.03) or 0.03
        )
        if side_u == "CALL":
            out.mom_align = mom5 >= mom15 + shift and mom5 > 0
        else:
            out.mom_align = mom5 <= mom15 - shift and mom5 < 0
        # Soft: chart already direction-aligned counts as mom helper too.
        if not out.mom_align:
            try:
                from app.engines.spot_direction import side_aligned_with_chart

                if side_aligned_with_chart(side_u, chart):
                    direction = str(getattr(chart, "direction", "") or "").upper()
                    if direction in ("BULLISH", "BEARISH"):
                        out.mom_align = True
            except Exception:
                pass

    # Squeeze release toward the side.
    try:
        from app.engines.advanced_indicators import index_squeeze_confirms_side

        out.squeeze_align = bool(index_squeeze_confirms_side(side_u, snap))
    except Exception:
        out.squeeze_align = False

    # Breadth bias (index constituents / session bias).
    try:
        from app.engines.symbol_cooldown import side_aligned_with_breadth

        bias = str(getattr(getattr(snap, "breadth", None), "bias", "") or "")
        out.breadth_align = bool(side_aligned_with_breadth(side_u, bias))
    except Exception:
        out.breadth_align = False

    helpers: list[str] = []
    if out.tick_spike:
        helpers.append("index_tick_spike")
    elif out.tick_align:
        helpers.append("index_tick_align")
    if out.mom_align:
        helpers.append("index_mom_turn")
    if out.squeeze_align:
        helpers.append("index_squeeze")
    if out.breadth_align:
        helpers.append("index_breadth")

    out.helpers = helpers
    out.helper_count = len(helpers)
    min_needed = int(
        getattr(settings, "index_tick_min_helpers_confirm", 2) or 2
    )
    # Need tape or structure — never breadth alone.
    has_tape = bool({"index_tick_spike", "index_tick_align"} & set(helpers))
    has_structure = bool(
        {"index_mom_turn", "index_squeeze", "index_breadth"} & set(helpers)
    )
    out.confirming = (
        out.helper_count >= min_needed and (has_tape or (has_structure and out.mom_align))
    )
    # Single strong spike + one structure helper is enough (Aug19 shape).
    if out.tick_spike and has_structure:
        out.confirming = True
    return out


def stamp_index_tick_helpers(
    alert: dict[str, Any],
    helpers: IndexTickHelpers,
) -> dict[str, Any]:
    """Attach index helper board onto live alert for FTV / UI / archive replay."""
    out = dict(alert)
    out["indexSpotMove3s"] = round(helpers.velocity_3s, 4)
    out["indexSpotMove9s"] = round(helpers.velocity_9s, 4)
    out["indexTickAlign"] = bool(helpers.tick_align)
    out["indexTickSpike"] = bool(helpers.tick_spike)
    out["indexMomAlign"] = bool(helpers.mom_align)
    out["indexSqueezeAlign"] = bool(helpers.squeeze_align)
    out["indexHelpers"] = list(helpers.helpers)
    out["indexHelperCount"] = int(helpers.helper_count)
    out["indexHelpersConfirm"] = bool(helpers.confirming)
    return out


def index_helpers_confirm_from_alert(alert: Optional[dict[str, Any]]) -> bool:
    if not isinstance(alert, dict):
        return False
    if bool(alert.get("indexHelpersConfirm")):
        return True
    helpers = alert.get("indexHelpers") or []
    if isinstance(helpers, list) and len(helpers) >= 2:
        return "index_tick_spike" in helpers or "index_tick_align" in helpers
    return False
