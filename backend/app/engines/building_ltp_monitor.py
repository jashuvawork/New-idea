"""Precise BUILDING radar LTP monitor — re-evaluate and take on every meaningful tick."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot
from app.engines.snapshot_fast import resolve_trade_premium

# key "SYMBOL:SIDE:STRIKE" -> last observed LTP
_building_ltp_watch: dict[str, float] = {}
# Previous helper fingerprint per key — detect helper flip (Aug19 sudden help).
_building_helper_fp: dict[str, str] = {}
_last_building_cycle_mono: float = 0.0
# Latest full scoreboard + best ready key (published each LTP cycle).
_last_scoreboard: list[dict[str, Any]] = []
_best_ready_key: Optional[str] = None
_scoreboard_active: bool = False


def reset_building_ltp_monitor_for_tests() -> None:
    global _last_building_cycle_mono, _best_ready_key, _scoreboard_active
    _building_ltp_watch.clear()
    _building_helper_fp.clear()
    _last_building_cycle_mono = 0.0
    _last_scoreboard.clear()
    _best_ready_key = None
    _scoreboard_active = False


def _alert_key(symbol: str, side: str, strike: float) -> str:
    return f"{str(symbol).upper()}:{str(side).upper()}:{float(strike):.0f}"


@dataclass
class BuildingLtpScore:
    key: str
    symbol: str
    side: str
    strike: float
    ltp: float
    tier: str
    ready: bool
    ready_reason: str
    score: float
    explosion_score: float
    velocity_3s: float
    velocity_9s: float
    local_move_pct: float
    off_low_move_pct: float
    volume_awaken: bool
    helpers: list[str] = field(default_factory=list)
    helper_count: int = 0
    helping: bool = False
    sudden_lift: bool = False
    rank: int = 0
    is_best_ready: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def building_alerts_on_radar(
    snapshots: dict[str, SymbolSnapshot],
) -> list[dict[str, Any]]:
    """Collect BUILDING (and building-rip ready) rows currently on radar."""
    from app.engines.building_ftv_gates import alert_has_building_rip_signal

    rows: list[dict[str, Any]] = []
    for symbol, snap in (snapshots or {}).items():
        if not getattr(snap, "dataAvailable", False):
            continue
        for alert in getattr(snap, "explosionAlerts", None) or []:
            if not isinstance(alert, dict):
                continue
            tier = str(alert.get("tier") or "").upper()
            # Keep true BUILDING plus promoted EXPLODING that still carry buildingRip.
            if tier != "BUILDING" and not (
                tier == "EXPLODING" and alert_has_building_rip_signal(alert)
            ):
                continue
            side = str(alert.get("side") or "").upper()
            try:
                strike = float(alert.get("strike") or 0)
            except (TypeError, ValueError):
                strike = 0.0
            if side not in ("CALL", "PUT") or strike <= 0:
                continue
            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "side": side,
                    "strike": strike,
                    "alert": alert,
                    "snap": snap,
                }
            )
    return rows


def _composite_building_score(
    *,
    alert: dict[str, Any],
    ready: bool,
    ready_reason: str,
    ltp: float,
    helper_bonus: float = 0.0,
    helping: bool = False,
) -> float:
    """Full causal score for one watched BUILDING name on this LTP print."""
    explosion = float(alert.get("explosionScore") or alert.get("score") or 0)
    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    v9 = float(alert.get("velocity9s") or alert.get("velocity_9s") or 0)
    local_move = float(
        alert.get("ictBaseRelativeMovePct")
        or alert.get("localBaseMovePct")
        or 0
    )
    off_low = float(alert.get("offLowMovePct") or 0)
    pad = max(local_move, off_low)
    vol_awake = bool(
        alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")
    )
    quality = float(
        alert.get("flatVerticalQuality")
        or alert.get("ictFlatVerticalQuality")
        or 0
    )
    score = explosion * 0.45
    if v3 > 0:
        score += min(25.0, v3 * 6.0)
    else:
        score -= 20.0
    if v9 > 0:
        score += min(10.0, v9 * 2.0)
    # Prefer measured little lifts off local base (2–15%), then mid-rip heat.
    if 2.0 <= pad <= 15.0:
        score += 18.0
    elif 15.0 < pad <= 35.0:
        score += 12.0
    elif pad > 55.0:
        score -= min(30.0, (pad - 55.0) * 0.8)
    if vol_awake:
        score += 8.0
    if quality > 0:
        score += quality * 0.12
    # Aug19 helpers (vol / velocity / displacement / chart / breadth / FTV).
    score += max(0.0, float(helper_bonus or 0))
    if helping:
        score += 6.0
    if ready:
        score += 30.0
        if ready_reason == "building_local_base_lift_ready":
            score += 10.0
        elif ready_reason == "building_rip_bullish_ready":
            score += 6.0
        elif "v_rip" in ready_reason or "elite_base" in ready_reason:
            score += 8.0
    if ltp > 0:
        score += min(5.0, ltp / 200.0)
    return round(max(0.0, min(100.0, score)), 2)


def evaluate_all_building_ltp(
    snapshots: dict[str, SymbolSnapshot],
    *,
    state: Any = None,
    max_age_seconds: float = 2.0,
) -> list[BuildingLtpScore]:
    """Calculate everything for every BUILDING name on radar (this LTP cycle)."""
    from app.engines.building_lift_helpers import (
        evaluate_building_lift_helpers,
        stamp_building_lift_helpers,
    )
    from app.engines.ict_breakout_monitor import (
        building_rip_bullish_readiness,
        first_lift_entry_readiness,
    )

    settings = get_settings()
    max_age = float(
        getattr(settings, "tick_overlay_max_age_seconds", max_age_seconds)
        or max_age_seconds
    )
    helper_monitor = bool(
        getattr(settings, "building_sudden_lift_monitor_enabled", True)
    )
    scored: list[BuildingLtpScore] = []
    for row in building_alerts_on_radar(snapshots):
        alert = dict(row["alert"])
        snap = row["snap"]
        side = Side(row["side"])
        key = _alert_key(row["symbol"], row["side"], row["strike"])
        ltp = resolve_trade_premium(
            snap, row["strike"], side, max_age_seconds=max_age,
        )
        if ltp is None or float(ltp) <= 0:
            try:
                ltp = float(alert.get("premium") or 0)
            except (TypeError, ValueError):
                ltp = 0.0
        ltp = float(ltp or 0)
        if ltp > 0:
            alert["premium"] = ltp
        # Prefer live WS tape velocity for this LTP print.
        alert = overlay_alert_tick_velocity(snap, alert, max_age_seconds=max_age)

        helpers = None
        helper_bonus = 0.0
        helping = False
        sudden = False
        helper_names: list[str] = []
        if helper_monitor:
            helpers = evaluate_building_lift_helpers(
                snap=snap,
                alert=alert,
                prev_ltp=_building_ltp_watch.get(key),
                live_ltp=ltp,
            )
            alert = stamp_building_lift_helpers(alert, helpers)
            helper_bonus = float(helpers.score_bonus)
            helping = bool(helpers.helping)
            sudden = bool(helpers.sudden_lift)
            helper_names = list(helpers.helpers)
            # Remember helper fingerprint for flip-triggered cycles.
            fp = ",".join(helper_names)
            _building_helper_fp[key] = fp
            # Persist onto live radar alert so selector / order path see stamps.
            live_alert = row["alert"]
            if isinstance(live_alert, dict):
                live_alert.update(
                    {
                        k: alert[k]
                        for k in (
                            "buildingRipHelpers",
                            "buildingRipHelpersOk",
                            "buildingLiftHelping",
                            "buildingSuddenLift",
                            "buildingLtpLiftPct",
                            "buildingHelperCount",
                            "buildingHelperBonus",
                            "buildingIctConfirms",
                            "ictBuildingRipReady",
                            "premium",
                            "velocity3s",
                            "velocity9s",
                            "tickVelocity3s",
                            "tickVelocity9s",
                        )
                        if k in alert
                    }
                )

        ready = False
        ready_reason = "not_evaluated"
        try:
            ready, ready_reason = first_lift_entry_readiness(
                snap=snap,
                alert=alert,
                state=state,
            )
        except Exception:
            try:
                ready, ready_reason = building_rip_bullish_readiness(
                    snap=snap,
                    alert=alert,
                    state=state,
                )
            except Exception:
                ready, ready_reason = False, "readiness_error"

        if ready and isinstance(row["alert"], dict):
            row["alert"]["ictBaseReadinessReason"] = str(ready_reason or "")
            if str(ready_reason or "") in (
                "building_rip_bullish_ready",
                "building_local_base_lift_ready",
            ):
                row["alert"]["ictBuildingRipReady"] = True
                alert["ictBuildingRipReady"] = True
                alert["ictBaseReadinessReason"] = str(ready_reason or "")

        score = _composite_building_score(
            alert=alert,
            ready=ready,
            ready_reason=ready_reason,
            ltp=ltp,
            helper_bonus=helper_bonus,
            helping=helping,
        )
        scored.append(
            BuildingLtpScore(
                key=key,
                symbol=row["symbol"],
                side=row["side"],
                strike=float(row["strike"]),
                ltp=round(ltp, 2),
                tier=str(alert.get("tier") or "BUILDING").upper(),
                ready=bool(ready),
                ready_reason=str(ready_reason or ""),
                score=score,
                explosion_score=float(
                    alert.get("explosionScore") or alert.get("score") or 0
                ),
                velocity_3s=float(
                    alert.get("velocity3s") or alert.get("velocity_3s") or 0
                ),
                velocity_9s=float(
                    alert.get("velocity9s") or alert.get("velocity_9s") or 0
                ),
                local_move_pct=float(
                    alert.get("ictBaseRelativeMovePct")
                    or alert.get("localBaseMovePct")
                    or 0
                ),
                off_low_move_pct=float(alert.get("offLowMovePct") or 0),
                volume_awaken=bool(
                    alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")
                ),
                helpers=helper_names,
                helper_count=len(helper_names),
                helping=helping,
                sudden_lift=sudden,
                meta={
                    "ictBuildingRipReady": bool(alert.get("ictBuildingRipReady")),
                    "ictLocalSwingBase": bool(alert.get("ictLocalSwingBase")),
                    "ictBaseArmed": bool(alert.get("ictBaseArmed")),
                    "buildingRipHelpersOk": bool(alert.get("buildingRipHelpersOk")),
                    "ltpLiftPct": float(alert.get("buildingLtpLiftPct") or 0),
                    "ictConfirms": list(alert.get("buildingIctConfirms") or []),
                },
            )
        )

    scored.sort(
        key=lambda s: (
            s.ready,
            s.helping,
            s.score,
            s.helper_count,
            s.velocity_3s,
            s.explosion_score,
        ),
        reverse=True,
    )
    for idx, row in enumerate(scored, start=1):
        row.rank = idx
    best = next((s for s in scored if s.ready), None)
    if best is not None:
        best.is_best_ready = True
    return scored


def publish_building_scoreboard(scores: list[BuildingLtpScore]) -> dict[str, Any]:
    """Publish scoreboard so selector takes only the best ready BUILDING."""
    global _best_ready_key, _scoreboard_active
    _last_scoreboard.clear()
    _last_scoreboard.extend(s.to_dict() for s in scores)
    best = next((s for s in scores if s.is_best_ready), None)
    _best_ready_key = best.key if best is not None else None
    _scoreboard_active = bool(
        getattr(get_settings(), "building_ltp_best_pick_enabled", True)
        and scores
    )
    return {
        "enabled": bool(getattr(get_settings(), "building_ltp_best_pick_enabled", True)),
        "active": _scoreboard_active,
        "watchedCount": len(scores),
        "readyCount": sum(1 for s in scores if s.ready),
        "bestKey": _best_ready_key,
        "best": best.to_dict() if best is not None else None,
        "scoreboard": list(_last_scoreboard),
    }


def clear_building_scoreboard() -> None:
    global _best_ready_key, _scoreboard_active
    _last_scoreboard.clear()
    _best_ready_key = None
    _scoreboard_active = False
    # Keep helper fingerprints so the next cycle can still detect flips.


def building_best_ready_key() -> Optional[str]:
    return _best_ready_key if _scoreboard_active else None


def building_scoreboard_snapshot() -> dict[str, Any]:
    return {
        "active": _scoreboard_active,
        "bestKey": _best_ready_key,
        "scoreboard": list(_last_scoreboard),
        "watched": dict(_building_ltp_watch),
        "count": len(_building_ltp_watch),
        "lastCycleMono": _last_building_cycle_mono,
    }


def apply_building_ltp_best_pick(
    candidate: Any,
) -> tuple[float, bool]:
    """Deprecated single-candidate helper — prefer filter_candidates_building_best_pick."""
    settings = get_settings()
    if not _scoreboard_active:
        return 0.0, True
    if not bool(getattr(settings, "building_ltp_best_pick_enabled", True)):
        return 0.0, True
    key = _candidate_key(candidate)
    preferred = preferred_building_ready_key({key})
    only_best = bool(getattr(settings, "building_ltp_only_best_ready", True))
    is_buildingish = _is_buildingish_candidate(candidate)
    if only_best and is_buildingish and preferred and key != preferred:
        return 0.0, False
    if preferred and key == preferred:
        bonus = float(
            getattr(settings, "building_ltp_best_pick_rank_bonus", 48.0) or 48.0
        )
        return bonus, True
    return 0.0, True


def _candidate_key(candidate: Any) -> str:
    return _alert_key(
        getattr(candidate, "symbol", ""),
        getattr(
            getattr(candidate, "side", None),
            "value",
            getattr(candidate, "side", ""),
        ),
        float(getattr(candidate, "strike", 0) or 0),
    )


def _is_buildingish_candidate(candidate: Any) -> bool:
    from app.engines.building_ftv_gates import alert_has_building_rip_signal

    tier = str(getattr(candidate, "tier", "") or "").upper()
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict) and not tier:
        tier = str(alert.get("tier") or "").upper()
    if tier == "BUILDING":
        return True
    return tier == "EXPLODING" and alert_has_building_rip_signal(
        alert if isinstance(alert, dict) else None
    )


def preferred_building_ready_key(candidate_keys: set[str]) -> Optional[str]:
    """Best scoreboard-ready BUILDING that actually made it into candidates.

    Fail soft: if the absolute #1 ready name was filtered out (OTM/band/guards),
    promote the next ready name that is selectable — never wipe all BUILDING takes.
    """
    if not _scoreboard_active or not _last_scoreboard:
        return _best_ready_key if _best_ready_key in candidate_keys else None
    for row in _last_scoreboard:
        if not row.get("ready"):
            continue
        key = str(row.get("key") or "")
        if key and key in candidate_keys:
            return key
    return None


def filter_candidates_building_best_pick(candidates: list[Any]) -> list[Any]:
    """Keep/boost only the best selectable BUILDING among monitored names."""
    settings = get_settings()
    if not _scoreboard_active:
        return candidates
    if not bool(getattr(settings, "building_ltp_best_pick_enabled", True)):
        return candidates
    if not candidates:
        return candidates

    key_map = {_candidate_key(c): c for c in candidates}
    preferred = preferred_building_ready_key(set(key_map.keys()))
    only_best = bool(getattr(settings, "building_ltp_only_best_ready", True))
    bonus = float(
        getattr(settings, "building_ltp_best_pick_rank_bonus", 48.0) or 48.0
    )

    out: list[Any] = []
    for c in candidates:
        key = _candidate_key(c)
        is_buildingish = _is_buildingish_candidate(c)
        if only_best and is_buildingish and preferred and key != preferred:
            continue
        if preferred and key == preferred:
            c.score = float(getattr(c, "score", 0) or 0) + bonus
            c.pretrade_meta = {
                **(getattr(c, "pretrade_meta", None) or {}),
                "buildingLtpBestPick": True,
                "buildingLtpBestPickBonus": bonus,
                "buildingLtpPreferredKey": preferred,
            }
        out.append(c)
    return out


def overlay_alert_tick_velocity(
    snap: SymbolSnapshot,
    alert: dict[str, Any],
    *,
    max_age_seconds: float = 3.0,
) -> dict[str, Any]:
    """Prefer fresh WS tape velocity over sparse poll velocity for BUILDING scoring."""
    from app.services.tick_store import get_velocity_pct

    side = str(alert.get("side") or "").upper()
    try:
        strike = float(alert.get("strike") or 0)
    except (TypeError, ValueError):
        strike = 0.0
    if side not in ("CALL", "PUT") or strike <= 0:
        return alert

    ik = None
    for row in getattr(snap, "heatmap", None) or []:
        if abs(float(getattr(row, "strike", 0) or 0) - strike) < 1:
            ik = (
                getattr(row, "callInstrumentKey", None)
                if side == "CALL"
                else getattr(row, "putInstrumentKey", None)
            )
            break
    if not ik:
        return alert

    out = dict(alert)
    v3 = get_velocity_pct(
        ik, window_seconds=3.0, max_age_seconds=max_age_seconds,
    )
    v9 = get_velocity_pct(
        ik, window_seconds=9.0, max_age_seconds=max_age_seconds,
    )
    if v3 is not None:
        poll_v3 = float(out.get("velocity3s") or out.get("velocity_3s") or 0)
        out["tickVelocity3s"] = float(v3)
        out["velocity3s"] = max(poll_v3, float(v3))
    if v9 is not None:
        poll_v9 = float(out.get("velocity9s") or out.get("velocity_9s") or 0)
        out["tickVelocity9s"] = float(v9)
        out["velocity9s"] = max(poll_v9, float(v9))
    return out


def publish_scoreboard_for_snapshots(
    snapshots: dict[str, SymbolSnapshot],
    *,
    state: Any = None,
) -> dict[str, Any]:
    """Score every BUILDING name and publish best-pick for the next selector pass."""
    scores = evaluate_all_building_ltp(snapshots, state=state)
    return publish_building_scoreboard(scores)


def sync_building_ltp_watch(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> dict[str, float]:
    """Refresh the BUILDING watch set from current radar + live LTPs."""
    settings = get_settings()
    max_age = float(
        getattr(settings, "tick_overlay_max_age_seconds", max_age_seconds)
        or max_age_seconds
    )
    live: dict[str, float] = {}
    for row in building_alerts_on_radar(snapshots):
        snap = row["snap"]
        side = Side(row["side"])
        ltp = resolve_trade_premium(
            snap,
            row["strike"],
            side,
            max_age_seconds=max_age,
        )
        if ltp is None or float(ltp) <= 0:
            try:
                ltp = float(row["alert"].get("premium") or 0)
            except (TypeError, ValueError):
                ltp = 0.0
        if float(ltp or 0) <= 0:
            continue
        key = _alert_key(row["symbol"], row["side"], row["strike"])
        live[key] = float(ltp)

    # Drop names that left BUILDING radar; keep current set only.
    stale = [k for k in _building_ltp_watch if k not in live]
    for key in stale:
        _building_ltp_watch.pop(key, None)
        _building_helper_fp.pop(key, None)
    for key, ltp in live.items():
        _building_ltp_watch.setdefault(key, ltp)
    return dict(live)


def peek_building_ltp_moves(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> tuple[bool, list[str], dict[str, float]]:
    """Detect meaningful BUILDING LTP moves without consuming fingerprints."""
    settings = get_settings()
    min_pct = float(
        getattr(settings, "building_ltp_min_change_pct", 0.15) or 0.15
    )
    min_abs = float(
        getattr(settings, "building_ltp_min_change_abs", 0.05) or 0.05
    )
    live = sync_building_ltp_watch(
        snapshots, max_age_seconds=max_age_seconds,
    )
    if not live:
        return False, [], live

    moved: list[str] = []
    for key, ltp in live.items():
        prev = _building_ltp_watch.get(key)
        if prev is None or prev <= 0:
            continue
        delta = abs(ltp - prev)
        pct = (delta / prev) * 100.0 if prev > 0 else 0.0
        if delta >= min_abs or pct >= min_pct:
            moved.append(key)
    return bool(moved), moved, live


def building_ltp_moved(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> tuple[bool, list[str]]:
    """True when any watched BUILDING contract printed a meaningful new LTP."""
    moved, keys, live = peek_building_ltp_moves(
        snapshots, max_age_seconds=max_age_seconds,
    )
    if moved:
        for key in keys:
            if key in live:
                _building_ltp_watch[key] = live[key]
    elif live:
        # Seed first samples so the next tick can detect a move.
        for key, ltp in live.items():
            _building_ltp_watch.setdefault(key, ltp)
    return moved, keys


def mark_building_ltps_seen(snapshots: dict[str, SymbolSnapshot]) -> None:
    """Align watch fingerprints after a full BUILDING entry cycle."""
    live = sync_building_ltp_watch(snapshots)
    _building_ltp_watch.clear()
    _building_ltp_watch.update(live)


def peek_building_helper_flip(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> tuple[bool, list[str]]:
    """True when a BUILDING name's helper board just flipped to helping."""
    from app.engines.building_lift_helpers import (
        evaluate_building_lift_helpers,
        stamp_building_lift_helpers,
    )

    settings = get_settings()
    if not bool(getattr(settings, "building_sudden_lift_monitor_enabled", True)):
        return False, []
    if not bool(getattr(settings, "building_helper_flip_triggers_cycle", True)):
        return False, []

    max_age = float(
        getattr(settings, "tick_overlay_max_age_seconds", max_age_seconds)
        or max_age_seconds
    )
    flipped: list[str] = []
    for row in building_alerts_on_radar(snapshots):
        alert = dict(row["alert"])
        snap = row["snap"]
        side = Side(row["side"])
        key = _alert_key(row["symbol"], row["side"], row["strike"])
        ltp = resolve_trade_premium(
            snap, row["strike"], side, max_age_seconds=max_age,
        )
        if ltp is None or float(ltp) <= 0:
            try:
                ltp = float(alert.get("premium") or 0)
            except (TypeError, ValueError):
                ltp = 0.0
        ltp = float(ltp or 0)
        if ltp > 0:
            alert["premium"] = ltp
        alert = overlay_alert_tick_velocity(snap, alert, max_age_seconds=max_age)
        helpers = evaluate_building_lift_helpers(
            snap=snap,
            alert=alert,
            prev_ltp=_building_ltp_watch.get(key),
            live_ltp=ltp,
        )
        stamp_building_lift_helpers(alert, helpers)
        fp = ",".join(helpers.helpers)
        prev_fp = _building_helper_fp.get(key, "")
        was_helping = bool(prev_fp) and len(prev_fp.split(",")) >= int(
            getattr(settings, "building_sudden_lift_min_helpers", 3) or 3
        )
        if helpers.helping and (not was_helping or fp != prev_fp):
            # New helping board or newly added helpers → force a take cycle.
            if not was_helping or helpers.sudden_lift:
                flipped.append(key)
        _building_helper_fp[key] = fp
    return bool(flipped), flipped


def building_ltp_monitor_due(
    snapshots: Optional[dict[str, SymbolSnapshot]],
    *,
    now_mono: Optional[float] = None,
) -> bool:
    """Whether the BUILDING LTP entry cycle should run now."""
    import time

    settings = get_settings()
    if not bool(getattr(settings, "building_ltp_monitor_enabled", True)):
        return False
    if not snapshots:
        return False

    has_building = bool(building_alerts_on_radar(snapshots))
    if not has_building and not _building_ltp_watch:
        return False

    mono = time.monotonic() if now_mono is None else float(now_mono)
    min_ms = float(
        getattr(settings, "building_ltp_monitor_min_ms", 75.0) or 75.0
    )
    if _last_building_cycle_mono > 0 and (mono - _last_building_cycle_mono) * 1000 < min_ms:
        return False

    moved, _, live = peek_building_ltp_moves(snapshots)
    if moved:
        return True

    # Aug19 lesson: helpers can flip on before a large LTP tick — still take.
    helper_flip, _ = peek_building_helper_flip(snapshots)
    if helper_flip:
        return True

    # First sighting: seed fingerprints and wait for the next LTP print.
    for key, ltp in live.items():
        _building_ltp_watch.setdefault(key, ltp)
    return False


def mark_building_ltp_cycle_done(*, now_mono: Optional[float] = None) -> None:
    import time

    global _last_building_cycle_mono
    _last_building_cycle_mono = (
        time.monotonic() if now_mono is None else float(now_mono)
    )


def building_watch_snapshot() -> dict[str, Any]:
    return building_scoreboard_snapshot()
