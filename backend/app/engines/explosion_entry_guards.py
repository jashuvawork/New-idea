"""Explosion entry guards — OTM depth cap, peak-chase block, MACD alignment."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.moneyness import _depth_steps, atm_strike, classify_moneyness
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _strike_depth(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
) -> tuple[int, str, float]:
    spot = float(snap.spot or 0)
    symbol = snap.symbol.upper()
    atm = float(snap.atmStrike or atm_strike(spot, symbol))
    money = classify_moneyness(side, strike, spot, symbol=symbol, atm=atm)
    depth = _depth_steps(side, strike, spot, symbol, atm)
    return depth, money, atm


def structured_near_atm(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
    *,
    ict: Any = None,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
    candidate: Any = None,
) -> bool:
    """
    Near-ATM CE/PE (≤N OTM) with ICT/local-base structure.

    Softens worst-day / live-velocity floors for both sides without opening deep-OTM FOMO.
    """
    settings = get_settings()
    side_v = _side_val(side)
    if side_v not in ("CALL", "PUT"):
        return False
    depth, money, _ = _strike_depth(side, strike, snap)
    max_steps = int(getattr(settings, "structured_near_atm_max_otm_steps", 3) or 3)
    if money == "OTM" and depth > max_steps:
        return False
    if money not in ("ATM", "ITM", "OTM"):
        return False
    if _ict_structure_confirmed(ict):
        return True
    from app.engines.local_base_chart_bypass import local_base_structure_active

    resolved_alert = alert if isinstance(alert, dict) else None
    if resolved_alert is None and candidate is not None:
        ca = getattr(candidate, "alert", None)
        if isinstance(ca, dict):
            resolved_alert = ca
    resolved_event = event
    if resolved_event is None and candidate is not None:
        resolved_event = getattr(candidate, "explosion_event", None)
    return local_base_structure_active(
        side, snap, event=resolved_event, alert=resolved_alert,
    )


# Backward-compatible alias (Jul24 CE-named helper).
structured_near_atm_call = structured_near_atm


def check_all_in_moneyness_cap(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
) -> tuple[bool, str, dict[str, Any]]:
    """Hard cap OTM depth — all-in bypass cannot skip this."""
    settings = get_settings()
    depth, money, atm = _strike_depth(side, strike, snap)
    meta = {
        "moneyness": money,
        "strikeStepsFromAtm": depth,
        "atmStrike": atm,
        "allInOtmCap": settings.extreme_all_in_max_otm_steps,
    }
    if money != "OTM":
        return True, "ok", meta
    if depth > settings.extreme_all_in_max_otm_steps:
        return False, f"all_in_otm_too_deep_{depth}", meta
    return True, "ok", meta


def check_peak_chase_entry(
    candidate: Any,
    explosion_event: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """Block chasing deep OTM premium rips near local top."""
    settings = get_settings()
    if not settings.explosion_peak_chase_guard_enabled:
        return True, "ok"
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return True, "ok"

    depth, money, _ = _strike_depth(candidate.side, float(candidate.strike), snap)
    if money != "OTM" or depth <= settings.explosion_peak_chase_max_otm_steps:
        return True, "ok"

    v3 = v9 = daily = peak = 0.0
    if explosion_event is not None:
        v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
        v9 = float(getattr(explosion_event, "velocity_9s", 0) or 0)
        daily = float(getattr(explosion_event, "daily_move_pct", 0) or 0)
        peak = float(getattr(explosion_event, "peak_move_pct", 0) or 0)

    mom_thresh = settings.explosion_peak_chase_min_premium_mom_pct
    hot = (
        v3 >= mom_thresh
        or v9 >= mom_thresh * 1.2
        or daily >= settings.explosion_peak_chase_min_session_move_pct
        or peak >= settings.explosion_peak_chase_min_session_move_pct
    )
    if hot:
        return False, f"explosion_peak_chase_deep_otm_{depth}"
    return True, "ok"


def _session_peak_move(explosion_event: Any) -> float:
    if explosion_event is None:
        return 0.0
    daily = float(getattr(explosion_event, "daily_move_pct", 0) or 0)
    peak = float(getattr(explosion_event, "peak_move_pct", 0) or 0)
    return max(daily, peak)


def trustworthy_local_base_move(ict: Any) -> float:
    """
    Base-relative % when the pad print is real enough for timing gates.

    Jul24: alerts printed baseRel≈1–2% (noise) while day-move was already ~28%.
    Trust floor (default 8%) filters that noise.

    Aug5 24500 PE: day% showed ~67% chase while LTP was only ~9% off the chart
    local base (~66→72). Do NOT require flat→vertical to accept a real pad % —
    any baseRel ≥ trust floor is the launch pad for window/chase/must-take.
    """
    if ict is None:
        return 0.0
    settings = get_settings()
    base = float(getattr(ict, "base_relative_move_pct", 0) or 0)
    if base <= 0:
        return 0.0
    # Mid-rip coil rejection remounts pad onto session low — never trust a tiny
    # armed pad that ICT already flagged as contaminated.
    reasons = getattr(ict, "reasons", None) or []
    if any(
        isinstance(r, str) and r.startswith("mid_rip_coil_rejected_")
        for r in reasons
    ):
        return base
    # Armed local base is the causal denominator — trust pad even below the
    # generic 8% noise floor so elite/armed launches at 2–7% are not treated as 0.
    if bool(getattr(ict, "base_armed", False)):
        return base
    # V-rip off session low: ICT stamps v_rip_ready inside 2–25% — trust the pad.
    if bool(getattr(ict, "v_rip_ready", False)) and bool(
        getattr(settings, "ict_v_rip_ready_enabled", True)
    ):
        v_lo = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
        v_hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
        if v_lo <= base <= v_hi:
            return base
    trust_min = float(
        getattr(settings, "explosion_local_base_trust_min_move_pct", 8.0) or 8.0
    )
    if base < trust_min:
        return 0.0
    return base


def _recent_local_base_move(explosion_event: Any) -> float:
    """Move % off the recent ~30-min local base (swing low); -1.0 when no history.

    The full-session low is the far morning dip and overstates the move as a chase.
    The recent-window low is the actual pad the current leg launched from. Returns the
    accurate move even when small (near base = not a chase, just not yet in the window).
    """
    if explosion_event is None:
        return -1.0
    settings = get_settings()
    if not getattr(settings, "explosion_local_base_recent_window_enabled", True):
        return -1.0
    try:
        from app.engines.explosion_detector import local_base_premium

        sym = str(getattr(explosion_event, "symbol", "") or "")
        strike = float(getattr(explosion_event, "strike", 0) or 0)
        side = getattr(explosion_event, "side", None)
        prem = float(getattr(explosion_event, "premium", 0) or 0)
        if not sym or side is None or prem <= 0:
            return -1.0
        base = float(local_base_premium(sym, strike, side) or 0)
        if base <= 0:
            return -1.0
        if prem <= base:
            return 0.0
        return (prem - base) / base * 100.0
    except Exception:
        return -1.0


def _off_low_move_pct(explosion_event: Any) -> float:
    """% above today's meaningful session low (V-bottom / reclaim)."""
    if explosion_event is None:
        return 0.0
    try:
        from app.engines.explosion_detector import session_low_relative_move_pct

        off_low = float(
            session_low_relative_move_pct(
                str(getattr(explosion_event, "symbol", "") or ""),
                float(getattr(explosion_event, "strike", 0) or 0),
                getattr(explosion_event, "side", None),
                float(getattr(explosion_event, "premium", 0) or 0),
            )
            or 0.0
        )
    except Exception:
        off_low = 0.0
    return off_low if off_low > 0 else 0.0


def effective_local_base_move_pct(
    explosion_event: Any = None,
    ict: Any = None,
) -> float:
    """Primary timing metric: local pad %, never day-peak %.

    Order:
      1) trustworthy ICT base-relative move
      2) session-low / off-low reclaim %
      3) 0 → caller may fall back to day% only when no pad exists
    """
    settings = get_settings()
    if not getattr(settings, "explosion_chase_use_local_base", True):
        return 0.0
    trust_min = float(
        getattr(settings, "explosion_local_base_trust_min_move_pct", 8.0) or 8.0
    )
    base = trustworthy_local_base_move(ict)
    if base > 0:
        return base
    # Recent ~30-min local base (swing low) — accurate pad when ICT flat-base didn't fire
    # on a choppy base. Use it whenever local-base history exists, even if the move off it
    # is small (near base ≠ chase). Only fall back to the far session-low when there's no
    # local-base history at all.
    recent = _recent_local_base_move(explosion_event)
    if recent >= 0:
        return recent
    off_low = _off_low_move_pct(explosion_event)
    if off_low >= trust_min:
        return off_low
    return 0.0


def structured_early_ict_ready(ict: Any) -> bool:
    """ICT swing/flat→vertical with heat — may use the nearer-base 10–65% band."""
    settings = get_settings()
    if not bool(getattr(settings, "ict_structured_early_entry_enabled", True)):
        return False
    if ict is None:
        return False
    structured = bool(getattr(ict, "local_swing_base", False)) or bool(
        getattr(ict, "flat_then_vertical", False)
    )
    if not structured:
        return False
    return bool(
        getattr(ict, "first_lift", False)
        or getattr(ict, "volume_awakening", False)
        or getattr(ict, "displacement", False)
        or getattr(ict, "premium_fvg", False)
    )


def entry_window_bounds(
    ict: Any = None,
    *,
    top_must_take: bool = False,
) -> tuple[float, float]:
    """Return (min%, max%) for the hard entry window.

    Unstructured spikes stay on the book band 28–65%.
    Structured ICT + heat, or top must-take (already near-base ATM/ITM),
    uses the nearer-base band (default 10–65%).
    """
    settings = get_settings()
    lo = float(getattr(settings, "explosion_early_window_min_move_pct", 28.0) or 28.0)
    hi = float(getattr(settings, "explosion_early_window_max_move_pct", 65.0) or 65.0)
    if top_must_take or structured_early_ict_ready(ict):
        lo = float(getattr(settings, "ict_structured_early_min_move_pct", 15.0) or 15.0)
        hi = float(getattr(settings, "ict_structured_early_max_move_pct", 65.0) or 65.0)
    if getattr(ict, "armed_base_launch", False) is True:
        lo = float(
            getattr(settings, "ict_armed_base_launch_min_move_pct", 5.0) or 5.0
        )
        hi = float(
            getattr(settings, "ict_armed_base_launch_max_move_pct", 15.0) or 15.0
        )
        # Sustained armed lift is the sparse-feed early FTV path through 25%.
        if getattr(ict, "armed_base_sustained_lift", False) is True:
            lo = min(
                lo,
                float(
                    getattr(settings, "ict_armed_sustained_lift_min_move_pct", 8.0)
                    or 8.0
                ),
            )
            hi = max(
                hi,
                float(
                    getattr(settings, "ict_armed_sustained_lift_max_move_pct", 25.0)
                    or 25.0
                ),
            )
    return lo, hi


def tier_promotion_pad_chase_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Block ELITE/EXPLODING entries promoted off the pad without a pad stamp.

    Aug28 NIFTY 24250 CE 10:17: ELITE at 8.4% baseRel after a micro-rip — chase,
    not cold-trough entry. Pad-stamped cold-trough lanes may still enter.
    """
    settings = get_settings()
    if not getattr(settings, "tier_promotion_pad_chase_block_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    tier = str(getattr(explosion_event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False, ""

    from app.engines.early_radar_pad_capture import alert_has_early_radar_pad_capture

    resolved = alert if isinstance(alert, dict) else {}
    if alert_has_early_radar_pad_capture(resolved):
        return False, ""

    threshold = float(
        getattr(settings, "tier_promotion_pad_chase_min_base_rel_pct", 8.0) or 8.0
    )
    base_rel = effective_local_base_move_pct(explosion_event, ict)
    if base_rel > threshold + 1e-6:
        return True, f"tier_promotion_pad_chase_blocked_{base_rel:.1f}%"
    return False, ""


def explosion_entry_window_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
    top_must_take: bool = False,
    squeeze_early_base: bool = False,
    bullish_local_base: bool = False,
) -> tuple[bool, str]:
    """Hard-block EXPLOSIVE entries outside the active early window.

    Unstructured: 28–65% (book). Structured ICT flat→vertical / swing V-base
    with heat, or top must-take: 10–65% so the first vertical leg stays
    tradeable — including Aug4 SENSEX 78700 PE (~54% off local base).

    Timing is measured from:
      1) trustworthy ICT local/swing base when present
      2) else % above today's meaningful session low (V-bottom reclaim)
      3) else day/peak session move (only when no pad exists)

    Weak ICT raw base must not hide behind day % — but only after a trusted
    off-low / local pad has been given a chance (Aug5 24500-style).
    Fake micro-baseline day moves (+8873%) are ignored when off-low is known.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_entry_window_hard_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    lo, hi = entry_window_bounds(ict, top_must_take=top_must_take)
    # Non-must-take ELITE/EXPLODING: take at local-base pad (default ≤40%).
    # Must-take keeps the wider structured band (≤65%).
    if not top_must_take:
        tier_u = str(getattr(explosion_event, "tier", "") or "").upper()
        if tier_u in ("ELITE", "EXPLODING"):
            elite_hi = float(
                getattr(settings, "elite_local_base_max_move_pct", 40.0) or 40.0
            )
            if elite_hi > 0:
                hi = min(hi, elite_hi)
            # Closed loop (entry-side): tighten the near-base ceiling per moment type from
            # the accumulated EOD knowledge — take nearer the local base, skip the milder
            # off-base chases this moment type historically didn't sustain. TIGHTEN-ONLY and
            # floored so genuine near-base first lifts (<= floor) are never blocked.
            if bool(getattr(settings, "eod_learning_apply_enabled", False)):
                try:
                    from app.engines.eod_ftv_learning import learned_ftv_profile

                    side_u = str(
                        getattr(getattr(explosion_event, "side", None), "value",
                                getattr(explosion_event, "side", "")) or ""
                    ).upper()
                    prof = learned_ftv_profile(
                        str(getattr(explosion_event, "symbol", "") or ""), side_u, tier_u,
                    )
                    min_n = int(getattr(settings, "eod_learning_apply_min_samples", 5) or 5)
                    if prof and int(prof.get("count", 0)) >= min_n:
                        learned_max = float(prof.get("recommendedNearBaseMaxPct") or 0)
                        floor = float(
                            getattr(settings, "eod_learning_near_base_floor_pct", 25.0)
                            or 25.0
                        )
                        if learned_max > 0:
                            hi = min(hi, max(floor, learned_max))
                except Exception:
                    pass
    # Squeeze-fired ELITE at a confirmed local base — a Bollinger/Keltner release off the
    # base is a confirmed coil break, not noise, so allow entry closer to the base than the
    # normal 15% floor (catch it AT the base). Gated by the caller to squeeze + ELITE + base.
    if squeeze_early_base and getattr(
        settings, "explosion_squeeze_early_base_enabled", True
    ):
        sq_floor = float(
            getattr(settings, "explosion_squeeze_early_base_min_move_pct", 8.0) or 8.0
        )
        if sq_floor > 0:
            lo = min(lo, sq_floor)
    # A confirmed CE/PE reversal at the measured local base receives the same early floor
    # as a squeeze release. The predictor already requires a live momentum turn, positive
    # option acceleration and volume (+ ICT confirms); chase/fake-trap/risk gates still run.
    if bullish_local_base and getattr(
        settings, "bullish_local_base_prediction_enabled", True
    ):
        bullish_floor = float(
            getattr(settings, "bullish_local_base_prediction_min_move_pct", 8.0) or 8.0
        )
        if bullish_floor > 0:
            lo = min(lo, bullish_floor)
    try:
        max_credible = float(
            getattr(settings, "session_move_max_credible_pct", 500.0)
        )
    except (TypeError, ValueError):
        max_credible = 500.0
    if max_credible <= 0:
        max_credible = 500.0

    session = _session_peak_move(explosion_event)
    if ict is not None:
        session = max(session, float(getattr(ict, "session_move_pct", 0) or 0))

    # Primary: local pad / off-low — never day% when a pad exists.
    pad = effective_local_base_move_pct(explosion_event, ict)
    if pad > 0:
        if pad < lo:
            return True, f"entry_window_local_low_{pad:.0f}%"
        if pad > hi:
            return True, f"entry_window_local_high_{pad:.0f}%"
        return False, ""

    # No trusted pad — ICT may still print a sub-floor raw base. Do not let
    # a "good-looking" day % hide that still-forming local (Jul30 77700).
    raw_local = (
        float(getattr(ict, "base_relative_move_pct", 0) or 0) if ict is not None else 0.0
    )
    if 0 < raw_local < lo:
        return True, f"entry_window_weak_local_{raw_local:.0f}%"

    # Uncredible day-% (micro-baseline artifact) with no pad → treat as unknown/low.
    if session > max_credible:
        return True, f"entry_window_uncredible_{session:.0f}%"

    if session < lo:
        return True, f"entry_window_low_{session:.0f}%"
    if session > hi:
        return True, f"entry_window_high_{session:.0f}%"
    return False, ""


def immature_explosion_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    bullish_local_base: bool = False,
    skip_elite_bypass: bool = False,
) -> tuple[bool, str]:
    """
    Block hot-velocity / displacement noise before a real premium rip prints.

    Jul20 NIFTY CALL losses entered at +0.8% / +1.4% session move with
    ictPattern=displacement — not a base→vertical. Require a minimum session
    move unless true flat→vertical early ICT is already confirmed.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_immature_block_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    if not skip_elite_bypass:
        from app.engines.elite_never_block import elite_must_take_bypass_allowed

        if elite_must_take_bypass_allowed(event=explosion_event, ict=ict, alert=alert):
            return False, ""

    move = _session_peak_move(explosion_event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    min_move = float(
        getattr(settings, "explosion_immature_min_session_move_pct", 28.0) or 28.0
    )
    early_min = float(
        getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0
    )
    # Structured local pad only for immature — unstructured baseRel must not
    # hold a day-mature rip as "immature_local" (Jul24). Chase/window still
    # use any pad ≥ trust via effective_local_base_move_pct.
    base_move = (
        trustworthy_local_base_move(ict)
        if getattr(settings, "explosion_chase_use_local_base", True)
        else 0.0
    )
    structured_pad = bool(ict is not None) and (
        bool(getattr(ict, "local_swing_base", False))
        or bool(getattr(ict, "flat_then_vertical", False))
    )
    if getattr(ict, "armed_base_launch", False) is True:
        return False, ""
    if base_move > 0 and structured_pad:
        local_floor = float(
            getattr(settings, "explosion_local_base_entry_min_move_pct", 15.0) or 15.0
        )
        if structured_early_ict_ready(ict):
            local_floor = min(
                local_floor,
                float(getattr(settings, "ict_structured_early_min_move_pct", 15.0) or 15.0),
            )
        if bullish_local_base and getattr(
            settings, "bullish_local_base_prediction_enabled", True
        ):
            local_floor = min(
                local_floor,
                float(
                    getattr(
                        settings,
                        "bullish_local_base_prediction_min_move_pct",
                        8.0,
                    )
                    or 8.0
                ),
            )
        # V-rip off session low: pad window is 2–25% (ict_v_rip_*), not the 15% structured floor.
        # Aug25 NIFTY PUT 24250 EXPLODING v_rip at 7.1% was blocked immature_local_base despite
        # flat→vertical + volumeAwaken and radar mfe 26%.
        if bool(getattr(ict, "v_rip_ready", False)) and bool(
            getattr(settings, "ict_v_rip_ready_enabled", True)
        ):
            v_lo = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
            v_hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
            if (
                v_lo <= base_move <= v_hi
                and bool(getattr(ict, "volume_awakening", False))
            ):
                local_floor = min(local_floor, v_lo)
        # Aug28 SENSEX PUT 77500: ict_base_armed prelaunch at 5.4% lb blocked as immature.
        if (
            bool(getattr(ict, "base_armed", False))
            and not bool(getattr(ict, "armed_base_launch", False))
            and str(getattr(explosion_event, "tier", "") or "").upper()
            in ("ELITE", "EXPLODING")
        ):
            pad_min = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
            pad_max = float(
                getattr(settings, "early_radar_pad_max_local_move_pct", 20.0) or 20.0
            )
            min_score = float(
                getattr(
                    settings,
                    "early_radar_pad_exploding_prelaunch_min_score",
                    25.0,
                )
                or 25.0
            )
            score = float(getattr(explosion_event, "explosion_score", 0) or 0)
            if (
                pad_min <= base_move <= pad_max + 1e-6
                and score >= min_score
            ):
                local_floor = min(local_floor, pad_min)
        if base_move >= local_floor:
            return False, ""
        return True, f"immature_local_base_{base_move:.1f}%"

    if move >= min_move:
        return False, ""

    # Only exception: confirmed flat→vertical already at early ICT floor.
    if (
        ict is not None
        and bool(getattr(ict, "active", False))
        and bool(getattr(ict, "flat_then_vertical", False))
        and (
            bool(getattr(ict, "volume_awakening", False))
            or bool(getattr(ict, "displacement", False))
        )
        and move >= early_min
    ):
        return False, ""

    return True, f"immature_explosion_move_{move:.1f}%"


def _ict_structure_confirmed(ict: Any) -> bool:
    """True ICT structure — not displacement-only / sticky-tier noise."""
    if ict is None:
        return False
    if not bool(getattr(ict, "active", False)):
        return False
    if bool(getattr(ict, "flat_then_vertical", False)):
        return True
    if bool(getattr(ict, "mega_rip", False)):
        return True
    if bool(getattr(ict, "premium_fvg", False)) and (
        bool(getattr(ict, "volume_awakening", False))
        or bool(getattr(ict, "displacement", False))
    ):
        return True
    if bool(getattr(ict, "volume_awakening", False)) and bool(
        getattr(ict, "displacement", False)
    ):
        return True
    # Dump→V-bottom reclaim with heat + early local-base expansion.
    settings = get_settings()
    local_floor = float(
        getattr(settings, "explosion_local_base_entry_min_move_pct", 15.0) or 15.0
    )
    base_rel = float(getattr(ict, "base_relative_move_pct", 0) or 0)
    if (
        bool(getattr(ict, "local_swing_base", False))
        and base_rel >= local_floor
        and (
            bool(getattr(ict, "volume_awakening", False))
            or bool(getattr(ict, "displacement", False))
        )
    ):
        return True
    return False


def live_explosion_confirmation_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    midday_chop: Optional[bool] = None,
    premium_capture: bool = False,
    snap: Optional[SymbolSnapshot] = None,
) -> tuple[bool, str]:
    """
    Hard-block wrong-timing explosions that look ELITE but lack live confirmation.

    Jul23 day book failures this stops:
    - NIFTY 23900 PE ELITE with v3=0.26 / ictPattern=watch (stale sticky tier)
    - NIFTY 23900 PE ELITE v3=2.35 displacement-only (no flat→vertical)
    - SENSEX 76200 PE midday displacement spike without structure

    Still allows: ICT flat→vertical with live heat (Jul23 76300 PE profile), and
    genuine volume-backed premium/afternoon captures (slow grinds, low velocity by
    design — e.g. NIFTY 24250 PE 1pm consolidation breakout).
    """
    settings = get_settings()
    if not getattr(settings, "explosion_live_confirm_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    from app.engines.ict_breakout_monitor import first_lift_entry_ready

    if first_lift_entry_ready(
        snap=snap,
        event=explosion_event,
        ict=ict,
    ):
        return False, ""

    tier = str(getattr(explosion_event, "tier", "") or "").upper()
    if (
        ict is not None
        and bool(getattr(ict, "base_armed", False))
        and not bool(getattr(ict, "armed_base_launch", False))
        and tier in ("ELITE", "EXPLODING")
    ):
        base_rel = float(getattr(ict, "base_relative_move_pct", 0) or 0)
        pad_min = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
        pad_max = float(
            getattr(settings, "early_radar_pad_max_local_move_pct", 20.0) or 20.0
        )
        min_score = float(
            getattr(
                settings,
                "early_radar_pad_exploding_prelaunch_min_score",
                25.0,
            )
            or 25.0
        )
        score = float(getattr(explosion_event, "explosion_score", 0) or 0)
        if pad_min <= base_rel <= pad_max + 1e-6 and score >= min_score:
            return False, ""

    from app.engines.elite_never_block import elite_must_take_bypass_allowed

    if elite_must_take_bypass_allowed(
        event=explosion_event, ict=ict, snap=snap, alert=alert,
    ):
        return False, ""

    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False, ""

    v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
    v9 = float(getattr(explosion_event, "velocity_9s", 0) or 0)
    min_v3 = float(
        getattr(settings, "explosion_live_confirm_min_velocity_3s", 2.0) or 2.0
    )
    # Soft floor for confirmed ICT flat→vertical mid-burst (brief velocity dip).
    ict_min_v3 = float(
        getattr(settings, "explosion_live_confirm_ict_min_velocity_3s", 1.5) or 1.5
    )
    structure = _ict_structure_confirmed(ict)

    # Structured near-ATM CE/PE with cooled live v3 but retained peak.
    near_atm_structured = False
    peak_v3 = 0.0
    if snap is not None:
        near_atm_structured = structured_near_atm(
            getattr(explosion_event, "side", ""),
            float(getattr(explosion_event, "strike", 0) or 0),
            snap,
            ict=ict,
            event=explosion_event,
        )
        if near_atm_structured:
            from app.engines.explosion_detector import retained_peak_velocity_3s

            peak_v3 = float(
                retained_peak_velocity_3s(
                    str(getattr(explosion_event, "symbol", "") or ""),
                    float(getattr(explosion_event, "strike", 0) or 0),
                    getattr(explosion_event, "side", Side.CALL),
                )
                or 0
            )
            soft = float(
                getattr(
                    settings,
                    "explosion_live_confirm_structured_ce_min_velocity_3s",
                    1.0,
                )
                or 1.0
            )
            ict_min_v3 = min(ict_min_v3, soft)
            min_v3 = min(min_v3, soft)

    # Genuine premium/afternoon capture is a validated slow-grind path (in-window +
    # score + volume + consolidation + chart alignment). It is live-confirmed by that
    # classification, not by raw velocity — afternoon consolidation breakouts are slow
    # by design. Require a real volume surge (or ICT structure) so a structure-less,
    # low-volume displacement spike cannot ride this bypass.
    if premium_capture and getattr(
        settings, "explosion_live_confirm_premium_capture_bypass", True
    ):
        vol_surge = float(getattr(explosion_event, "volume_surge", 0) or 0)
        min_vol = float(
            getattr(settings, "explosion_live_confirm_premium_min_vol_surge", 1.3) or 1.3
        )
        if structure or vol_surge >= min_vol:
            return False, ""

    # 1) Stale / cooled live velocity — sticky ELITE alone is not enough.
    # Structured near-ATM CE/PE may use retained peak velocity when live cooled.
    eff_v3 = max(v3, peak_v3) if near_atm_structured else v3
    if structure or near_atm_structured:
        if eff_v3 < ict_min_v3 and v9 < min_v3:
            return True, f"stale_live_velocity_v3_{v3:.2f}_ict"
    elif v3 < min_v3:
        return True, f"stale_live_velocity_v3_{v3:.2f}"

    # 2) Structure confirmation — displacement-only / watch must not enter.
    require_structure = bool(
        getattr(settings, "explosion_live_confirm_require_structure", True)
    )
    if require_structure and not structure:
        # Allow extreme hot velocity + real session rip without ICT object only
        # when both v3 and session move clear early-window floors.
        move = _session_peak_move(explosion_event)
        if ict is not None:
            move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))
        early_min = float(
            getattr(settings, "explosion_early_window_min_move_pct", 28.0) or 28.0
        )
        hot_v3 = float(
            getattr(settings, "explosion_live_confirm_hot_velocity_3s", 8.0) or 8.0
        )
        # Midday chop: never allow structure-less entries (FOMO spikes).
        if midday_chop is None:
            midday_chop = _midday_chop_active()
        if midday_chop:
            return True, "midday_no_ict_structure"
        if not (v3 >= hot_v3 and move >= early_min):
            return True, "no_ict_structure_confirmation"

    return False, ""


def post_peak_chase_blocked(
    explosion_event: Any,
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Don't chase the EXHAUSTION of a completed move — block buying near the top of a run
    that already happened (symmetric for CE and PE, since we always buy the option premium).

    Reads the contract's recent premium history: if a run of >= min_run occurred in the
    lookback window AND the current premium is within near_top_frac of that window's peak,
    the leg is spent and this is a late chase (today's live PUT 23950: bought near the low
    at 10:47 as the down-move exhausted, then the market V-reversed and stopped it). A genuine
    near-base entry is exempt by construction — current sits near the window LOW, not its peak.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "explosion_post_peak_chase_guard_enabled", True)):
        return False, ""
    if explosion_event is None:
        return False, ""
    sym = str(getattr(explosion_event, "symbol", "") or "")
    side = getattr(explosion_event, "side", None)
    strike = float(getattr(explosion_event, "strike", 0) or 0)
    if not sym or side is None:
        return False, ""
    lookback = float(
        getattr(settings, "explosion_post_peak_chase_lookback_seconds", 900.0) or 900.0
    )
    min_run = float(
        getattr(settings, "explosion_post_peak_chase_min_run_pct", 0.25) or 0.25
    )
    near_top = float(
        getattr(settings, "explosion_post_peak_chase_near_top_frac", 0.12) or 0.12
    )
    try:
        from app.engines.explosion_detector import recent_premium_run

        r = recent_premium_run(sym, strike, side, lookback_seconds=lookback)
    except Exception:
        return False, ""
    high = float(r.get("high") or 0)
    current = float(r.get("current") or 0)
    run = float(r.get("run") or 0)
    if high <= 0 or current <= 0:
        return False, ""
    if run >= min_run and current >= high * (1.0 - near_top):
        return True, "explosion_post_peak_chase"
    return False, ""


def extended_session_chase_blocked(
    explosion_event: Any,
    *,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """
    Hard-block EXPLOSIVE entries after the move is already mostly done.

    Measure from LOCAL BASE / session-low pad first — day-session % alone always
    looks like a chase after an earlier run-up (Jul23 SENSEX 76400 PE: +471% day
    at the 14:35 local reclaim; Aug5 24500 PE: day ~67% while pad was ~9%).

    When a pad exists, day% is ignored entirely.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_extended_chase_block_enabled", True):
        return False, ""
    if explosion_event is None:
        return False, ""

    from app.engines.elite_never_block import elite_must_take_bypass_allowed

    # Near-base top ELITE/EXPLODING must never be chase-blocked — take at the pad.
    if elite_must_take_bypass_allowed(
        event=explosion_event, ict=ict, alert=alert,
    ):
        return False, ""

    move = _session_peak_move(explosion_event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    base_move = effective_local_base_move_pct(explosion_event, ict)
    if base_move > 0:
        local_max = float(
            getattr(settings, "explosion_local_base_chase_max_move_pct", 65.0) or 65.0
        )
        if base_move > local_max:
            return True, f"explosion_extended_chase_local_{base_move:.0f}%"
        # Local / off-low pad still inside the window — never block on day %.
        return False, ""

    hard = float(getattr(settings, "explosion_extended_chase_min_move_pct", 65.0) or 65.0)
    early_max = float(getattr(settings, "explosion_early_window_max_move_pct", 65.0) or 65.0)
    if move < hard:
        return False, ""

    # Keep true early base-break ICT inside the early window only.
    # (premium_fvg chases at +91% stay blocked — that is the PF killer.)
    if (
        ict is not None
        and bool(getattr(ict, "flat_then_vertical", False))
        and bool(getattr(ict, "active", False))
        and move <= early_max
    ):
        return False, ""

    # Legacy base-relative bypass when local-primary path is off / no base_move.
    if (
        ict is not None
        and getattr(settings, "ict_base_relative_chase_bypass_enabled", True)
        and bool(getattr(ict, "flat_then_vertical", False))
        and bool(getattr(ict, "active", False))
        and (
            bool(getattr(ict, "volume_awakening", False))
            or bool(getattr(ict, "displacement", False))
        )
    ):
        base_max = float(
            getattr(settings, "ict_base_relative_chase_max_move_pct", 65.0) or 65.0
        )
        abs_cap = float(
            getattr(settings, "ict_base_relative_chase_abs_move_cap_pct", 160.0) or 160.0
        )
        ignore_abs = bool(
            getattr(settings, "ict_base_relative_ignore_abs_cap", True)
        )
        legacy_base = float(getattr(ict, "base_relative_move_pct", 0) or 0)
        if 0 < legacy_base <= base_max and (ignore_abs or move <= abs_cap):
            return False, ""

    return True, f"explosion_extended_chase_{move:.0f}%"


def cap_extended_chase_lots(lots: int, explosion_event: Any, *, ict: Any = None) -> int:
    """Shrink size in the soft extended zone; hard-cap all explosion size."""
    settings = get_settings()
    hard_cap = int(getattr(settings, "explosion_hard_lot_cap", 10) or 10)
    lots = min(max(1, lots), hard_cap)
    move = _session_peak_move(explosion_event)
    try:
        base_max = float(
            getattr(settings, "ict_base_relative_chase_max_move_pct", 55.0) or 55.0
        )
    except (TypeError, ValueError):
        base_max = 55.0
    # Prefer trusted local pad / off-low over raw ICT baseRel (day% can lie).
    try:
        pad = float(effective_local_base_move_pct(explosion_event, ict) or 0.0)
    except Exception:
        pad = 0.0
    if pad <= 0 and ict is not None:
        try:
            pad = float(getattr(ict, "base_relative_move_pct", 0) or 0)
        except (TypeError, ValueError):
            pad = 0.0
    # Local / flat base still inside the soft early window → full size.
    if 0 < pad <= base_max:
        return lots
    # Soft-cap using local base when day-move is misleadingly large.
    if pad > base_max and getattr(settings, "explosion_chase_use_local_base", True):
        soft_cap = int(getattr(settings, "explosion_extended_soft_lot_cap", 6) or 6)
        return min(lots, soft_cap)
    soft = float(getattr(settings, "explosion_extended_soft_min_move_pct", 50.0) or 50.0)
    if move >= soft:
        soft_cap = int(getattr(settings, "explosion_extended_soft_lot_cap", 6) or 6)
        lots = min(lots, soft_cap)
    return lots


def check_explosion_macd_alignment(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> tuple[bool, str]:
    """Require MACD bias to align with explosion side (no bearish MACD CALLs)."""
    settings = get_settings()
    if not settings.explosion_macd_alignment_required:
        return True, "ok"

    from app.engines.elite_never_block import elite_must_take_bypass_allowed

    if elite_must_take_bypass_allowed(
        event=event, candidate=candidate, alert=alert, snap=snap,
    ):
        return True, "ok"

    chart = snap.spotChart
    if not chart:
        return True, "ok"

    macd_bias = str(chart.macdBias or "NEUTRAL").upper()
    side_val = _side_val(side)

    if side_val == "CALL" and macd_bias == "BEARISH":
        return False, "explosion_macd_bearish_blocks_call"
    if side_val == "PUT" and macd_bias == "BULLISH":
        return False, "explosion_macd_bullish_blocks_put"
    return True, "ok"


def detect_faded_vertical_rip(
    explosion_event: Any,
    snap: Optional[SymbolSnapshot] = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Peak rip already happened but live velocity cooled — same pattern as cheap OTM
    explosion chase on worst days. Take with caution (smaller size, tighter stop).
    """
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not getattr(settings, "explosion_faded_rip_caution_enabled", True):
        return False, meta
    if explosion_event is None:
        return False, meta

    tier = str(getattr(explosion_event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False, meta

    v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
    peak = float(getattr(explosion_event, "peak_move_pct", 0) or 0)
    min_peak = float(getattr(settings, "explosion_faded_rip_min_peak_pct", 35.0) or 35.0)
    max_live = float(getattr(settings, "explosion_faded_rip_max_live_velocity_3s", 0.5) or 0.5)
    if peak < min_peak or v3 > max_live:
        return False, meta

    from app.engines.explosion_detector import retained_peak_velocity_3s
    from app.models.schemas import Side

    side = getattr(explosion_event, "side", Side.CALL)
    peak_v3 = retained_peak_velocity_3s(
        str(getattr(explosion_event, "symbol", "") or ""),
        float(getattr(explosion_event, "strike", 0) or 0),
        side,
    )
    if peak_v3 < float(settings.worst_day_breakout_min_velocity_3s):
        return False, meta

    meta = {
        "fadedVerticalRip": True,
        "fadedRipCaution": True,
        "peakMovePct": round(peak, 2),
        "liveVelocity3s": round(v3, 2),
        "peakVelocity3s": round(peak_v3, 2),
        "cautionLotCap": int(getattr(settings, "explosion_faded_rip_lot_cap", 8) or 8),
    }
    if snap is not None:
        depth, money, atm = _strike_depth(
            side,
            float(getattr(explosion_event, "strike", 0) or 0),
            snap,
        )
        meta["moneyness"] = money
        meta["strikeStepsFromAtm"] = depth
        meta["atmStrike"] = atm
    return True, meta


def cap_faded_rip_lots(lots: int) -> int:
    settings = get_settings()
    cap = int(getattr(settings, "explosion_faded_rip_lot_cap", 8) or 8)
    return min(max(1, lots), cap)


def faded_rip_stop_multiplier() -> float:
    settings = get_settings()
    return float(getattr(settings, "explosion_faded_rip_tighter_stop_mult", 0.85) or 0.85)


def is_faded_rip_caution_trade(trade: Any) -> bool:
    """Explosion-only — faded vertical rip entered with caution sizing."""
    from app.models.schemas import StrategyType

    ctx = getattr(trade, "entryContext", None) or {}
    if not (ctx.get("fadedRipCaution") or ctx.get("fadedVerticalRip")):
        return False
    strategy = getattr(trade, "strategyType", None)
    if strategy == StrategyType.EXPLOSIVE:
        return True
    return str(ctx.get("selectionMode") or "").lower() == "explosion"


def _faded_rip_chart_aligned_hold(trade: Any) -> bool:
    """Strong session rip + chart flipped aligned — keep faded-rip runner."""
    settings = get_settings()
    min_move = float(getattr(settings, "faded_rip_no_green_hold_min_session_move_pct", 60.0) or 60.0)
    ctx = getattr(trade, "entryContext", None) or {}
    session_move = max(
        float(ctx.get("dailyMovePct") or ctx.get("openPremiumMove") or 0),
        float(ctx.get("peakMovePct") or 0),
        float(ctx.get("sessionMovePct") or 0),
    )
    if session_move < min_move:
        return False

    from app.models.schemas import Side

    side = getattr(trade, "side", Side.CALL)
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    for chart in (
        (ctx.get("executionChart") or {}).get("indexChart") or {},
        (ctx.get("executionChart") or {}).get("snapshotChart") or {},
    ):
        direction = str(chart.get("direction", "NEUTRAL")).upper()
        if side_val == "CALL" and direction == "BULLISH":
            return True
        if side_val == "PUT" and direction == "BEARISH":
            return True
    breadth = str(ctx.get("breadth") or "").upper()
    if side_val == "CALL" and breadth == "BULLISH":
        return True
    if side_val == "PUT" and breadth == "BEARISH":
        return True
    return False


def faded_rip_no_green_exit_reason(
    trade: Any,
    *,
    hold_seconds: float,
    best_points: float,
) -> Optional[str]:
    """Exit explosive fade-chase if never went green within the caution window."""
    settings = get_settings()
    if not getattr(settings, "explosion_faded_rip_no_green_exit_enabled", True):
        return None
    if not is_faded_rip_caution_trade(trade):
        return None
    if _faded_rip_chart_aligned_hold(trade):
        return None
    limit = int(getattr(settings, "explosion_faded_rip_no_green_seconds", 60) or 60)
    min_green = float(getattr(settings, "explosion_faded_rip_min_green_points", 0.5) or 0.5)
    if hold_seconds >= limit and best_points < min_green:
        return "explosion_faded_rip_no_green"
    return None


def _regime_chopish(snap: SymbolSnapshot) -> bool:
    regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime or "").upper()
    if regime in ("CHOP", "RANGE_BOUND"):
        return True
    chart = snap.spotChart
    if chart is None:
        return False
    mom = abs(float(getattr(chart, "momentum5Pct", 0) or 0))
    strength = float(getattr(chart, "trendStrength", 100) or 100)
    return mom < 0.25 and strength < 45


def _midday_chop_active() -> bool:
    """Time-window chop — independent of scalp-block toggle."""
    try:
        from app.engines.session_timing import _minutes_now
        from app.services.upstox import get_market_phase

        if get_market_phase() != "LIVE_MARKET":
            return False
        settings = get_settings()
        current = _minutes_now()
        start = settings.midday_chop_start_hour * 60 + settings.midday_chop_start_minute
        end = settings.midday_chop_end_hour * 60 + settings.midday_chop_end_minute
        return start <= current < end
    except Exception:
        return False


def _or_position(snap: SymbolSnapshot) -> str:
    chart = snap.spotChart
    if chart is None:
        return ""
    return str(getattr(chart, "orPosition", "") or "").upper()


def _premium_mom_flat(premium_chart: Any) -> bool:
    """Live premium already cooled — FOMO fill risk (Jul20 mom3/5=0, NEUTRAL)."""
    if premium_chart is None:
        return False
    settings = get_settings()
    max_mom = float(
        getattr(settings, "fake_explosion_trap_max_premium_mom_pct", 0.15) or 0.15
    )
    if isinstance(premium_chart, dict):
        mom3 = float(premium_chart.get("momentum3Pct") or 0)
        mom5 = float(premium_chart.get("momentum5Pct") or 0)
        direction = str(premium_chart.get("direction") or "").upper()
    else:
        mom3 = float(getattr(premium_chart, "momentum3Pct", 0) or 0)
        mom5 = float(getattr(premium_chart, "momentum5Pct", 0) or 0)
        direction = str(getattr(premium_chart, "direction", "") or "").upper()
    flat_mom = abs(mom3) <= max_mom and abs(mom5) <= max_mom
    return flat_mom or direction == "NEUTRAL"


def _worst_or_expiry_chop_day(snap: SymbolSnapshot, state: Any = None) -> bool:
    """True only when the live session is labeled WORST / EXPIRY WORST.

    Do not infer from RANGE_BOUND alone — that would hard-block valid Jul31-style
    base-window EXPLODING entries on ordinary midday chop.
    """
    if state is None:
        return False
    for attr in ("dayMode", "day_mode", "dailyStrategy", "dayAdaptive"):
        raw = getattr(state, attr, None)
        if isinstance(raw, dict):
            blob = " ".join(
                str(raw.get(k) or "")
                for k in ("dayMode", "dayType", "message", "mode")
            ).upper()
        else:
            blob = str(raw or "").upper()
        if "WORST" in blob or "EXPIRY WORST" in blob:
            return True
    return False


def _post_small_win(state: Any) -> tuple[bool, dict[str, Any]]:
    """Last closed trade was a small green — size-up FOMO risk unless trail-proved."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if state is None:
        return False, meta
    try:
        from app.engines.pretrade_validator import collect_session_trades
    except Exception:
        return False, meta

    lookback = int(getattr(settings, "fake_explosion_trap_post_win_lookback", 1) or 1)
    trades = collect_session_trades(state)
    if not trades:
        return False, meta
    recent = trades[-lookback:]
    last = recent[-1]
    pnl = float(getattr(last, "pnl_inr", 0) or 0)
    reason = str(getattr(last, "exit_reason", "") or "").lower()
    max_pnl = float(
        getattr(settings, "fake_explosion_trap_post_win_max_pnl_inr", 3000.0) or 3000.0
    )
    meta = {
        "lastPnlInr": round(pnl, 2),
        "lastExitReason": reason,
    }
    if pnl <= 0:
        return False, meta
    # Trail / runner / target exits proved the move — allow normal size.
    if any(tok in reason for tok in ("trail", "runner", "target", "tp")):
        if pnl >= max_pnl:
            return False, meta
        # Small trail win still clamps — Jul20 +₹446 trail then 49-lot trap.
        meta["postSmallWin"] = True
        meta["trailProvedButSmall"] = True
        return True, meta
    if pnl < max_pnl:
        meta["postSmallWin"] = True
        return True, meta
    return False, meta


def _post_win_top_confidence_allows(
    candidate: Any,
    *,
    v3: float,
    snap: SymbolSnapshot,
) -> bool:
    """Post-win re-entry requires top rank, full sleeve, or hot live re-acceleration."""
    settings = get_settings()
    if not getattr(settings, "fake_explosion_trap_post_win_require_top_confidence", True):
        return True

    pre = getattr(candidate, "pretrade_meta", None) or {}
    causal = pre.get("causalRanking") or {}
    if causal.get("topRankEligible") or causal.get("fullSleeveEligible"):
        return True

    hot_v3 = float(
        getattr(settings, "fake_explosion_trap_post_win_hc_min_velocity_3s", 2.0) or 2.0
    )
    if v3 >= hot_v3:
        return True

    from app.engines.explosion_confidence import is_high_conviction_entry
    from app.engines.chart_exit_levels import chart_trade_confidence

    tier = str(
        getattr(getattr(candidate, "explosion_event", None), "tier", None)
        or getattr(candidate, "tier", "")
        or ""
    ).upper()
    move = float(getattr(getattr(candidate, "explosion_event", None), "daily_move_pct", 0) or 0)
    chart_conf, _ = chart_trade_confidence(
        snap, getattr(candidate, "side", None),
    )
    if is_high_conviction_entry(
        side=getattr(candidate, "side", None),
        snap=snap,
        tier=tier,
        score=float(getattr(candidate, "score", 0) or 0),
        move_pct=move,
        chart_confidence=chart_conf,
        velocity_3s=v3,
    ):
        return True
    return False


def detect_fake_explosion_trap(
    candidate: Any,
    snap: SymbolSnapshot,
    *,
    state: Any = None,
    premium_chart: Any = None,
    ict: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Detect FOMO / fake-rip explosion traps (Jul20 NIFTY 24300 CE).

    Returns (should_block, reason, meta).
    meta.action is "block" or "cut_size"; lotCap / psychologyEscalate when cutting.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"fakeExplosionTrap": False}
    if not getattr(settings, "fake_explosion_trap_enabled", True):
        return False, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", meta

    # Fake traps still apply on must-take / ELITE — FOMO stacks and flat
    # premium extensions are real losers even when the pad looks early.
    event = getattr(candidate, "explosion_event", None)
    tier = str(
        getattr(event, "tier", None)
        or getattr(candidate, "tier", "")
        or ""
    ).upper()
    v3 = float(getattr(event, "velocity_3s", 0) or 0) if event else 0.0
    move = _session_peak_move(event)
    if ict is not None:
        move = max(move, float(getattr(ict, "session_move_pct", 0) or 0))

    chop_regime = _regime_chopish(snap)
    midday = _midday_chop_active()
    chopish = chop_regime or midday
    elite_hot = tier in ("ELITE", "EXPLODING") and (
        v3 >= 2.0 or tier == "ELITE"
    )
    # "Extended" = chase territory past the early base window — NOT the entry min.
    # Using min_move (28%) here hard-blocked Jul15 ATM ELITE winners (32–45% moves).
    min_move = float(
        getattr(settings, "fake_explosion_trap_min_session_move_pct", 28.0) or 28.0
    )
    extended_move = float(
        getattr(settings, "fake_explosion_trap_extended_move_pct", 0) or 0
    )
    if extended_move <= 0:
        extended_move = float(
            getattr(settings, "explosion_early_window_max_move_pct", 65.0) or 65.0
        )
    local_pad = float(effective_local_base_move_pct(event, ict) or 0.0)
    local_max = float(
        getattr(settings, "explosion_local_base_chase_max_move_pct", 65.0) or 65.0
    )
    fresh_local_pad = 0 < local_pad <= local_max
    timing_move = local_pad if fresh_local_pad else move
    session_extended = move >= extended_move and not fresh_local_pad
    in_base_window = min_move <= timing_move < extended_move
    premium_flat = _premium_mom_flat(premium_chart)

    depth, money, atm = _strike_depth(candidate.side, float(candidate.strike), snap)
    from app.engines.moneyness import resolve_preferred_moneyness

    preferred = resolve_preferred_moneyness(
        "explosion", snap, candidate_score=float(getattr(candidate, "score", 0) or 0),
        side=candidate.side,
    )
    or_pos = _or_position(snap)
    otm_inside_or = (
        getattr(settings, "fake_explosion_trap_otm_requires_or_breakout", True)
        and money == "OTM"
        and preferred == "ATM"
        and or_pos == "INSIDE"
    )
    post_win, post_meta = _post_small_win(state)
    meta.update(post_meta)

    flags: list[str] = []
    if chop_regime:
        flags.append("chop_regime")
    if midday:
        flags.append("midday_chop")
    if elite_hot:
        flags.append("elite_hot")
    if session_extended:
        flags.append("session_extended")
    if in_base_window:
        flags.append("base_window")
    if premium_flat:
        flags.append("premium_flat")
    if otm_inside_or:
        flags.append("otm_inside_or")
    if post_win:
        flags.append("post_small_win")

    if post_win and getattr(
        settings, "fake_explosion_trap_post_win_velocity_block_enabled", True
    ):
        alert = getattr(candidate, "alert", None)
        from app.engines.early_radar_pad_capture import ict_base_armed_prelaunch_pad_lane

        armed_bypass = bool(
            getattr(
                settings,
                "fake_explosion_trap_post_win_armed_base_bypass_enabled",
                False,
            )
        )
        if (
            armed_bypass
            and isinstance(alert, dict)
            and ict_base_armed_prelaunch_pad_lane(alert)
        ):
            return False, "ok", meta
        min_v3 = float(
            getattr(settings, "fake_explosion_trap_post_win_min_velocity_3s", 0.0) or 0.0
        )
        if chopish:
            chop_min = float(
                getattr(
                    settings, "fake_explosion_trap_post_win_midday_min_velocity_3s", 1.0
                )
                or 1.0
            )
            min_v3 = max(min_v3, chop_min)
        if v3 <= min_v3:
            meta.update({
                "fakeExplosionTrap": True,
                "action": "block",
                "psychologyEscalate": "FOMO",
                "postWinVelocityBlock": True,
                "requiredMinVelocity3s": round(min_v3, 3),
                "liveVelocity3s": round(v3, 3),
            })
            return True, "fake_explosion_trap_post_win_cold_velocity", meta

    if post_win and not _post_win_top_confidence_allows(candidate, v3=v3, snap=snap):
        meta.update({
            "fakeExplosionTrap": True,
            "action": "block",
            "psychologyEscalate": "FOMO",
            "postWinTopConfidenceBlock": True,
            "liveVelocity3s": round(v3, 3),
        })
        return True, "fake_explosion_trap_post_win_not_top_confidence", meta

    meta.update({
        "fakeExplosionTrap": False,
        "conflictFlags": flags,
        "conflictCount": len(flags),
        "explosionTier": tier,
        "sessionMovePct": round(move, 2),
        "localBaseMovePct": round(local_pad, 2),
        "velocity3s": round(v3, 2),
        "moneyness": money,
        "preferredMoneyness": preferred,
        "orPosition": or_pos,
        "atmStrike": atm,
        "strikeStepsFromAtm": depth,
        "chopRegime": chop_regime,
        "middayChop": midday,
        "eliteHot": elite_hot,
        "premiumFlat": premium_flat,
    })

    if not flags:
        return False, "ok", meta

    lot_cap = int(
        getattr(settings, "fake_explosion_trap_chop_elite_lot_cap", 6) or 6
    )
    post_cap = int(
        getattr(settings, "fake_explosion_trap_post_win_lot_cap", 8) or 8
    )
    action = ""
    reason = ""
    psych = ""

    # Hard block: classic fake rip — extension already printed, premium cooled,
    # or OTM inside OR on chop with elite narrative.
    hard_block = False
    if getattr(settings, "fake_explosion_trap_block_on_conflict", True):
        if premium_flat and session_extended and (chopish or elite_hot):
            hard_block = True
            reason = "fake_explosion_trap_premium_flat_extension"
        elif otm_inside_or and chopish and elite_hot:
            hard_block = True
            reason = "fake_explosion_trap_otm_inside_or"
        elif (
            chopish
            and elite_hot
            and session_extended
            and otm_inside_or
            and post_win
        ):
            hard_block = True
            reason = "fake_explosion_trap_fomo_stack"
        elif (
            bool(getattr(settings, "fake_explosion_trap_block_worst_midday_chop", True))
            and chop_regime
            and midday
            and elite_hot
            and _worst_or_expiry_chop_day(snap, state)
        ):
            # Aug18 NIFTY 24250 PUT: armed-base EXPLODING on EXPIRY WORST + midday
            # chop only soft-capped to 6 lots, then failed_launch. Previously these
            # chop+elite stacks were stopped — restore hard block on worst/expiry.
            hard_block = True
            reason = "fake_explosion_trap_worst_midday_chop"
            meta["worstMiddayChopBlock"] = True
        else:
            min_flags = int(
                getattr(settings, "fake_explosion_trap_min_conflict_flags", 3) or 3
            )
            # Require chop + elite + at least one structural risk (extension/OTM/flat/post-win)
            structural = {
                "session_extended",
                "premium_flat",
                "otm_inside_or",
                "post_small_win",
            }
            structural_conflicts = structural.intersection(flags)
            if fresh_local_pad:
                # Flat premium alone is not an extension when the option is still close
                # to a confirmed local launch pad. OTM/post-win conflicts still apply.
                structural_conflicts.discard("premium_flat")
            if (
                len(flags) >= min_flags
                and (chop_regime or midday)
                and elite_hot
                and structural_conflicts
            ):
                hard_block = True
                reason = "fake_explosion_trap_conflict"

    if hard_block:
        meta.update({
            "fakeExplosionTrap": True,
            "action": "block",
            "psychologyEscalate": "FOMO" if post_win else "OVERCONFIDENCE",
        })
        return True, reason, meta

    # Midday/chop + elite narrative without ICT / local-base structure → hard block.
    # Soft lot-cap alone still let Jul23 displacement spikes through.
    structure_ok = _ict_structure_confirmed(ict)
    if not structure_ok:
        from app.engines.local_base_chart_bypass import local_base_structure_active

        alert = getattr(candidate, "alert", None)
        if not isinstance(alert, dict):
            alert = None
        structure_ok = local_base_structure_active(
            candidate.side,
            snap,
            event=event,
            alert=alert,
        )
        if structure_ok:
            meta["localBaseStructure"] = True
    if (
        getattr(settings, "fake_explosion_trap_midday_require_structure", True)
        and chopish
        and elite_hot
        and not structure_ok
    ):
        meta.update({
            "fakeExplosionTrap": True,
            "action": "block",
            "psychologyEscalate": "FOMO" if post_win else "OVERCONFIDENCE",
            "structureMissing": True,
        })
        return True, "fake_explosion_trap_midday_no_structure", meta

    # Soft cut: chop+elite full-size forbidden; post-small-win clamp.
    # Exception: structured base-window (28–55%) rips take full lots — soft-cutting
    # those to 6 lots killed Jul23 76300 PE and Jul31 NIFTY 24500 CE (2-step OTM).
    max_near_otm = int(
        getattr(settings, "moneyness_local_base_max_otm_steps", 3) or 3
    )
    near_otm_ok = bool(
        getattr(settings, "fake_explosion_trap_skip_soft_cut_near_otm", True)
    ) and money == "OTM" and depth <= max_near_otm and structure_ok
    skip_soft = bool(
        getattr(settings, "fake_explosion_trap_skip_soft_cut_base_window", True)
    ) and in_base_window and (
        money in ("ATM", "ITM") or near_otm_ok
    ) and not session_extended and not otm_inside_or
    if skip_soft:
        meta["baseWindowFullLots"] = True

    cut = False
    if chopish and elite_hot and not skip_soft:
        cut = True
        action = "cut_size"
        reason = "fake_explosion_trap_chop_elite_size"
        lot_cap = min(lot_cap, int(
            getattr(settings, "fake_explosion_trap_chop_elite_lot_cap", 6) or 6
        ))
        psych = "OVERCONFIDENCE"
    if post_win and not skip_soft:
        cut = True
        action = "cut_size"
        reason = reason or "fake_explosion_trap_post_win_size"
        lot_cap = min(lot_cap, post_cap) if chopish and elite_hot else post_cap
        psych = "FOMO" if psych != "OVERCONFIDENCE" else "OVERCONFIDENCE"

    if cut:
        if getattr(settings, "fake_explosion_trap_psychology_escalate", True):
            # Conflict stack escalates label even on soft cut.
            conflict_heavy = len(flags) >= 3 and chopish and elite_hot
            if conflict_heavy and post_win:
                psych = "FOMO"
            elif conflict_heavy:
                psych = psych or "OVERCONFIDENCE"
        meta.update({
            "fakeExplosionTrap": True,
            "action": action,
            "lotCap": lot_cap,
            "psychologyEscalate": psych or None,
        })
        # Soft cut does not block entry — open path applies lotCap.
        return False, reason, meta

    return False, "ok", meta


def _trap_soft_cap_must_honor(trap_meta: dict[str, Any]) -> bool:
    """Chop/worst conflict stacks must keep cut_size lotCap (Aug6 27→6 restore hole)."""
    settings = get_settings()
    if not getattr(settings, "fake_explosion_trap_honor_soft_cap_on_chop", True):
        return False
    if trap_meta.get("action") != "cut_size":
        return False
    flags = {
        str(f).lower()
        for f in (trap_meta.get("conflictFlags") or [])
        if f is not None
    }
    chopish = bool(
        trap_meta.get("chopRegime")
        or trap_meta.get("middayChop")
        or "chop_regime" in flags
        or "midday_chop" in flags
    )
    elite_hot = bool(trap_meta.get("eliteHot") or "elite_hot" in flags)
    return chopish and (elite_hot or int(trap_meta.get("conflictCount") or 0) >= 3)


def cap_fake_explosion_trap_lots(
    lots: int,
    trap_meta: Optional[dict[str, Any]],
    *,
    bypass_soft_cap: bool = False,
) -> int:
    """Apply trap lot cap after good-day max-lot force (Jul20 49-lot hole)."""
    if not trap_meta or not trap_meta.get("fakeExplosionTrap"):
        return lots
    if trap_meta.get("action") == "block":
        return 0
    # Chop/worst cut_size always wins over baseWindowFullLots / HC soft bypass.
    if _trap_soft_cap_must_honor(trap_meta):
        bypass_soft_cap = False
    # High-conviction / elevated ATM base rips keep max lots; hard block still wins.
    if bypass_soft_cap and trap_meta.get("action") == "cut_size":
        return lots
    cap = trap_meta.get("lotCap")
    if cap is None:
        return lots
    return min(max(0, lots), int(cap))
