"""True peak prediction — index impulse × gamma, historical analogues, live ratchet.

Three layers blended at entry for NIFTY and SENSEX:
  1. Index impulse → expected option move (per-strike delta/gamma when available)
  2. Historical analogue MFE (learned EOD profiles + pattern match)
  3. Structure projection (existing moment_stage_trail) + live ratchet on the runner

Stamped on entryContext as predictedMaxLtp / predictedMaxMovePct / peakPrediction meta.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from app.config import Settings, get_settings
from app.models.schemas import PaperTrade, Side, SymbolSnapshot

SUPPORTED_INDEX_SYMBOLS = frozenset({"NIFTY", "SENSEX"})


def _num(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value or default)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return x


def _side_u(side: Any) -> str:
    if isinstance(side, Side):
        return side.value.upper()
    return str(side or "").upper()


def _moment_type_from_evidence(
    *,
    alert: Optional[Mapping[str, Any]] = None,
    ict: Any = None,
) -> str:
    if alert:
        if alert.get("ictVRipReady") or alert.get("vRipReady"):
            return "V"
        if alert.get("ictFlatThenVertical") or alert.get("flatThenVertical"):
            return "FTV"
        if alert.get("ictArmedBaseLaunch") or alert.get("armedBaseLaunch"):
            return "ARMED_BASE"
        if alert.get("ictFirstLift") or alert.get("firstLift"):
            return "FIRST_LIFT"
        if alert.get("ictBuildingRipReady") or alert.get("buildingRipReady"):
            return "BUILDING_RIP"
    if ict is not None:
        if bool(getattr(ict, "v_rip_ready", False)):
            return "V"
        if bool(getattr(ict, "flat_then_vertical", False)):
            return "FTV"
        if bool(getattr(ict, "armed_base_launch", False)):
            return "ARMED_BASE"
        if bool(getattr(ict, "first_lift", False)):
            return "FIRST_LIFT"
    tier = str((alert or {}).get("tier") or getattr(ict, "tier", "") or "").upper()
    if tier in ("ELITE", "EXPLODING"):
        return tier
    return "FTV"


def resolve_strike_greeks(
    symbol: str,
    side: Any,
    strike: float,
    snap: Optional[SymbolSnapshot],
    *,
    chain: Optional[list[dict[str, Any]]] = None,
) -> dict[str, float]:
    """Per-strike delta/gamma — chain leg first, else moneyness-scaled ATM from snapshot."""
    side_v = _side_u(side)
    sym = str(symbol or "").upper()
    out = {"delta": 0.45, "gamma": 0.002, "source": "default"}

    if chain:
        for row in chain:
            row_strike = _num(row.get("strike_price") or row.get("strike"))
            if abs(row_strike - float(strike)) > 1e-6:
                continue
            leg = (row.get("put_options") if side_v == "PUT" else row.get("call_options")) or {}
            g = leg.get("greeks") or {}
            delta = _num(g.get("delta"), 0.0)
            gamma = _num(g.get("gamma"), 0.0)
            if delta != 0.0 or gamma != 0.0:
                out = {
                    "delta": abs(delta) if side_v == "PUT" else delta,
                    "gamma": abs(gamma) if gamma else 0.002,
                    "rawDelta": delta,
                    "source": "chain",
                }
                return out

    if snap is None:
        return out

    g = getattr(snap, "greeks", None)
    atm_delta = abs(_num(getattr(g, "delta", 0.45), 0.45))
    atm_gamma = _num(getattr(g, "gamma", 0.002), 0.002)
    spot = _num(getattr(snap, "spot", 0) or getattr(snap, "atmStrike", 0))
    if spot <= 0:
        out = {"delta": atm_delta, "gamma": atm_gamma, "source": "snap_atm"}
        return out

    from app.engines.moneyness import strike_step

    step = max(1.0, _num(strike_step(sym), 50.0))
    if side_v == "CALL":
        steps_otm = (float(strike) - spot) / step
        scale = max(0.25, 1.0 - 0.08 * max(0.0, steps_otm))
    else:
        steps_otm = (spot - float(strike)) / step
        scale = max(0.25, 1.0 - 0.08 * max(0.0, steps_otm))

    out = {
        "delta": round(min(0.95, atm_delta * scale), 4),
        "gamma": round(max(0.0005, atm_gamma * (1.0 + 0.15 * max(0.0, -steps_otm))), 6),
        "source": "snap_scaled",
        "moneynessStepsOtm": round(steps_otm, 2),
    }
    return out


def index_impulse_projection(
    symbol: str,
    side: Any,
    snap: Optional[SymbolSnapshot],
    *,
    alert: Optional[Mapping[str, Any]] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Expected index move (pts / %) from live tick drift, velocity, and spike thrust."""
    s = settings or get_settings()
    sym = str(symbol or "").upper()
    side_v = _side_u(side)
    spot = _num(getattr(snap, "spot", 0) if snap else 0)
    horizon = float(getattr(s, "peak_prediction_impulse_horizon_seconds", 90.0) or 90.0)

    drift_pts = 0.0
    drift_pct = 0.0
    v3 = 0.0
    v9 = 0.0
    helpers: list[str] = []

    if sym in SUPPORTED_INDEX_SYMBOLS:
        try:
            from app.engines.index_tick_helpers import (
                evaluate_index_tick_helpers,
                recent_index_drift,
            )

            drift = recent_index_drift(sym, side_v)
            drift_pts = _num(drift.get("pts"))
            drift_pct = _num(drift.get("net_pct"))
            if snap is not None:
                board = evaluate_index_tick_helpers(snap=snap, side=side_v, alert=alert)
                v3 = _num(board.velocity_3s)
                v9 = _num(board.velocity_9s)
                helpers = list(board.helpers or [])
        except Exception:
            pass

    if alert:
        v3 = v3 or _num(alert.get("indexSpotMove3s"))
        v9 = v9 or _num(alert.get("indexSpotMove9s"))
        if not drift_pts and alert.get("indexDriftNetPct") is not None and spot > 0:
            drift_pct = _num(alert.get("indexDriftNetPct"))
            drift_pts = spot * drift_pct / 100.0

    # Project index continuation over the impulse horizon from 3s/9s velocity.
    vel_pts_3s = abs(v3) * spot if spot > 0 else 0.0
    vel_pts_9s = abs(v9) * spot * 0.33 if spot > 0 else 0.0
    horizon_scale = max(1.0, horizon / 3.0)
    velocity_pts = max(vel_pts_3s, vel_pts_9s) * min(horizon_scale, 8.0)

    # Same-direction impulse only.
    signed_drift = drift_pts
    if side_v == "PUT" and signed_drift > 0:
        signed_drift = -signed_drift
    elif side_v == "CALL" and signed_drift < 0:
        signed_drift = abs(signed_drift)

    impulse_pts = max(abs(signed_drift), velocity_pts)
    if side_v == "PUT":
        impulse_pts = -impulse_pts
    elif side_v == "CALL":
        impulse_pts = abs(impulse_pts)

    impulse_pct = (impulse_pts / spot * 100.0) if spot > 0 else 0.0
    # Symbol-specific caps — SENSEX moves wider in points than NIFTY.
    max_pts = float(getattr(s, "peak_prediction_sensex_max_impulse_pts", 180.0) or 180.0)
    if sym == "NIFTY":
        max_pts = float(getattr(s, "peak_prediction_nifty_max_impulse_pts", 120.0) or 120.0)
    impulse_pts = max(-max_pts, min(max_pts, impulse_pts))

    return {
        "symbol": sym,
        "side": side_v,
        "spot": round(spot, 2),
        "horizonSeconds": horizon,
        "driftPts": round(drift_pts, 2),
        "driftPct": round(drift_pct, 4),
        "velocity3s": round(v3, 4),
        "velocity9s": round(v9, 4),
        "impulsePts": round(impulse_pts, 2),
        "impulsePct": round(impulse_pct, 4),
        "indexHelpers": helpers,
        "confidence": round(
            min(
                1.0,
                0.25
                + (0.25 if drift_pts else 0.0)
                + (0.25 if abs(v3) > 0.02 else 0.0)
                + (0.15 if "index_spike_burst" in helpers or "index_drift" in helpers else 0.0),
            ),
            3,
        ),
    }


def gamma_premium_projection(
    *,
    entry_premium: float,
    impulse_pts: float,
    delta: float,
    gamma: float,
    side: Any,
) -> dict[str, Any]:
    """Taylor expansion: dPremium ≈ |delta|×dSpot + 0.5×gamma×dSpot² (signed for side)."""
    entry = max(_num(entry_premium), 1e-6)
    side_v = _side_u(side)
    d_spot = _num(impulse_pts)

    # PUT benefits from index down (negative d_spot); CALL from index up.
    if side_v == "PUT" and d_spot > 0:
        d_spot = -d_spot
    elif side_v == "CALL" and d_spot < 0:
        d_spot = abs(d_spot)

    eff_delta = abs(_num(delta, 0.45))
    eff_gamma = max(_num(gamma, 0.002), 1e-6)
    linear = eff_delta * abs(d_spot)
    convex = 0.5 * eff_gamma * (d_spot ** 2)
    premium_move_pts = linear + convex
    predicted_premium = entry + premium_move_pts
    move_pct = premium_move_pts / entry * 100.0

    return {
        "linearPts": round(linear, 2),
        "convexPts": round(convex, 2),
        "premiumMovePts": round(premium_move_pts, 2),
        "predictedPremium": round(predicted_premium, 2),
        "movePct": round(move_pct, 2),
        "deltaUsed": round(eff_delta, 4),
        "gammaUsed": round(eff_gamma, 6),
    }


def historical_analogue_peak(
    symbol: str,
    side: Any,
    tier: str,
    moment_type: str,
    *,
    base_rel_pct: float = 0.0,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Last-N similar V/FTV/ELITE moments — learned EOD profile + pattern key fallback."""
    s = settings or get_settings()
    sym = str(symbol or "").upper()
    side_v = _side_u(side)
    tier_u = str(tier or "OTHER").upper()
    moment = str(moment_type or "FTV").upper()

    if sym not in SUPPORTED_INDEX_SYMBOLS:
        return {"available": False, "reason": "unsupported_symbol"}

    from app.engines.eod_ftv_learning import learned_ftv_profile, load_learned_params

    store = load_learned_params()
    profiles = store.get("profiles") or {}
    keys_to_try = [
        f"{sym}:{side_v}:{tier_u}:{moment}",
        f"{sym}:{side_v}:{tier_u}",
        f"{sym}:{side_v}:OTHER",
    ]
    profile: dict[str, Any] = {}
    matched_key = ""
    for key in keys_to_try:
        if ":" in key and key.count(":") >= 3:
            prof = dict(profiles.get(key) or {})
        else:
            parts = key.split(":")
            prof = learned_ftv_profile(parts[0], parts[1], parts[2]) if len(parts) >= 3 else {}
        if prof and int(prof.get("count") or 0) > 0:
            profile = prof
            matched_key = key
            break

    if not profile:
        return {
            "available": False,
            "reason": "no_learned_profile",
            "keysTried": keys_to_try,
        }

    median_mfe = _num(profile.get("medianPeakPct"))
    p25_mfe = _num(profile.get("p25PeakPct"))
    p75_mfe = _num(profile.get("p75PeakPct", median_mfe * 1.15))
    count = int(profile.get("count") or 0)
    min_samples = int(getattr(s, "peak_prediction_analogue_min_samples", 3) or 3)

    # Earlier entry off base → more runway to historical median peak.
    pad = max(0.0, _num(base_rel_pct))
    runway_mult = 1.0 + max(0.0, (20.0 - min(pad, 20.0)) / 100.0)
    predicted_pct = median_mfe * runway_mult
    conservative_pct = p25_mfe * runway_mult if p25_mfe > 0 else predicted_pct * 0.75
    stretch_pct = p75_mfe * runway_mult if p75_mfe > 0 else predicted_pct * 1.2

    return {
        "available": count >= min_samples,
        "matchedKey": matched_key,
        "sampleCount": count,
        "medianMfePct": round(median_mfe, 2),
        "p25MfePct": round(conservative_pct, 2),
        "p75MfePct": round(stretch_pct, 2),
        "predictedMovePct": round(predicted_pct, 2),
        "hitRate": _num(profile.get("hitRate")),
        "runwayMultiplier": round(runway_mult, 3),
    }


def predict_peak(
    *,
    symbol: str,
    side: Any,
    strike: float,
    entry_premium: float,
    snap: Optional[SymbolSnapshot],
    tier: str = "",
    base_premium: float = 0.0,
    base_rel_pct: float = 0.0,
    alert: Optional[Mapping[str, Any]] = None,
    ict: Any = None,
    exit_plan: Optional[dict[str, Any]] = None,
    velocity_3s: float = 0.0,
    volume_surge: float = 1.0,
    session_move_pct: float = 0.0,
    flat_then_vertical: bool = False,
    mega_rip: bool = False,
    premium_fvg: bool = False,
    max_profit: bool = False,
    chain: Optional[list[dict[str, Any]]] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Blend gamma impulse, historical analogue, and structure projection into peak forecast."""
    s = settings or get_settings()
    if not bool(getattr(s, "peak_prediction_enabled", True)):
        return {"enabled": False}

    sym = str(symbol or "").upper()
    if sym not in SUPPORTED_INDEX_SYMBOLS:
        return {"enabled": False, "reason": "unsupported_symbol"}

    entry = max(_num(entry_premium), 1e-6)
    moment_type = _moment_type_from_evidence(alert=alert, ict=ict)
    tier_u = str(tier or (alert or {}).get("tier") or getattr(ict, "tier", "") or "OTHER").upper()

    greeks = resolve_strike_greeks(sym, side, strike, snap, chain=chain)
    impulse = index_impulse_projection(sym, side, snap, alert=alert, settings=s)
    gamma = gamma_premium_projection(
        entry_premium=entry,
        impulse_pts=_num(impulse.get("impulsePts")),
        delta=_num(greeks.get("delta")),
        gamma=_num(greeks.get("gamma")),
        side=side,
    )
    analogue = historical_analogue_peak(
        sym, side, tier_u, moment_type, base_rel_pct=base_rel_pct, settings=s
    )

    from app.engines.moment_stage_trail import compute_projected_max_tp

    structure_pts = compute_projected_max_tp(
        entry_premium=entry,
        base_premium=base_premium,
        exit_plan=exit_plan,
        velocity_3s=velocity_3s,
        volume_surge=volume_surge,
        session_move_pct=session_move_pct,
        premium_fvg=premium_fvg,
        flat_then_vertical=flat_then_vertical,
        mega_rip=mega_rip,
        max_profit=max_profit,
        settings=s,
    )
    structure_pct = structure_pts / entry * 100.0

    w_gamma = float(getattr(s, "peak_prediction_gamma_weight", 0.35) or 0.35)
    w_analogue = float(getattr(s, "peak_prediction_analogue_weight", 0.40) or 0.40)
    w_structure = float(getattr(s, "peak_prediction_structure_weight", 0.25) or 0.25)

    components: list[tuple[str, float, float]] = [
        ("gamma", _num(gamma.get("movePct")), w_gamma),
        ("structure", structure_pct, w_structure),
    ]
    if analogue.get("available"):
        components.append(("analogue", _num(analogue.get("predictedMovePct")), w_analogue))
    else:
        # Redistribute analogue weight to gamma + structure when no history.
        w_gamma += w_analogue * 0.55
        w_structure += w_analogue * 0.45
        components = [
            ("gamma", _num(gamma.get("movePct")), w_gamma),
            ("structure", structure_pct, w_structure),
        ]

    total_w = sum(c[2] for c in components) or 1.0
    blended_pct = sum(c[1] * c[2] for c in components) / total_w

    min_pct = float(getattr(s, "peak_prediction_min_move_pct", 15.0) or 15.0)
    max_pct = float(getattr(s, "peak_prediction_max_move_pct", 250.0) or 250.0)
    if sym == "SENSEX":
        max_pct = float(getattr(s, "peak_prediction_sensex_max_move_pct", 300.0) or 300.0)

    blended_pct = max(min_pct, min(max_pct, blended_pct))
    stretch_pct = blended_pct
    if analogue.get("available"):
        stretch_pct = max(blended_pct, _num(analogue.get("p75MfePct")))

    predicted_max_ltp = round(entry * (1.0 + stretch_pct / 100.0), 2)
    predicted_pts = round(predicted_max_ltp - entry, 2)
    conservative_ltp = round(entry * (1.0 + max(min_pct, blended_pct * 0.7) / 100.0), 2)

    confidence = round(
        min(
            1.0,
            _num(impulse.get("confidence")) * 0.35
            + (0.35 if analogue.get("available") else 0.1)
            + min(0.3, structure_pct / 200.0),
        ),
        3,
    )

    return {
        "enabled": True,
        "symbol": sym,
        "side": _side_u(side),
        "strike": float(strike),
        "momentType": moment_type,
        "tier": tier_u,
        "entryPremium": round(entry, 2),
        "predictedMaxLtp": predicted_max_ltp,
        "predictedMaxMovePct": round(stretch_pct, 2),
        "predictedMaxTpPoints": predicted_pts,
        "predictedConservativeLtp": conservative_ltp,
        "predictedConservativeMovePct": round((conservative_ltp - entry) / entry * 100.0, 2),
        "confidence": confidence,
        "components": {
            "gamma": gamma,
            "impulse": impulse,
            "greeks": greeks,
            "analogue": analogue,
            "structureTpPoints": structure_pts,
            "structureMovePct": round(structure_pct, 2),
            "blendWeights": {name: round(w, 3) for name, _, w in components},
            "blendedMovePct": round(blended_pct, 2),
        },
    }


def stamp_peak_prediction_on_context(
    ctx: dict[str, Any],
    prediction: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge peak prediction fields into entry context + exit plan."""
    if not prediction or not prediction.get("enabled"):
        return ctx
    out = dict(ctx)
    out["peakPrediction"] = {
        "predictedMaxLtp": prediction.get("predictedMaxLtp"),
        "predictedMaxMovePct": prediction.get("predictedMaxMovePct"),
        "predictedMaxTpPoints": prediction.get("predictedMaxTpPoints"),
        "predictedConservativeLtp": prediction.get("predictedConservativeLtp"),
        "confidence": prediction.get("confidence"),
        "momentType": prediction.get("momentType"),
        "components": prediction.get("components"),
    }
    out["predictedMaxLtp"] = prediction.get("predictedMaxLtp")
    out["predictedMaxMovePct"] = prediction.get("predictedMaxMovePct")
    out["predictedMaxTpPoints"] = prediction.get("predictedMaxTpPoints")

    # Lift structure projection when prediction sees more runway.
    pred_pts = _num(prediction.get("predictedMaxTpPoints"))
    if pred_pts > _num(out.get("projectedMaxTp")):
        out["projectedMaxTp"] = pred_pts
    plan = dict(out.get("exitPlan") or {})
    if pred_pts > _num(plan.get("projectedMaxTp")):
        plan["projectedMaxTp"] = pred_pts
        plan["peakPrediction"] = out["peakPrediction"]
        out["exitPlan"] = plan
    return out


def ratchet_toward_predicted_peak(
    trade: PaperTrade,
    best: float,
    *,
    settings: Optional[Settings] = None,
) -> float:
    """Live ratchet layer 3 — extend projectedMaxTp toward predicted peak while hot."""
    s = settings or get_settings()
    if not bool(getattr(s, "peak_prediction_enabled", True)):
        return 0.0
    if not bool(getattr(s, "peak_prediction_live_ratchet_enabled", True)):
        return 0.0

    ctx = trade.entryContext or {}
    pred_pts = _num(ctx.get("predictedMaxTpPoints"))
    pred_ltp = _num(ctx.get("predictedMaxLtp"))
    entry = _num(getattr(trade, "entryPremium", 0))
    if pred_pts <= 0 and pred_ltp > 0 and entry > 0:
        pred_pts = pred_ltp - entry
    if pred_pts <= 0:
        return _num(ctx.get("projectedMaxTp"))

    current = _num(ctx.get("projectedMaxTp"))
    trigger = float(getattr(s, "peak_prediction_ratchet_trigger_frac", 0.85) or 0.85)
    if best < current * trigger and best < pred_pts * trigger:
        return current

    live_v = _num(ctx.get("liveVelocity3s") or ctx.get("velocity3s"))
    hot_v = float(getattr(s, "peak_prediction_ratchet_hot_velocity_3s", 2.0) or 2.0)
    hot = live_v >= hot_v or bool(ctx.get("ictMegaRip"))

    target_pts = pred_pts
    if hot:
        stretch = float(getattr(s, "peak_prediction_ratchet_hot_stretch", 1.12) or 1.12)
        target_pts = pred_pts * stretch

    abs_cap = float(getattr(s, "moment_stage_max_projected_tp", 800.0) or 800.0)
    new_pts = round(min(abs_cap, max(current, best + max(target_pts - best, 0) * 0.5)), 1)

    if trade.entryContext is None:
        trade.entryContext = {}
    trade.entryContext["projectedMaxTp"] = new_pts
    trade.entryContext["peakPredictionRatchetPts"] = new_pts
    plan = dict(trade.entryContext.get("exitPlan") or {})
    plan["projectedMaxTp"] = new_pts
    trade.entryContext["exitPlan"] = plan
    return new_pts
