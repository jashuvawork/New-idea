"""Live entry score — re-score every tick / immediately before entry.

Radar explosionScore reflects detection quality at stamp time; premium velocity and
post-spike drawdown can invert minutes later. This module keeps radarScore for audit and
uses liveEntryScore for rank, pretrade, and execution gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import PremiumChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _alert_dict(candidate_or_alert: Any) -> dict[str, Any]:
    if isinstance(candidate_or_alert, dict):
        return candidate_or_alert
    alert = getattr(candidate_or_alert, "alert", None)
    return alert if isinstance(alert, dict) else {}


def _radar_base_score(alert: Mapping[str, Any], candidate: Any = None) -> float:
    if candidate is not None:
        for attr in ("score", "confidence"):
            val = float(getattr(candidate, attr, 0) or 0)
            if val > 0:
                return val
    event = getattr(candidate, "explosion_event", None) if candidate is not None else None
    if event is not None:
        return float(getattr(event, "explosion_score", 0) or 0)
    return float(alert.get("explosionScore") or alert.get("explosion_score") or 0)


def compute_live_entry_score(
    alert: Mapping[str, Any],
    *,
    radar_score: Optional[float] = None,
    premium_chart: Optional[PremiumChart] = None,
    settings: Any = None,
) -> tuple[float, dict[str, Any]]:
    settings = settings or get_settings()
    base = float(radar_score if radar_score is not None else _radar_base_score(alert))
    meta: dict[str, Any] = {
        "radarScore": round(base, 2),
        "scoredAt": datetime.now(IST).isoformat(),
    }

    from app.engines.premium_spike_dump_guard import (
        alert_premium_spike_dump_meta,
        live_execution_trade_score,
    )

    live, live_meta = live_execution_trade_score(
        base,
        premium_chart,
        alert=alert,
        settings=settings,
    )
    meta.update(live_meta)

    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    v9 = float(alert.get("velocity9s") or alert.get("velocity_9s") or 0)
    per_v3 = float(
        getattr(settings, "live_entry_score_negative_v3_penalty_per_point", 3.0) or 3.0
    )
    v3_dead = float(
        getattr(settings, "live_entry_score_negative_v3_deadband", 0.55) or 0.55
    )
    penalty_scale = 1.0
    high_radar_min = float(
        getattr(settings, "live_entry_score_high_radar_soft_penalty_min", 94.0) or 94.0
    )
    if base >= high_radar_min:
        penalty_scale = float(
            getattr(settings, "live_entry_score_high_radar_penalty_scale", 0.45) or 0.45
        )
        meta["highRadarSoftPenalty"] = True
    if v3 < -v3_dead:
        pen = min(35.0, abs(v3 + v3_dead) * per_v3 * penalty_scale)
        live = max(0.0, live - pen)
        meta["velocity3Penalty"] = round(pen, 2)
    if v9 < -v3_dead:
        pen9 = min(25.0, abs(v9 + v3_dead) * (per_v3 * 0.6) * penalty_scale)
        live = max(0.0, live - pen9)
        meta["velocity9Penalty"] = round(pen9, 2)

    dump = alert_premium_spike_dump_meta(alert, settings=settings)
    meta["premiumDump"] = dump
    if dump.get("active"):
        live = min(
            live,
            float(getattr(settings, "live_entry_score_dump_cap", 42.0) or 42.0),
        )
        meta["dumpCapApplied"] = True

    peak = float(alert.get("sessionPeakPremium") or alert.get("peakPremium") or 0)
    low = float(alert.get("sessionLowPremium") or alert.get("sessionLow") or 0)
    prem = float(alert.get("premium") or alert.get("lastPremium") or 0)
    if peak > low > 0 and prem > 0:
        pos = (prem - low) / (peak - low)
        meta["sessionRangePosition"] = round(pos, 3)
        max_pos = float(
            getattr(settings, "live_entry_score_chase_max_range_position", 0.45) or 0.45
        )
        max_v3_chase = float(
            getattr(settings, "live_entry_score_chase_max_velocity_3s", 1.0) or 1.0
        )
        if pos > max_pos and v3 < max_v3_chase:
            chase_pen = min(
                55.0,
                (pos - max_pos)
                * float(
                    getattr(settings, "live_entry_score_chase_range_penalty_scale", 90.0)
                    or 90.0
                ),
            )
            live = max(0.0, live - chase_pen)
            meta["chaseRangePenalty"] = round(chase_pen, 2)

    meta["liveEntryScore"] = round(live, 2)
    meta["liveScorePenalty"] = round(max(0.0, base - live), 2)
    return live, meta


def stamp_alert_live_entry_scores(alert: dict[str, Any]) -> dict[str, Any]:
    """Called on each WS explosion alert refresh (every tick batch)."""
    settings = get_settings()
    if not bool(getattr(settings, "live_entry_score_stamp_on_alerts", True)):
        return alert
    radar = float(alert.get("explosionScore") or 0)
    live, meta = compute_live_entry_score(alert, radar_score=radar)
    alert["radarExplosionScore"] = round(radar, 2)
    alert["liveEntryScore"] = meta.get("liveEntryScore", live)
    alert["liveScorePenalty"] = meta.get("liveScorePenalty", 0)
    alert["liveEntryScoreMeta"] = {
        k: meta[k]
        for k in (
            "premiumDirection",
            "premiumMomentum5Pct",
            "drawdownFromHighPct",
            "velocity3Penalty",
            "velocity9Penalty",
            "dumpCapApplied",
        )
        if k in meta
    }
    return alert


def refresh_candidate_live_entry_score(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    premium_chart: Optional[PremiumChart] = None,
) -> dict[str, Any]:
    """Immediately before pretrade / execution — align candidate.score with live tick."""
    settings = get_settings()
    alert = _alert_dict(candidate)
    if snap is not None and alert:
        # Prefer freshest alert row for this contract on the snapshot.
        sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "").upper()
        side = str(
            getattr(getattr(candidate, "side", None), "value", None)
            or getattr(candidate, "side", "")
            or alert.get("side")
            or ""
        ).upper()
        strike = float(getattr(candidate, "strike", 0) or alert.get("strike") or 0)
        for row in snap.explosionAlerts or []:
            if (
                str(row.get("symbol") or "").upper() == sym
                and str(row.get("side") or "").upper() == side
                and float(row.get("strike") or 0) == strike
            ):
                alert = row
                break

    radar = _radar_base_score(alert, candidate)
    live, meta = compute_live_entry_score(
        alert,
        radar_score=radar,
        premium_chart=premium_chart,
    )
    meta["radarScore"] = round(radar, 2)

    if bool(getattr(settings, "live_entry_score_replace_candidate_score", True)):
        candidate.score = live
    candidate.liveEntryScore = live  # type: ignore[attr-defined]
    candidate.radarScoreAtEntry = radar  # type: ignore[attr-defined]
    candidate.liveEntryScoreMeta = meta  # type: ignore[attr-defined]
    if isinstance(getattr(candidate, "alert", None), dict):
        candidate.alert["liveEntryScore"] = live
        candidate.alert["radarExplosionScore"] = radar
    return meta


def live_entry_score_min_for_tier(tier: str, *, settings: Any = None) -> float:
    settings = settings or get_settings()
    tier_u = str(tier or "").upper()
    if tier_u == "ELITE":
        return float(getattr(settings, "live_entry_score_min_elite", 52.0) or 52.0)
    if tier_u == "EXPLODING":
        return float(getattr(settings, "live_entry_score_min_exploding", 48.0) or 48.0)
    return float(getattr(settings, "live_entry_score_min_default", 44.0) or 44.0)


def live_entry_score_blocks_entry(
    candidate: Any,
    snap: Optional[SymbolSnapshot] = None,
    *,
    premium_chart: Optional[PremiumChart] = None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = get_settings()
    if not bool(getattr(settings, "live_entry_score_gate_enabled", True)):
        return False, "ok", {}
    meta = refresh_candidate_live_entry_score(
        candidate, snap, premium_chart=premium_chart,
    )
    tier = str(getattr(candidate, "tier", "") or _alert_dict(candidate).get("tier") or "")
    live = float(getattr(candidate, "liveEntryScore", 0) or meta.get("liveEntryScore") or 0)
    min_live = live_entry_score_min_for_tier(tier, settings=settings)
    meta["liveEntryMin"] = min_live
    if live < min_live:
        return (
            True,
            f"live_entry_score_{live:.0f}_below_{min_live:.0f}",
            meta,
        )
    from app.engines.premium_spike_dump_guard import post_spike_premium_dump_blocked

    dump_blocked, dump_reason, dump_meta = post_spike_premium_dump_blocked(
        getattr(candidate, "explosion_event", None),
        alert=_alert_dict(candidate),
    )
    meta["premiumSpikeDump"] = dump_meta
    if dump_blocked:
        return True, dump_reason, meta
    return False, "ok", meta


def live_entry_scores_from_evidence(evidence: Mapping[str, Any]) -> tuple[float, float]:
    live = float(
        evidence.get("liveEntryScore")
        or evidence.get("live_entry_score")
        or 0
    )
    radar = float(
        evidence.get("radarExplosionScore")
        or evidence.get("explosionScore")
        or evidence.get("explosion_score")
        or 0
    )
    if live <= 0 and radar > 0:
        live = radar
    return live, radar


def live_entry_moment_active(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    """Strong tick score + radar — real intraday moment, not stale detection."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_entry_moment_waiver_enabled", True)):
        return False
    live, radar = live_entry_scores_from_evidence(evidence)
    min_live = float(getattr(settings, "live_entry_moment_min_live", 86.0) or 86.0)
    min_radar = float(getattr(settings, "live_entry_moment_min_radar", 92.0) or 92.0)
    return live >= min_live and radar >= min_radar


def live_entry_moment_waives_exploding_tier(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_entry_moment_waives_exploding_tier", True)):
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in {"EXPLODING", "ELITE"}:
        return False
    return live_entry_moment_active(evidence, settings=settings)


def live_entry_best_trade_capture_active(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
    require_explicit_live: bool = False,
) -> bool:
    """Top radar + live tick score — allow best-trade capture through FTV/elite stacks."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_entry_best_trade_capture_enabled", True)):
        return False
    explicit_live = float(
        evidence.get("liveEntryScore") or evidence.get("live_entry_score") or 0
    )
    live, radar = live_entry_scores_from_evidence(evidence)
    if require_explicit_live and explicit_live <= 0:
        return False
    if require_explicit_live:
        live = explicit_live
    min_live = float(
        getattr(settings, "live_entry_best_trade_capture_min_live", 88.0) or 88.0
    )
    min_radar = float(
        getattr(settings, "live_entry_best_trade_capture_min_radar", 95.0) or 95.0
    )
    return live >= min_live and radar >= min_radar


def live_entry_best_trade_capture_from_alert(
    alert: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    if float(alert.get("liveEntryScore") or 0) <= 0:
        return False
    evidence = {
        "liveEntryScore": alert.get("liveEntryScore"),
        "explosionScore": alert.get("explosionScore") or alert.get("radarExplosionScore"),
        "tier": alert.get("tier"),
    }
    return live_entry_best_trade_capture_active(
        evidence, settings=settings, require_explicit_live=True,
    )
