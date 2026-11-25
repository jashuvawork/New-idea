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


def new_session_base_identify(
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
    *,
    velocity_3s: float = 0.0,
    stale_ict_base: float = 0.0,
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

    # 1) Session trough base — V-bottom / new pad at session low.
    trough_max = float(
        getattr(settings, "new_session_base_trough_max_off_low_pct", 14.0) or 14.0
    )
    if sess_low > 0:
        off_low = (live - sess_low) / sess_low * 100.0
        if 0.0 <= off_low <= trough_max + 1e-6:
            try:
                from app.engines.explosion_detector import mid_rip_armed_coil

                if not mid_rip_armed_coil(
                    session_low=sess_low,
                    armed_base=sess_low,
                    premium=live,
                    session_peak=sess_peak,
                    settings=settings,
                ):
                    meta.update(
                        {
                            "effectiveBasePremium": round(sess_low, 2),
                            "offBasePct": round(off_low, 2),
                            "newBaseKind": "session_trough",
                        }
                    )
                    return True, "session_trough", meta
            except Exception:
                meta.update(
                    {
                        "effectiveBasePremium": round(sess_low, 2),
                        "offBasePct": round(off_low, 2),
                        "newBaseKind": "session_trough",
                    }
                )
                return True, "session_trough", meta

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
                        meta.update(
                            {
                                "effectiveBasePremium": round(recent_base, 2),
                                "offBasePct": round(base_rel, 2),
                                "newBaseKind": "post_rip_pullback",
                                "recentWindowBase": True,
                            }
                        )
                        return True, "post_rip_pullback", meta

    return False, "", meta


def stamp_new_session_base_fields(
    row: dict[str, Any],
    *,
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
    velocity_3s: float = 0.0,
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


def session_base_guard_summary(settings: Any = None) -> dict[str, Any]:
    """Deployment HUD — session trough / rip-fall / stale-armed knobs (09:45+ book)."""
    settings = settings or get_settings()
    return {
        "newSessionBaseIdentifyEnabled": bool(
            getattr(settings, "new_session_base_identify_enabled", True)
        ),
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