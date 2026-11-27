"""Identify fresh session bases (trough remount / post-rip pullback coil) — CE/PE.

Sticky ICT armed pads can sit far above the true launch base after a rip. This
module re-bases chase / freshness / armed waivers onto the correct pad.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side


def _side_val(side: Side | str | None) -> str:
    if side is None:
        return ""
    return side.value if isinstance(side, Side) else str(side).upper()


def index_participation_allows_base_side(
    sym: str,
    side: Side | str,
    snap: Any,
    state: Any = None,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Base formation follows index participation: CALL off rally/session-low lift,
    PUT off slide/session-high roll — not counter-leg premium pads.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "new_session_base_require_index_participation", True)):
        return True, "ok", meta
    if snap is None:
        meta["indexBaseFormationSkipped"] = "no_snapshot"
        return True, "ok", meta

    side_u = _side_val(side)
    if side_u not in ("CALL", "PUT"):
        return True, "ok", meta

    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        side_aligns_with_dominant_trend,
    )

    dom, trend_meta = index_session_dominant_trend(sym, snap, state, settings=settings)
    meta["indexDominantTrend"] = dom
    if isinstance(trend_meta, dict):
        meta["indexTrendMetrics"] = trend_meta.get("indexTrendMetrics")
    meta["indexBaseFormationLeg"] = dom

    if dom in ("", "NEUTRAL"):
        return True, "ok", meta

    if side_aligns_with_dominant_trend(side_u, dom):
        meta["indexBaseSideAlign"] = True
        return True, "ok", meta

    from app.engines.index_tick_helpers import index_trend_breakout

    if index_trend_breakout(sym, side_u, snap, settings=settings).get("breakout"):
        meta["indexBaseSideAlign"] = "trend_breakout"
        return True, "ok", meta

    meta["indexBaseSideAlign"] = False
    return False, "index_base_counter_participation", meta


def new_session_base_identify(
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
    *,
    velocity_3s: float = 0.0,
    stale_ict_base: float = 0.0,
    snap: Any = None,
    state: Any = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (identified, kind, meta) when a proper new base is the launch pad."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "new_session_base_identify_enabled", True)):
        return False, "", meta
    sym = str(symbol or "").upper()
    live = float(premium or 0)
    if not sym or strike <= 0 or live <= 0:
        return False, "", meta

    try:
        from app.engines.explosion_detector import (
            get_session_low_premium,
            get_session_peak_premium,
        )
    except Exception:
        return False, "", meta

    sess_low = float(get_session_low_premium(sym, strike, side) or 0)
    sess_peak = float(get_session_peak_premium(sym, strike, side) or 0)
    if sess_low > 0:
        meta["sessionLowPremium"] = round(sess_low, 2)
    if sess_peak > 0:
        meta["sessionPeakPremium"] = round(sess_peak, 2)

    def _finalize(kind: str, payload: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        out = {**meta, **payload}
        allowed, reason, idx_meta = index_participation_allows_base_side(
            sym, side, snap, state, settings=settings,
        )
        out.update(idx_meta)
        if not allowed:
            out["indexBaseFormationBlocked"] = reason
            return False, "", out
        return True, kind, out

    # 1) Session trough base — V-bottom / new pad at session low (not chase-at-session-high).
    if bool(getattr(settings, "new_session_base_session_trough_stamp_enabled", False)) and sess_low > 0:
        trough_max = float(
            getattr(settings, "new_session_base_trough_max_off_low_pct", 14.0) or 14.0
        )
        min_off_peak = float(
            getattr(settings, "new_session_base_trough_min_fall_from_peak_pct", 0.08) or 0.08
        )
        off_low = (live - sess_low) / sess_low * 100.0
        fall_from_peak = (
            (sess_peak - live) / sess_peak if sess_peak > live > 0 else 0.0
        )
        meta["fallFromPeakPct"] = round(fall_from_peak * 100, 1)
        if (
            0.0 <= off_low <= trough_max + 1e-6
            and fall_from_peak >= min_off_peak - 1e-6
        ):
            try:
                from app.engines.explosion_detector import mid_rip_armed_coil

                if not mid_rip_armed_coil(
                    session_low=sess_low,
                    armed_base=sess_low,
                    premium=live,
                    session_peak=sess_peak,
                    settings=settings,
                ):
                    return _finalize(
                        "session_trough",
                        {
                            "effectiveBasePremium": round(sess_low, 2),
                            "offBasePct": round(off_low, 2),
                            "newBaseKind": "session_trough",
                        },
                    )
            except Exception:
                return _finalize(
                    "session_trough",
                    {
                        "effectiveBasePremium": round(sess_low, 2),
                        "offBasePct": round(off_low, 2),
                        "newBaseKind": "session_trough",
                    },
                )

    # 2) Post-rip pullback new base — coil off peak, not stale mid-rip armed.
    min_run = float(
        getattr(settings, "new_session_base_post_rip_min_session_run_pct", 0.30) or 0.30
    )
    min_pullback = float(
        getattr(settings, "new_session_base_post_rip_min_peak_pullback_pct", 0.12) or 0.12
    )
    max_pad = float(
        getattr(settings, "new_session_base_post_rip_max_pad_pct", 18.0) or 18.0
    )
    min_v3 = float(
        getattr(settings, "new_session_base_post_rip_min_velocity_3s", 0.8) or 0.8
    )
    stale_gap = float(
        getattr(settings, "new_session_base_stale_ict_gap_pct", 12.0) or 12.0
    )

    if sess_low > 0 and sess_peak > live > 0:
        session_run = (sess_peak - sess_low) / sess_low
        fall_from_peak = (sess_peak - live) / sess_peak
        meta["sessionRunPct"] = round(session_run * 100, 1)
        meta["fallFromPeakPct"] = round(fall_from_peak * 100, 1)
        if session_run >= min_run and fall_from_peak >= min_pullback - 1e-6:
            from app.engines.ict_breakout_monitor import _detect_recent_window_base

            found, recent_base, base_rel = _detect_recent_window_base(
                symbol=sym,
                strike=float(strike),
                side=side,
                premium=live,
                settings=settings,
            )
            if found and recent_base > 0 and base_rel <= max_pad + 1e-6:
                stale = False
                ref = float(stale_ict_base or 0)
                if ref > recent_base:
                    gap = (ref - recent_base) / recent_base * 100.0
                    stale = gap >= stale_gap - 1e-6
                    meta["staleIctGapPct"] = round(gap, 1)
                elif sess_low > 0 and ref > sess_low:
                    gap = (ref - sess_low) / sess_low * 100.0
                    stale = gap >= stale_gap - 1e-6
                    meta["staleVsTroughGapPct"] = round(gap, 1)
                if stale or ref <= 0:
                    if velocity_3s >= min_v3 or base_rel <= max_pad * 0.6:
                        return _finalize(
                            "post_rip_pullback",
                            {
                                "effectiveBasePremium": round(recent_base, 2),
                                "offBasePct": round(base_rel, 2),
                                "newBaseKind": "post_rip_pullback",
                                "recentWindowBase": True,
                            },
                        )

    return False, "", meta


def stamp_new_session_base_fields(
    row: dict[str, Any],
    *,
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
    velocity_3s: float = 0.0,
    snap: Any = None,
    state: Any = None,
    settings: Any = None,
) -> dict[str, Any]:
    """Merge new-base stamps into a radar / execution alert."""
    out = dict(row)
    stale = float(
        out.get("ictBasePremium")
        or out.get("localBaseBasePremium")
        or out.get("basePremium")
        or 0
    )
    ok, kind, meta = new_session_base_identify(
        symbol,
        strike,
        side,
        premium,
        velocity_3s=velocity_3s,
        stale_ict_base=stale,
        snap=snap,
        state=state,
        settings=settings,
    )
    if not ok:
        return out
    eff = float(meta.get("effectiveBasePremium") or 0)
    out["newSessionBase"] = True
    out["newBaseKind"] = kind
    out["effectiveBasePremium"] = eff
    out["localBaseBasePremium"] = eff
    if kind == "session_trough":
        out["sessionTroughBase"] = True
    elif kind == "post_rip_pullback":
        out["postRipPullbackBase"] = True
    for key in ("sessionLowPremium", "sessionPeakPremium", "offBasePct"):
        if key in meta:
            out[key] = meta[key]
    return out


def resolve_effective_base_premium_inr(
    alert: Mapping[str, Any] | None,
    *,
    symbol: str = "",
    strike: float = 0.0,
    side: Side | str | None = None,
    premium: float = 0.0,
    velocity_3s: float = 0.0,
    fallback: float = 0.0,
    settings: Any = None,
) -> tuple[float, dict[str, Any]]:
    """Prefer identified new base; else alert ICT base; else fallback."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    row = dict(alert) if isinstance(alert, Mapping) else {}
    if row.get("newSessionBase") and float(row.get("effectiveBasePremium") or 0) > 0:
        return float(row["effectiveBasePremium"]), {
            "newBaseKind": row.get("newBaseKind"),
            "fromAlert": True,
        }

    sym = str(row.get("symbol") or symbol or "")
    stk = float(row.get("strike") or strike or 0)
    side_v = _side_val(row.get("side") or side)
    live = float(row.get("premium") or row.get("lastPremium") or premium or 0)
    v3 = float(row.get("velocity3s") or row.get("velocity_3s") or velocity_3s or 0)
    stale = float(
        row.get("ictBasePremium")
        or row.get("localBaseBasePremium")
        or fallback
        or 0
    )
    if sym and stk > 0 and live > 0 and side_v in ("CALL", "PUT"):
        ok, kind, id_meta = new_session_base_identify(
            sym,
            stk,
            side_v,
            live,
            velocity_3s=v3,
            stale_ict_base=stale,
            settings=settings,
        )
        if ok:
            eff = float(id_meta.get("effectiveBasePremium") or 0)
            if eff > 0:
                return eff, {**id_meta, "newBaseKind": kind}

    for key in ("effectiveBasePremium", "localBaseBasePremium", "ictBasePremium", "basePremium"):
        try:
            v = float(row.get(key) or 0)
            if v > 0:
                return v, meta
        except (TypeError, ValueError):
            pass
    return float(fallback or 0), meta


def alert_pad_move_pct(alert: Mapping[str, Any] | None) -> float:
    """Trusted % off effective session base when newSessionBase is stamped."""
    if not isinstance(alert, Mapping):
        return -1.0
    if not alert.get("newSessionBase"):
        return -1.0
    for key in ("localBaseMovePct", "offBasePct", "ictBaseRelativeMovePct"):
        try:
            v = float(alert.get(key) or -1)
            if v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    eff = float(alert.get("effectiveBasePremium") or 0)
    prem = float(alert.get("premium") or alert.get("lastPremium") or 0)
    if eff > 0 and prem > eff:
        return (prem - eff) / eff * 100.0
    return -1.0


def new_session_base_near_miss_waive(
    alert: Mapping[str, Any] | None,
    *,
    settings: Any = None,
) -> bool:
    """BUILDING/ELITE at a freshly identified trough/pullback base — reduce tier lag."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "new_session_base_near_miss_waive_enabled", True)):
        return False
    if not isinstance(alert, Mapping) or not alert.get("newSessionBase"):
        return False
    pad = alert_pad_move_pct(alert)
    pad_max = float(
        getattr(settings, "new_session_base_entry_max_move_pct", 22.0) or 22.0
    )
    pad_min = float(getattr(settings, "new_session_base_entry_min_move_pct", 2.0) or 2.0)
    if pad < 0 or pad < pad_min - 1e-6 or pad > pad_max + 1e-6:
        return False
    try:
        score = float(alert.get("explosionScore") or alert.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    min_score = float(
        getattr(settings, "new_session_base_near_miss_min_explosion_score", 18.0) or 18.0
    )
    if score < min_score - 1e-6:
        return False
    try:
        v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    except (TypeError, ValueError):
        v3 = 0.0
    min_v3 = float(
        getattr(settings, "new_session_base_near_miss_min_velocity_3s", 0.35) or 0.35
    )
    if v3 < min_v3 - 1e-6:
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("BUILDING", "ELITE", "EXPLODING", "HOT"):
        return False
    return True


def new_session_base_entry_floors(settings: Any = None) -> dict[str, float]:
    settings = settings or get_settings()
    return {
        "minMovePct": float(
            getattr(settings, "new_session_base_entry_min_move_pct", 2.0) or 2.0
        ),
        "maxMovePct": float(
            getattr(settings, "new_session_base_entry_max_move_pct", 22.0) or 22.0
        ),
    }


def session_base_guard_summary(settings: Any = None) -> dict[str, Any]:
    """Deployment HUD — session trough / rip-fall / stale-armed knobs (09:45+ book)."""
    settings = settings or get_settings()
    return {
        "newSessionBaseIdentifyEnabled": bool(
            getattr(settings, "new_session_base_identify_enabled", True)
        ),
        "newSessionBaseRequireIndexParticipation": bool(
            getattr(settings, "new_session_base_require_index_participation", True)
        ),
        "newSessionBaseSessionTroughStampEnabled": bool(
            getattr(settings, "new_session_base_session_trough_stamp_enabled", False)
        ),
        "newSessionBaseTroughMinFallFromPeakPct": float(
            getattr(settings, "new_session_base_trough_min_fall_from_peak_pct", 0.08) or 0.08
        )
        * 100.0,
        "explosionSessionRipFallBlockEnabled": bool(
            getattr(settings, "explosion_session_rip_fall_entry_block_enabled", True)
        ),
        "localBasePullbackArmedRespectRipFall": bool(
            getattr(settings, "local_base_pullback_armed_launch_respect_rip_fall", True)
        ),
        "localBasePullbackStaleTroughBlocksWaiver": bool(
            getattr(settings, "local_base_pullback_armed_launch_stale_trough_blocks_waiver", True)
        ),
        "localBasePullbackStaleTroughGapPct": float(
            getattr(settings, "local_base_pullback_stale_trough_gap_pct", 15.0) or 15.0
        ),
        "indexLiftTurnPutRipRequiresSlideOrNotBullishBreadth": bool(
            getattr(
                settings,
                "index_lift_turn_put_rip_requires_slide_or_not_bullish_breadth",
                True,
            )
        ),
        "fakeExplosionTrapPostWinArmedBaseBypassEnabled": bool(
            getattr(settings, "fake_explosion_trap_post_win_armed_base_bypass_enabled", False)
        ),
        "ripFallNearTroughMaxLiftPct": float(
            getattr(settings, "explosion_session_rip_fall_near_trough_max_lift_pct", 0.18)
            or 0.18
        )
        * 100.0,
        "newSessionBaseEntryFloors": new_session_base_entry_floors(settings),
        "newSessionBaseNearMissWaiveEnabled": bool(
            getattr(settings, "new_session_base_near_miss_waive_enabled", True)
        ),
    }


_RIP_FALL_OBS_KEYS = (
    "sessionRipFallBlock",
    "sessionRipFallExempt",
    "sessionRunPct",
    "fallFromPeakPct",
    "liftFromTroughPct",
    "sessionPeakPremium",
    "sessionLowPremium",
    "velocity3s",
    "premiumMomentum5Pct",
    "armedBaseStaleVsSessionTrough",
)


def session_base_observability_bundle(
    alert: Mapping[str, Any] | None = None,
    pretrade_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Funnel + entryContext stamps for post-session RCA (base vs fall-leg)."""
    out: dict[str, Any] = {}
    row = dict(alert) if isinstance(alert, Mapping) else {}
    pre = dict(pretrade_meta) if isinstance(pretrade_meta, Mapping) else {}
    rip = pre.get("sessionRipFall")
    if isinstance(rip, dict):
        for key in _RIP_FALL_OBS_KEYS:
            if rip.get(key) is not None:
                out[key] = rip[key]
    for key in (
        "newSessionBase",
        "newBaseKind",
        "effectiveBasePremium",
        "sessionTroughBase",
        "postRipPullbackBase",
        "localBasePullbackFill",
    ):
        if row.get(key) is not None:
            out[key] = row[key]
        elif pre.get(key) is not None:
            out[key] = pre[key]
    for key in _RIP_FALL_OBS_KEYS:
        if pre.get(key) is not None and key not in out:
            out[key] = pre[key]
    return out