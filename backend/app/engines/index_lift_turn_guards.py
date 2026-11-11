"""Hard blocks for counter-trend entries during index V-reversal turns.

When spot is rallying off the session low (visible CE lift), new PUT entries are blocked
at a lower point threshold than full index_rally_side_flip unlock. Mirror: slide off
session high blocks CALL.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot
from app.engines.index_rally_side_flip import index_rally_metrics


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _block_put_min_pts(symbol: str, settings: Any) -> float:
    sym = symbol.upper()
    if sym == "NIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_put_min_pts_nifty", 35.0) or 35.0
        )
    if sym == "BANKNIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_put_min_pts_banknifty", 60.0) or 60.0
        )
    return float(getattr(settings, "index_lift_turn_block_put_min_pts", 70.0) or 70.0)


def _block_call_min_pts(symbol: str, settings: Any) -> float:
    sym = symbol.upper()
    if sym == "NIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_call_min_pts_nifty", 35.0) or 35.0
        )
    if sym == "BANKNIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_call_min_pts_banknifty", 60.0) or 60.0
        )
    return float(getattr(settings, "index_lift_turn_block_call_min_pts", 70.0) or 70.0)


def index_session_rally_turn_active(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """Spot has lifted meaningfully off today's low — CE lift regime."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_lift_turn_block_put_enabled", True)):
        return False, {}
    sym = str(symbol or "").upper()
    allowed = {
        s.strip().upper()
        for s in str(
            getattr(settings, "index_lift_turn_symbols_csv", "SENSEX,NIFTY,BANKNIFTY") or ""
        ).split(",")
        if s.strip()
    }
    if allowed and sym not in allowed:
        return False, {}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    rally_pts = float(metrics.get("rallyPoints") or 0)
    min_pts = _block_put_min_pts(sym, settings)
    if rally_pts < min_pts:
        return False, {**metrics, "rallyPoints": rally_pts, "minPts": min_pts}

    chart = snap.spotChart
    if chart is None:
        return False, metrics

    min_mom5 = float(getattr(settings, "index_lift_turn_min_mom5_pct", 0.02) or 0.02)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)

    # Index 5m actively falling — PE allowed even if still far above session low.
    if mom5 <= -min_mom5:
        return False, {
            **metrics,
            "rallyPoints": rally_pts,
            "mom5": mom5,
            "waiver": "index_mom5_bearish_put_ok",
        }

    from app.engines.spot_direction import index_trough_momentum_turn

    trough_turn = index_trough_momentum_turn(Side.CALL, chart, settings=settings)
    mom_ok = mom5 >= min_mom5
    if not mom_ok and not trough_turn:
        return False, {**metrics, "mom5": mom5, "troughTurn": trough_turn}

    return True, {
        **metrics,
        "rallyPoints": rally_pts,
        "minPts": min_pts,
        "mom5": mom5,
        "troughTurn": trough_turn,
        "mode": "index_session_rally_turn",
    }


def index_session_slide_turn_active(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """Spot has slid meaningfully off today's high — PE slide regime."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_lift_turn_block_call_enabled", True)):
        return False, {}
    sym = str(symbol or "").upper()
    allowed = {
        s.strip().upper()
        for s in str(
            getattr(settings, "index_lift_turn_symbols_csv", "SENSEX,NIFTY,BANKNIFTY") or ""
        ).split(",")
        if s.strip()
    }
    if allowed and sym not in allowed:
        return False, {}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    slide_pts = float(metrics.get("slidePoints") or 0)
    min_pts = _block_call_min_pts(sym, settings)
    if slide_pts < min_pts:
        return False, {**metrics, "slidePoints": slide_pts, "minPts": min_pts}

    chart = snap.spotChart
    if chart is None:
        return False, metrics

    min_mom5 = float(getattr(settings, "index_lift_turn_min_mom5_pct", 0.02) or 0.02)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)

    from app.engines.spot_direction import index_trough_momentum_turn

    peak_turn = index_trough_momentum_turn(Side.PUT, chart, settings=settings)
    mom_ok = mom5 <= -min_mom5
    if not mom_ok and not peak_turn:
        return False, {**metrics, "mom5": mom5, "peakTurn": peak_turn}

    if mom5 >= min_mom5:
        return False, {
            **metrics,
            "slidePoints": slide_pts,
            "mom5": mom5,
            "waiver": "index_mom5_bullish_call_ok",
        }

    return True, {
        **metrics,
        "slidePoints": slide_pts,
        "minPts": min_pts,
        "mom5": mom5,
        "peakTurn": peak_turn,
        "mode": "index_session_slide_turn",
    }


_PUT_OPTION_RIP_MOMENTS = frozenset({
    "first_lift_local_base",
    "armed_base_launch",
    "mega_rip",
    "flat_then_vertical",
    "v_rip_session_low",
    "ict_base_armed",
})


def _coerce_mapping(obj: Any) -> dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    if isinstance(obj, dict):
        return obj
    return {}


def index_lift_turn_option_rip_waiver(
    side: Side | str,
    *,
    explosion_event: Any = None,
    alert: Optional[Mapping[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Allow PE/CALL when the option book is ripping even if index turn guard is on."""
    settings = settings or get_settings()
    side_v = _side_val(side)
    if not bool(getattr(settings, "index_lift_turn_option_rip_waiver_enabled", True)):
        return False, "", {}
    tier_u = str(getattr(explosion_event, "tier", "") or "").upper()
    alert_d = _coerce_mapping(alert)
    if not tier_u:
        tier_u = str(alert_d.get("tier") or alert_d.get("bestTier") or "").upper()
    allowed_tiers = {
        t.strip().upper()
        for t in str(
            getattr(settings, "index_lift_turn_option_rip_tiers_csv", "ELITE,EXPLODING") or ""
        ).split(",")
        if t.strip()
    }
    if tier_u not in allowed_tiers:
        return False, "", {}

    v3 = float(
        getattr(explosion_event, "velocity_3s", 0)
        or alert_d.get("velocity3s")
        or alert_d.get("velocity_3s")
        or 0
    )
    min_v3 = float(getattr(settings, "index_lift_turn_option_rip_min_velocity_3s", 1.2) or 1.2)
    if v3 < min_v3:
        return False, "", {}

    moment = str(alert_d.get("momentType") or alert_d.get("pattern") or "").lower()
    if moment and moment not in {m.lower() for m in _PUT_OPTION_RIP_MOMENTS}:
        pass  # velocity + tier still enough for live pad rip

    meta = {
        "tier": tier_u,
        "velocity3s": round(v3, 2),
        "momentType": moment or None,
        "waiver": "index_lift_turn_option_rip",
    }
    if side_v == "PUT":
        return True, "index_lift_turn_put_option_rip_waiver", meta
    return True, "index_lift_turn_call_option_rip_waiver", meta


def index_lift_turn_blocks_side(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
    explosion_event: Any = None,
    alert: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, meta) when side fights an active index V-turn."""
    settings = settings or get_settings()
    side_v = _side_val(side)

    rip_ok, rip_reason, rip_meta = index_lift_turn_option_rip_waiver(
        side,
        explosion_event=explosion_event,
        alert=alert,
        settings=settings,
    )
    if rip_ok:
        return False, "ok", {"indexLiftTurnWaiver": rip_meta, "waiverReason": rip_reason}

    if side_v == "PUT":
        active, meta = index_session_rally_turn_active(symbol, snap, settings=settings)
        if active:
            return True, "index_lift_turn_blocks_put", meta
    elif side_v == "CALL":
        active, meta = index_session_slide_turn_active(symbol, snap, settings=settings)
        if active:
            return True, "index_lift_turn_blocks_call", meta
    return False, "ok", {}


def index_turn_exec_premium_fade_waiver_active(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """
  Allow shallow 1m premium-fade exec fills when index V-turn matches entry side.

  PUT: slide off session high (PE slide day). CALL: rally off session low.
  Does not bypass counter-trend entries — only mirrors turn direction.
  """
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_turn_exec_fade_waiver_enabled", True)):
        return False, {}
    sym = str(symbol or getattr(snap, "symbol", "") or "").upper()
    allowed = {
        s.strip().upper()
        for s in str(
            getattr(settings, "index_lift_turn_symbols_csv", "SENSEX,NIFTY,BANKNIFTY") or ""
        ).split(",")
        if s.strip()
    }
    if allowed and sym not in allowed:
        return False, {}
    tier_u = str(getattr(explosion_event, "tier", "") or "").upper()
    allowed_tiers = {
        t.strip().upper()
        for t in str(
            getattr(settings, "index_turn_exec_fade_waiver_tiers_csv", "ELITE,EXPLODING") or ""
        ).split(",")
        if t.strip()
    }
    if tier_u not in allowed_tiers:
        return False, {}
    side_v = _side_val(side)
    if side_v == "PUT":
        active, meta = index_session_slide_turn_active(sym, snap, settings=settings)
        mode = "index_session_slide_turn"
    elif side_v == "CALL":
        active, meta = index_session_rally_turn_active(sym, snap, settings=settings)
        mode = "index_session_rally_turn"
    else:
        return False, {}
    if not active:
        return False, {}
    return True, {**meta, "waiver": "index_turn_exec_fade", "mode": mode, "tier": tier_u}
