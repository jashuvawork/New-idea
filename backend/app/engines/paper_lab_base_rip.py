"""Paper-lab experiment: enter near local base, ride to rip — NIFTY + SENSEX (not live)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings

IST = ZoneInfo("Asia/Kolkata")


def paper_lab_base_rip_active(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        getattr(settings, "paper_lab_base_rip_enabled", False)
        and getattr(settings, "paper_trading", True)
        and not getattr(settings, "enable_live_trading", False)
    )


def paper_lab_ladder_keep_ratio(settings: Settings | None = None) -> Optional[float]:
    """Higher peak_keep when lab mode on — more of the rip before exit."""
    settings = settings or get_settings()
    if not paper_lab_base_rip_active(settings):
        return None
    raw = float(getattr(settings, "paper_lab_base_rip_ladder_keep_ratio", 0.85) or 0.85)
    return min(0.95, max(0.55, raw))


def paper_lab_hot_defer_velocity(settings: Settings | None = None) -> Optional[float]:
    settings = settings or get_settings()
    if not paper_lab_base_rip_active(settings):
        return None
    return float(getattr(settings, "paper_lab_base_rip_hot_defer_velocity_3s", 1.6) or 1.6)


def _alert_near_base_rip(alert: dict[str, Any], settings: Settings) -> bool:
    if not isinstance(alert, dict):
        return False
    max_pad = float(getattr(settings, "paper_lab_base_rip_max_local_base_pct", 18.0) or 18.0)
    pad = max(
        float(alert.get("localBasePct") or alert.get("local_base_pct") or 0),
        float(alert.get("ictBaseRelativeMovePct") or 0),
        float(alert.get("openPremiumMove") or 0),
    )
    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    min_v3 = float(getattr(settings, "paper_lab_base_rip_min_velocity_3s", 1.5) or 1.5)
    tier = str(alert.get("tier") or "").upper()
    if pad > max_pad or v3 < min_v3:
        return False
    if tier in ("ELITE", "EXPLODING", "BUILDING"):
        return True
    score = float(alert.get("explosionScore") or alert.get("score") or 0)
    return score >= float(getattr(settings, "paper_lab_base_rip_min_explosion_score", 55.0) or 55.0)


def paper_lab_base_rip_rank_bonus(
    alert: dict[str, Any] | None,
    settings: Settings | None = None,
) -> float:
    """Selector rank nudge for near-base rip setups (paper only)."""
    settings = settings or get_settings()
    if not paper_lab_base_rip_active(settings) or not alert:
        return 0.0
    if not _alert_near_base_rip(alert, settings):
        return 0.0
    return float(getattr(settings, "paper_lab_base_rip_rank_bonus", 22.0) or 22.0)


def paper_lab_extended_chase_waive(
    *,
    local_pad: float,
    session_move: float,
    velocity_3s: float,
    settings: Settings | None = None,
) -> bool:
    """Allow controlled chase on paper when move is still near base but rip is live."""
    settings = settings or get_settings()
    if not paper_lab_base_rip_active(settings):
        return False
    max_pad = float(getattr(settings, "paper_lab_base_rip_max_local_base_pct", 18.0) or 18.0)
    min_v3 = float(getattr(settings, "paper_lab_base_rip_min_velocity_3s", 1.5) or 1.5)
    max_session = float(
        getattr(settings, "paper_lab_base_rip_max_session_move_pct", 28.0) or 28.0
    )
    return local_pad <= max_pad and velocity_3s >= min_v3 and session_move <= max_session


def build_index_base_rip_monitor(
    snapshots: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Dual-index board: spot, regime, best near-base rip candidates."""
    settings = settings or get_settings()
    board: dict[str, Any] = {
        "at": datetime.now(IST).isoformat(),
        "labActive": paper_lab_base_rip_active(settings),
        "indices": {},
    }
    max_pad = float(getattr(settings, "paper_lab_base_rip_max_local_base_pct", 18.0) or 18.0)
    for sym in ("NIFTY", "SENSEX"):
        snap = snapshots.get(sym) or snapshots.get(sym.upper())
        if snap is None:
            continue
        regime = getattr(snap, "regime", None)
        regime_s = str(getattr(regime, "value", regime) or regime or "")
        spot = getattr(snap, "spot", None)
        chart = getattr(snap, "spotChart", None)
        hi = getattr(chart, "sessionHigh", None) if chart else None
        lo = getattr(chart, "sessionLow", None) if chart else None
        pos = None
        if spot and hi and lo and hi > lo:
            pos = round((float(spot) - float(lo)) / (float(hi) - float(lo)) * 100.0, 1)
        alerts = list(getattr(snap, "explosionAlerts", None) or [])
        near: list[dict[str, Any]] = []
        for a in alerts[:40]:
            if not isinstance(a, dict):
                continue
            pad = float(a.get("localBasePct") or a.get("local_base_pct") or 99.0)
            if pad > max_pad:
                continue
            side = str(a.get("side") or "").upper()
            near.append(
                {
                    "key": f"{sym}:{side}:{a.get('strike')}",
                    "strike": a.get("strike"),
                    "side": side,
                    "tier": a.get("tier"),
                    "localBasePct": round(pad, 2),
                    "velocity3s": round(float(a.get("velocity3s") or 0), 2),
                    "explosionScore": a.get("explosionScore") or a.get("score"),
                    "labRipEligible": _alert_near_base_rip(a, settings),
                }
            )
        near.sort(
            key=lambda x: (
                0 if x.get("labRipEligible") else 1,
                -(float(x.get("explosionScore") or 0)),
            )
        )
        top = getattr(snap, "topExplosion", None)
        board["indices"][sym] = {
            "regime": regime_s,
            "spot": spot,
            "sessionHigh": hi,
            "sessionLow": lo,
            "rangePositionPct": pos,
            "explosionAlertCount": len(alerts),
            "nearBaseRip": near[:6],
            "topExplosion": (
                {
                    "key": f"{sym}:{top.get('side')}:{top.get('strike')}",
                    "localBasePct": top.get("localBasePct"),
                    "tier": top.get("tier"),
                }
                if isinstance(top, dict)
                else None
            ),
        }
    return board


def append_monitor_artifact(payload: dict[str, Any]) -> None:
    try:
        from pathlib import Path
        import json

        day = datetime.now(IST).strftime("%Y-%m-%d")
        path = Path("/opt/cursor/artifacts/paper-lab-base-rip") / f"monitor-{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass