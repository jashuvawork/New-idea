"""Local-base overrides session chart + sibling side/bias blocks.

Gap-down mornings leave spotChart.direction / breadth BEARISH, which
blanket-blocks every CALL. Jul24 NIFTY 23700 CE was EXPLODING ~98 off a ~110
local base and still died on call_vs_bearish_chart /
explosion_call_vs_bearish_breadth / market_opposes_side.

Policy: a confirmed LOCAL PREMIUM BASE lifts session chart, explosion breadth,
market-opposes, directional confirmation, and bad-day/worst-day alignment
gates. Ichimoku agreement is optional confirmation, not a gate.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _ichimoku_dict(snap: Optional[SymbolSnapshot]) -> dict[str, Any]:
    if snap is None:
        return {}
    analysis = getattr(snap, "chartAnalysis", None)
    if analysis is None:
        return {}
    ich = getattr(analysis, "ichimoku", None) or {}
    return ich if isinstance(ich, dict) else {}


def ichimoku_supports_side(side: Side | str, snap: Optional[SymbolSnapshot]) -> bool:
    """True when smart/classic Ichimoku agrees with CALL→bullish or PUT→bearish."""
    settings = get_settings()
    ich = _ichimoku_dict(snap)
    if not ich:
        return False
    side_v = _side_val(side)
    target = "BULLISH" if side_v == "CALL" else "BEARISH"
    smart = str(ich.get("smartBias") or "NEUTRAL").upper()
    cloud = str(ich.get("cloudBias") or "NEUTRAL").upper()
    tk = str(ich.get("tkCross") or "NEUTRAL").upper()
    price_vs = str(ich.get("priceVsCloud") or "").upper()
    chikou = str(ich.get("chikouBias") or "NEUTRAL").upper()
    require_cloud = bool(getattr(settings, "local_base_ichimoku_require_cloud", False))
    if smart == target:
        return True
    if require_cloud:
        if cloud == target:
            return True
        if tk == target and (
            (target == "BULLISH" and price_vs == "ABOVE")
            or (target == "BEARISH" and price_vs == "BELOW")
        ):
            return True
        if chikou == target and cloud == target:
            return True
        return False
    return cloud == target or tk == target or chikou == target


def _alert_session_move(alert: dict[str, Any]) -> float:
    return max(
        float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        float(alert.get("peakMovePct") or 0),
        float(alert.get("ictBaseRelativeMovePct") or 0),
    )


def local_base_entry_window(tier: str = "", volume_surge: float = 0.0) -> tuple[float, float]:
    """Adaptive base-relative entry window (entry_min%, chase_max%) off the local base.

    - ELITE + strong volume → wider ceiling (catch more of the best 100→250 rips).
    - EXPLODING → higher floor (clear the base's ~8% noise band, fewer fakeouts).
    - Otherwise → the base 15–40% window.
    """
    settings = get_settings()
    entry_min = float(getattr(settings, "explosion_local_base_entry_min_move_pct", 15.0) or 15.0)
    chase_max = float(getattr(settings, "explosion_local_base_chase_max_move_pct", 40.0) or 40.0)
    if not getattr(settings, "local_base_adaptive_window_enabled", True):
        return entry_min, chase_max
    tier_u = str(tier or "").upper()
    strong_vol = float(volume_surge or 0) >= float(
        getattr(settings, "local_base_wide_window_min_vol_surge", 3.0) or 3.0
    )
    if tier_u == "ELITE" and strong_vol:
        chase_max = max(
            chase_max,
            float(getattr(settings, "local_base_elite_chase_max_move_pct", 50.0) or 50.0),
        )
    elif tier_u == "EXPLODING":
        entry_min = max(
            entry_min,
            float(getattr(settings, "local_base_exploding_entry_min_move_pct", 20.0) or 20.0),
        )
    return entry_min, chase_max


def _alert_has_local_base(alert: dict[str, Any]) -> bool:
    """Local premium launch pad — ICT structure OR strong early-window explosion."""
    from app.engines.early_radar_pad_capture import alert_has_early_radar_pad_capture

    if alert_has_early_radar_pad_capture(alert):
        return True
    settings = get_settings()
    if alert.get("ictFlatThenVertical") or alert.get("localSwingBase"):
        return True
    if alert.get("ictBreakout") and float(alert.get("ictBaseRelativeMovePct") or 0) > 0:
        return True
    if str(alert.get("ictPattern") or "") in (
        "flat_then_vertical", "early_flat_break", "local_swing_base",
    ):
        return True
    # Base-relative already measured in the tradeable local window (tier/volume-adaptive).
    base_rel = float(alert.get("ictBaseRelativeMovePct") or 0)
    entry_min, local_max = local_base_entry_window(
        str(alert.get("tier") or ""), float(alert.get("volumeSurge") or 0),
    )
    if entry_min <= base_rel <= local_max:
        return True
    # Jul24 23700 CE: EXPLODING/ELITE on radar with early-window move after a
    # gap-down — ICT flags sometimes lag one poll; tier+score+move is enough.
    # Keep this radar fallback ABOVE the entry floor so bare ELITE+15% cannot
    # lift counter-breadth locks without real ICT structure.
    tier = str(alert.get("tier") or "").upper()
    score = float(alert.get("explosionScore") or 0)
    move = _alert_session_move(alert)
    min_score = float(
        getattr(settings, "local_base_chart_bypass_min_score", 38.0) or 38.0
    )
    radar_min = float(
        getattr(settings, "local_base_chart_bypass_radar_min_move_pct", 28.0) or 28.0
    )
    if (
        tier in ("EXPLODING", "ELITE")
        and score >= min_score
        and radar_min <= move <= local_max
    ):
        return True
    if (
        tier == "BUILDING"
        and score >= min_score
        and (
            bool(alert.get("volumeAwaken"))
            or bool(alert.get("ictVolumeAwakening"))
            or float(alert.get("velocity3s") or 0) >= 2.0
        )
        and move >= radar_min * 0.5
        and move <= local_max
    ):
        return True
    return False


def _alert_or_event_local_base(
    *,
    side: Side | str = "",
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """Local premium structure: flat→vertical, swing V-base, or early EXPLODING rip."""
    if isinstance(alert, dict) and _alert_has_local_base(alert):
        return True
    side_v = _side_val(side) if side else ""
    if not side_v and event is not None:
        side_v = _side_val(getattr(event, "side", ""))
    # Scan live radar alerts even when event is absent (directional lock / hard block).
    if snap is not None and side_v:
        strike = float(getattr(event, "strike", 0) or 0) if event is not None else 0.0
        for a in snap.explosionAlerts or []:
            if str(a.get("side") or "").upper() != side_v:
                continue
            if strike and abs(float(a.get("strike") or 0) - strike) > 0.1:
                continue
            if _alert_has_local_base(a):
                return True
    if event is not None:
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            ict = analyze_explosion_event_ict(event, snap)
            if bool(getattr(ict, "flat_then_vertical", False)):
                return True
            if bool(getattr(ict, "local_swing_base", False)):
                return True
            if float(getattr(ict, "base_relative_move_pct", 0) or 0) > 0 and bool(
                getattr(ict, "active", False)
            ):
                return True
        except Exception:
            pass
        # Event-only radar fallback — stricter than entry floor (see alert path).
        settings = get_settings()
        tier = str(getattr(event, "tier", "") or "").upper()
        score = float(getattr(event, "explosion_score", 0) or 0)
        move = max(
            float(getattr(event, "daily_move_pct", 0) or 0),
            float(getattr(event, "peak_move_pct", 0) or 0),
        )
        min_score = float(
            getattr(settings, "local_base_chart_bypass_min_score", 38.0) or 38.0
        )
        radar_min = float(
            getattr(settings, "local_base_chart_bypass_radar_min_move_pct", 28.0) or 28.0
        )
        _, local_max = local_base_entry_window(
            tier, float(getattr(event, "volume_surge", 0) or 0),
        )
        if (
            tier in ("EXPLODING", "ELITE")
            and score >= min_score
            and radar_min <= move <= local_max
        ):
            return True
    return False


def session_chart_conflicts_side(side: Side | str, snap: Optional[SymbolSnapshot]) -> bool:
    chart = getattr(snap, "spotChart", None) if snap is not None else None
    if chart is None:
        return False
    direction = str(getattr(chart, "direction", None) or "NEUTRAL").upper()
    side_v = _side_val(side)
    if side_v == "CALL" and direction == "BEARISH":
        return True
    if side_v == "PUT" and direction == "BULLISH":
        return True
    return False


def _top_tier_score_vol(
    event: Any, alert: Optional[dict[str, Any]]
) -> tuple[str, float, float]:
    """Best-effort (tier, explosion_score, volume_surge) from an event or alert dict."""
    if event is not None:
        tier = str(getattr(event, "tier", "") or "").upper()
        score = float(
            getattr(event, "explosion_score", 0) or getattr(event, "score", 0) or 0
        )
        vol = float(getattr(event, "volume_surge", 0) or 0)
        if tier or score:
            return tier, score, vol
    if isinstance(alert, dict):
        tier = str(alert.get("tier") or "").upper()
        score = float(alert.get("explosionScore") or alert.get("score") or 0)
        vol = float(alert.get("volumeSurge") or alert.get("volume_surge") or 0)
        return tier, score, vol
    return "", 0.0, 0.0


def local_base_momentum_turn(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """True when a high-volume top-tier base rip is a CONFIRMED reversal toward its side.

    Symmetric for CALL and PUT: the counter-breadth turn the book must not miss (Aug13
    SENSEX 77900 CE) — the index 5m momentum is turning toward the option side (5m better
    than 15m by a margin AND 5m no worse than 10m) even before breadth/chart flip. A
    steadily dumping / non-improving index, a low score, or thin volume is NOT a turn.
    """
    settings = get_settings()
    if not bool(getattr(settings, "local_base_turn_bypass_enabled", True)):
        return False
    chart = getattr(snap, "spotChart", None) if snap is not None else None
    if chart is None:
        return False
    tier, score, vol = _top_tier_score_vol(event, alert)
    if tier not in ("ELITE", "EXPLODING"):
        return False
    min_score = float(getattr(settings, "local_base_turn_min_score", 62.0) or 62.0)
    pad_min_score = float(
        getattr(settings, "local_base_turn_pad_min_score", 28.0) or 28.0
    )
    soft_cap = float(
        getattr(settings, "fast_bullish_local_base_soft_min_score", 45.0) or 45.0
    )
    effective_min = min_score
    if score < min_score and score >= pad_min_score and score <= soft_cap:
        effective_min = pad_min_score
    if score < effective_min:
        return False
    if vol < float(getattr(settings, "local_base_turn_min_vol_surge", 2.0) or 2.0):
        return False
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    mom10 = float(getattr(chart, "momentum10Pct", 0) or 0)
    mom15 = float(getattr(chart, "momentum15Pct", 0) or 0)
    min_shift = float(
        getattr(settings, "local_base_turn_min_mom_shift_pct", 0.05) or 0.05
    )
    side_v = _side_val(side)
    if side_v == "CALL":
        # 5m accelerating up vs 15m, and not worse than the 10m step (monotonic-ish turn).
        return mom5 >= mom15 + min_shift and mom5 >= mom10
    if side_v == "PUT":
        return mom5 <= mom15 - min_shift and mom5 <= mom10
    return False


def local_base_structure_active(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """True when a local premium base / early EXPLODING rip is confirmed for side."""
    settings = get_settings()
    if not getattr(settings, "local_base_overrides_session_chart_enabled", True):
        if not getattr(settings, "local_base_ichimoku_chart_bypass_enabled", True):
            return False
    if snap is None:
        return False
    if not _alert_or_event_local_base(side=side, event=event, alert=alert, snap=snap):
        return False
    if getattr(settings, "local_base_chart_bypass_require_ichimoku", False):
        if not ichimoku_supports_side(side, snap):
            return False
    chart = snap.spotChart
    side_v = _side_val(side)
    max_against = float(
        getattr(settings, "local_base_ichimoku_max_adverse_mom5_pct", 0.12) or 0.12
    )
    # Bullish-for-CALL / bearish-for-PUT: tighten the adverse tolerance using LIVE 5-min
    # momentum so a CALL only fires when the index is turning up (not drifting down), and
    # a PUT only when it's turning down. Keeps genuine bounces; rejects counter-drift.
    if getattr(settings, "local_base_require_aligned_live_momentum", True):
        max_against = min(
            max_against,
            float(getattr(settings, "local_base_aligned_momentum_max_adverse_pct", 0.05) or 0.05),
        )
    # Counter-breadth TURN: a confirmed high-volume top-tier reversal toward the side may
    # run slightly ahead of the index — widen the adverse cap (bounded) so the turn is
    # caught, while a steadily dumping / non-improving / low-quality event still fails below.
    if local_base_momentum_turn(side, snap, event=event, alert=alert):
        max_against = max(
            max_against,
            float(
                getattr(settings, "local_base_turn_max_adverse_mom5_pct", 0.12) or 0.12
            ),
        )
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    if side_v == "CALL" and mom5 < -max_against:
        return False
    if side_v == "PUT" and mom5 > max_against:
        return False
    return True


def local_base_overrides_side_bias(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Lift session breadth / market-opposes / directional / bad-day / worst-day
    side blocks when a local premium base is confirmed.

    Same structure gate as chart bypass; gated by local_base_overrides_bearish_breadth
    (name kept for config compat — covers CALL-vs-bearish and PUT-vs-bullish alike).
    """
    settings = get_settings()
    if not getattr(settings, "local_base_overrides_bearish_breadth", True):
        return False
    from app.engines.index_confirmed_local_base import index_confirmed_local_base

    if index_confirmed_local_base(side, snap, alert):
        return True
    return local_base_structure_active(side, snap, event=event, alert=alert)


def local_base_overrides_session_chart(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Lift call_vs_bearish / put_vs_bullish when a local premium base is confirmed.

    Ichimoku is optional. Primary signal = local base / early-window EXPLODING rip.
    """
    if not session_chart_conflicts_side(side, snap):
        return False
    if local_base_structure_active(side, snap, event=event, alert=alert):
        return True
    from app.engines.pad_lane_capture import pad_lane_turnaround_chart_bypass

    return pad_lane_turnaround_chart_bypass(
        side, snap, event=event, alert=alert,
    )


# Backward-compatible names used across the codebase.
def local_base_ichimoku_chart_bypass(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    return local_base_overrides_session_chart(
        side, snap, event=event, alert=alert,
    )


def _top_explosion_bypass_tiers() -> set[str]:
    settings = get_settings()
    raw = str(
        getattr(settings, "top_explosion_local_base_bypass_tiers_csv", "ELITE,EXPLODING")
        or "ELITE,EXPLODING"
    )
    return {t.strip().upper() for t in raw.split(",") if t.strip()}


def is_top_explosion_local_base_bypass(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """A confirmed TOP explosion off a local base — may override advisory stand-asides
    (composer stand-down / opposing bias / worst-day PAUSED halt) on ANY day.

    "Never miss the best base rips" — but bounded so it can't become chop FOMO:
    - explosion mode, tier in top_explosion_local_base_bypass_tiers_csv (ELITE/EXPLODING)
    - explosion score ≥ top_explosion_local_base_bypass_min_score (62)
    - a CONFIRMED local premium base for the side (flat→vertical / early-window rip),
      which also enforces the base-relative early window (15–40%) + the adverse-momentum
      cap (won't fire while the index is dumping hard).
    Scalps, low tiers/scores, late chases, and hard live-dumps do NOT qualify. This is
    the "enter the 100→250 rip at the base" gate.
    """
    settings = get_settings()
    if not getattr(settings, "top_explosion_local_base_bypass_enabled", True):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False

    event = getattr(candidate, "explosion_event", None)
    alert = getattr(candidate, "alert", None)
    alert = alert if isinstance(alert, dict) else {}
    tier = str(
        getattr(candidate, "tier", "")
        or (getattr(event, "tier", "") if event is not None else "")
        or alert.get("tier", "")
        or ""
    ).upper()
    if tier not in _top_explosion_bypass_tiers():
        return False

    score = float(
        getattr(candidate, "confidence", 0)
        or (alert.get("explosionScore") if alert else 0)
        or (getattr(event, "explosion_score", 0) if event is not None else 0)
        or 0
    )
    min_score = float(
        getattr(settings, "top_explosion_local_base_bypass_min_score", 62.0) or 62.0
    )
    if score < min_score:
        return False

    snap = snap if snap is not None else getattr(candidate, "snap", None)
    side = getattr(candidate, "side", "")
    return local_base_structure_active(
        side, snap, event=event, alert=alert or None,
    )


# Backward-compatible alias (ELITE-focused name, now ELITE/EXPLODING via config).
def is_local_base_elite_bypass(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    return is_top_explosion_local_base_bypass(candidate, snap)


def local_base_ichimoku_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """Snap helper — also scans matching explosionAlerts when event is absent."""
    if local_base_overrides_session_chart(
        side, snap, event=explosion_event, alert=alert,
    ):
        return True
    side_v = _side_val(side)
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_v:
            continue
        if local_base_overrides_session_chart(
            side, snap, event=explosion_event, alert=alert,
        ):
            return True
    return False
