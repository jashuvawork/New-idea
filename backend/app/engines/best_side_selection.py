"""Best-side selection — follow the dominant CE/PE leg all session.

When one option side is clearly surging (velocity + score), waive sticky
directional lock, power-hour top-only blocks, and rank penalties so the bot
can flip PUT morning → CALL afternoon (or the reverse) without waiting for
five independent chart confirmations.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _side_str(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _effective_thresholds(*, power_hour: bool = False) -> tuple[float, float, float]:
    settings = get_settings()
    if power_hour:
        vel_min = float(
            getattr(settings, "best_side_power_hour_min_velocity_3s", 1.8) or 1.8
        )
        vel_ratio = float(
            getattr(settings, "best_side_power_hour_min_velocity_ratio", 1.3) or 1.3
        )
    else:
        vel_min = float(getattr(settings, "best_side_min_velocity_3s", 2.0) or 2.0)
        vel_ratio = float(
            getattr(settings, "best_side_min_velocity_ratio", 1.4) or 1.4
        )
    score_min = float(
        getattr(settings, "best_side_min_explosion_score", 45.0) or 45.0
    )
    return vel_min, vel_ratio, score_min


def side_velocity_metrics(snap: SymbolSnapshot) -> dict[str, Any]:
    """Aggregate per-side velocity and explosion score from live radar."""
    call_v3 = put_v3 = 0.0
    call_score = put_score = 0.0

    for entry in snap.explosiveRunnerWatchlist or []:
        side = _side_str(entry.get("side", ""))
        vel = float(entry.get("premiumVelocityPct", 0) or 0)
        score = float(entry.get("score", 0) or 0)
        if side == "CALL":
            call_v3 = max(call_v3, vel)
            call_score = max(call_score, score)
        elif side == "PUT":
            put_v3 = max(put_v3, vel)
            put_score = max(put_score, score)

    for alert in snap.explosionAlerts or []:
        side = _side_str(alert.get("side", ""))
        v3 = float(alert.get("velocity3s", 0) or 0)
        score = float(alert.get("explosionScore", 0) or 0)
        if side == "CALL":
            call_v3 = max(call_v3, v3)
            call_score = max(call_score, score)
        elif side == "PUT":
            put_v3 = max(put_v3, v3)
            put_score = max(put_score, score)

    top = snap.topExplosion or {}
    top_side = _side_str(top.get("side", ""))
    top_v3 = float(top.get("velocity3s", 0) or 0)
    top_score = float(top.get("explosionScore", 0) or 0)
    if top_side == "CALL":
        call_v3 = max(call_v3, top_v3)
        call_score = max(call_score, top_score)
    elif top_side == "PUT":
        put_v3 = max(put_v3, top_v3)
        put_score = max(put_score, top_score)

    runner = snap.explosiveRunner
    if runner and runner.side:
        rs = _side_str(runner.side)
        rv = float(getattr(runner.signal, "premiumVelocityPct", 0) or 0) if runner.signal else 0.0
        rscore = float(runner.score or 0)
        if rs == "CALL":
            call_v3 = max(call_v3, rv)
            call_score = max(call_score, rscore)
        elif rs == "PUT":
            put_v3 = max(put_v3, rv)
            put_score = max(put_score, rscore)

    if call_v3 >= put_v3 and (call_v3 > 0 or call_score >= put_score):
        dominant = "CALL"
        dominant_v3 = call_v3
        weaker_v3 = put_v3
        dominant_score = call_score
    elif put_v3 > call_v3 or put_score > call_score:
        dominant = "PUT"
        dominant_v3 = put_v3
        weaker_v3 = call_v3
        dominant_score = put_score
    else:
        dominant = ""
        dominant_v3 = weaker_v3 = 0.0
        dominant_score = 0.0

    ratio = dominant_v3 / weaker_v3 if weaker_v3 > 0.05 else (999.0 if dominant_v3 > 0 else 0.0)

    return {
        "callVelocity3s": round(call_v3, 3),
        "putVelocity3s": round(put_v3, 3),
        "callScore": round(call_score, 2),
        "putScore": round(put_score, 2),
        "dominantSide": dominant,
        "dominantVelocity3s": round(dominant_v3, 3),
        "weakerVelocity3s": round(weaker_v3, 3),
        "dominantScore": round(dominant_score, 2),
        "velocityRatio": round(ratio, 2),
    }


def _metrics_pass_dominance(
    metrics: dict[str, Any],
    side_v: str,
    *,
    power_hour: bool = False,
    candidate: Any = None,
) -> tuple[bool, dict[str, Any]]:
    settings = get_settings()
    if not bool(getattr(settings, "best_side_selection_enabled", True)):
        return False, {"reason": "disabled"}

    dominant = str(metrics.get("dominantSide") or "")
    if not dominant or dominant != side_v:
        return False, {"reason": "not_dominant_side", **metrics}

    vel_min, vel_ratio, score_min = _effective_thresholds(power_hour=power_hour)
    dom_v3 = float(metrics.get("dominantVelocity3s") or 0)
    ratio = float(metrics.get("velocityRatio") or 0)
    dom_score = float(metrics.get("dominantScore") or 0)

    cand_v3 = cand_score = 0.0
    if candidate is not None:
        ev = getattr(candidate, "explosion_event", None)
        if ev is not None:
            cand_v3 = float(getattr(ev, "velocity_3s", 0) or 0)
            cand_score = float(getattr(ev, "explosion_score", 0) or 0)
        alert = getattr(candidate, "alert", None)
        if isinstance(alert, dict):
            cand_v3 = max(cand_v3, float(alert.get("velocity3s", 0) or 0))
            cand_score = max(cand_score, float(alert.get("explosionScore", 0) or 0))

    effective_v3 = max(dom_v3, cand_v3)
    effective_score = max(dom_score, cand_score)

    velocity_ok = effective_v3 >= vel_min and (
        ratio >= vel_ratio or float(metrics.get("weakerVelocity3s") or 0) <= 0.05
    )
    score_ok = effective_score >= score_min

    from app.engines.morning_premium_capture import dominant_single_side_surge

    surge_ok = dominant_single_side_surge(metrics.get("_snap")) if metrics.get("_snap") else False

    if velocity_ok or score_ok or surge_ok:
        return True, {
            "dominantSide": dominant,
            "velocityOk": velocity_ok,
            "scoreOk": score_ok,
            "surgeOk": surge_ok,
            "effectiveVelocity3s": round(effective_v3, 3),
            "effectiveScore": round(effective_score, 2),
            **metrics,
        }
    return False, {
        "reason": "below_thresholds",
        "velocityOk": velocity_ok,
        "scoreOk": score_ok,
        "requiredVelocity": vel_min,
        "requiredRatio": vel_ratio,
        "requiredScore": score_min,
        **metrics,
    }


def resolve_dominant_side(
    snap: SymbolSnapshot,
    *,
    power_hour: bool = False,
    side_v: str = "",
    candidate: Any = None,
) -> tuple[Optional[str], dict[str, Any]]:
    """Return CALL/PUT when that side clearly dominates on this symbol."""
    metrics = side_velocity_metrics(snap)
    metrics["_snap"] = snap
    if side_v:
        ok, meta = _metrics_pass_dominance(
            metrics, side_v.upper(), power_hour=power_hour, candidate=candidate,
        )
        if ok:
            return side_v.upper(), meta
        return None, meta

    dominant = str(metrics.get("dominantSide") or "")
    if not dominant:
        return None, {**metrics, "reason": "no_dominant_side"}
    ok, meta = _metrics_pass_dominance(
        metrics, dominant, power_hour=power_hour, candidate=candidate,
    )
    if ok:
        return dominant, meta
    return None, meta


def side_is_dominant(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    power_hour: bool = False,
    candidate: Any = None,
) -> tuple[bool, dict[str, Any]]:
    side_v = _side_str(side)
    resolved, meta = resolve_dominant_side(
        snap, power_hour=power_hour, side_v=side_v, candidate=candidate,
    )
    return resolved == side_v, meta


def dominant_side_flip_bypass(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    candidate: Any = None,
    power_hour: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """True when sticky lock should yield to the live dominant leg."""
    _ = symbol
    settings = get_settings()
    if not bool(getattr(settings, "best_side_selection_enabled", True)):
        return False, "disabled", {}
    if not bool(getattr(settings, "best_side_directional_lock_bypass_enabled", True)):
        return False, "directional_bypass_off", {}

    side_v = _side_str(side)
    ok, meta = side_is_dominant(side_v, snap, power_hour=power_hour, candidate=candidate)
    if ok:
        return True, "best_side_dominant", meta

    if candidate is not None:
        from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

        ev = getattr(candidate, "explosion_event", None)
        if ev is not None and qualifies_for_vertical_rip_bypass(ev, snap=snap):
            metrics = side_velocity_metrics(snap)
            if metrics.get("dominantSide") == side_v:
                return True, "best_side_vertical_rip", metrics

    return False, meta.get("reason", "not_dominant"), meta


def dominant_side_qualifies_power_hour(candidate: Any) -> bool:
    """Power hour: dominant-side BUILDING/EXPLODING with live surge counts as top."""
    settings = get_settings()
    if not bool(getattr(settings, "best_side_power_hour_bypass_enabled", True)):
        return False
    snap = getattr(candidate, "snap", None)
    if snap is None or not snap.dataAvailable:
        return False

    side = getattr(candidate, "side", None)
    if side is None:
        return False

    ok, _ = side_is_dominant(side, snap, power_hour=True, candidate=candidate)
    if not ok:
        return False

    ev = getattr(candidate, "explosion_event", None)
    tier = str(getattr(ev, "tier", "") or getattr(candidate, "tier", "") or "").upper()
    if tier not in ("BUILDING", "EXPLODING", "ELITE", "WATCH"):
        return False

    vel_min, _, score_min = _effective_thresholds(power_hour=True)
    v3 = float(getattr(ev, "velocity_3s", 0) or 0) if ev else 0.0
    score = float(getattr(ev, "explosion_score", 0) or getattr(candidate, "score", 0) or 0)
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        v3 = max(v3, float(alert.get("velocity3s", 0) or 0))
        score = max(score, float(alert.get("explosionScore", 0) or 0))

    return v3 >= vel_min * 0.85 or score >= score_min - 5.0


def snapshots_have_dominant_side_surge(
    snapshots: dict[str, SymbolSnapshot],
    *,
    power_hour: bool = False,
) -> bool:
    """Session lift when any symbol shows a clear one-sided surge."""
    settings = get_settings()
    if not bool(getattr(settings, "best_side_selection_enabled", True)):
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        dom, _ = resolve_dominant_side(snap, power_hour=power_hour)
        if dom:
            return True
    return False


def resolve_global_best_side(
    snapshots: dict[str, SymbolSnapshot],
    *,
    power_hour: bool = False,
) -> tuple[str, str, float, dict[str, Any]]:
    """Best (symbol, side) tuple across all indices by velocity × score."""
    best_rank = 0.0
    best_sym = ""
    best_side = ""
    best_meta: dict[str, Any] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        dom, meta = resolve_dominant_side(snap, power_hour=power_hour)
        if not dom:
            continue
        rank = float(meta.get("effectiveVelocity3s") or meta.get("dominantVelocity3s") or 0) * 10.0
        rank += float(meta.get("effectiveScore") or meta.get("dominantScore") or 0)
        if rank > best_rank:
            best_rank = rank
            best_sym = sym.upper()
            best_side = dom
            best_meta = meta
    return best_sym, best_side, best_rank, best_meta


def best_side_rank_adjustment(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    *,
    power_hour: bool = False,
) -> float:
    """Boost dominant-leg candidates; penalize clearly counter-dominant entries."""
    settings = get_settings()
    if not bool(getattr(settings, "best_side_selection_enabled", True)):
        return 0.0
    snap = getattr(candidate, "snap", None) or snapshots.get(
        str(getattr(candidate, "symbol", "") or "").upper()
    )
    if snap is None or not snap.dataAvailable:
        return 0.0

    side_val = _side_str(getattr(candidate, "side", "") or "")
    ok, _ = side_is_dominant(
        side_val, snap, power_hour=power_hour, candidate=candidate,
    )
    adj = 0.0
    if ok:
        adj += float(getattr(settings, "best_side_rank_bonus", 25.0) or 25.0)

    global_sym, global_side, _, _ = resolve_global_best_side(
        snapshots, power_hour=power_hour,
    )
    sym_u = str(getattr(candidate, "symbol", "") or "").upper()
    if global_sym and global_side == side_val and sym_u == global_sym:
        adj += float(getattr(settings, "best_side_global_rank_bonus", 15.0) or 15.0)
    elif global_side and global_side != side_val:
        metrics = side_velocity_metrics(snap)
        if metrics.get("dominantSide") and metrics.get("dominantSide") != side_val:
            adj -= float(
                getattr(settings, "best_side_counter_rank_penalty", 18.0) or 18.0
            )
    return adj


def best_side_fading_rank_waive(
    candidate: Any,
    snap: SymbolSnapshot,
) -> float:
    """Offset bad-day fading penalty when candidate is the live dominant leg."""
    settings = get_settings()
    if not bool(getattr(settings, "best_side_selection_enabled", True)):
        return 0.0
    side_val = _side_str(getattr(candidate, "side", "") or "")
    ok, _ = side_is_dominant(side_val, snap, candidate=candidate)
    if ok:
        return float(getattr(settings, "best_side_fading_waive_bonus", 20.0) or 20.0)
    return 0.0
