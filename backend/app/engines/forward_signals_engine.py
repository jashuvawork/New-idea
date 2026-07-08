"""Forward signals — unify upcoming moments, trade setups, and risk forecasts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.engines.chop_day_guards import chop_guard_summary
from app.engines.composer_market_monitor import get_latest_brief
from app.engines.expiry_day_guards import expiry_guard_summary
from app.engines.worst_day_guard import identify_worst_day, session_entry_policy
from app.models.schemas import AutoTraderState, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

SESSION_WINDOWS: list[dict[str, Any]] = [
    {
        "id": "open_caution",
        "label": "Open caution",
        "startH": 9,
        "startM": 15,
        "endH": 9,
        "endM": 45,
        "horizon": "MOMENT",
        "hint": "Auction chop — wait for direction before size",
    },
    {
        "id": "morning_capture",
        "label": "Morning premium capture",
        "startH": 9,
        "startM": 15,
        "endH": 11,
        "endM": 45,
        "horizon": "MOMENT",
        "hint": "Open premium expansion — watch velocity on both sides",
    },
    {
        "id": "all_day_explosion",
        "label": "All-day explosion",
        "startH": 9,
        "startM": 20,
        "endH": 15,
        "endM": 25,
        "horizon": "MOMENT",
        "hint": "Flat-then-vertical rips — volume awakening after 14:00",
    },
    {
        "id": "momentum_rally",
        "label": "Momentum rally",
        "startH": 10,
        "startM": 0,
        "endH": 15,
        "endM": 25,
        "horizon": "MOMENT",
        "hint": "Afternoon breakouts — premium-led vs chart",
    },
    {
        "id": "power_hour",
        "label": "Power hour",
        "startH": 14,
        "startM": 0,
        "endH": 15,
        "endM": 25,
        "horizon": "MOMENT",
        "hint": "Near-expiry gamma — deep OTM PE/CE can rip fast",
    },
]


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def _window_status(start_h: int, start_m: int, end_h: int, end_m: int) -> dict[str, Any]:
    t = _minutes_now()
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    active = start <= t < end
    if t < start:
        return {"active": False, "status": "UPCOMING", "startsInMin": start - t, "endsInMin": None}
    if active:
        return {"active": True, "status": "LIVE", "startsInMin": 0, "endsInMin": end - t}
    return {"active": False, "status": "ENDED", "startsInMin": None, "endsInMin": None}


def _sig_id(*parts: Any) -> str:
    return ":".join(str(p) for p in parts if p is not None)


def _build_moments() -> list[dict[str, Any]]:
    moments: list[dict[str, Any]] = []
    for w in SESSION_WINDOWS:
        st = _window_status(w["startH"], w["startM"], w["endH"], w["endM"])
        moments.append({
            "id": w["id"],
            "label": w["label"],
            "horizon": w["horizon"],
            "hint": w["hint"],
            **st,
            "window": f"{w['startH']:02d}:{w['startM']:02d}–{w['endH']:02d}:{w['endM']:02d} IST",
        })
    moments.sort(key=lambda m: (0 if m["status"] == "LIVE" else 1 if m["status"] == "UPCOMING" else 2, m.get("startsInMin") or 999))
    return moments


def _explosion_signals(snapshots: dict[str, SymbolSnapshot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            tier = str(alert.get("tier") or "WATCH")
            if tier == "WATCH" and not alert.get("allDayExplosion"):
                continue
            daily = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
            score = float(alert.get("explosionScore") or 0)
            side = str(alert.get("side") or "")
            strike = alert.get("strike")
            tradeable = bool(alert.get("tradeable"))
            blockers: list[str] = []
            if not tradeable:
                blockers.append("tier_or_velocity")
            if tier == "BUILDING" and not alert.get("allDayExplosion") and not alert.get("premiumCapture"):
                blockers.append("building_await_upgrade")
            windows: list[str] = []
            if alert.get("morningCapture"):
                windows.append("morningCapture")
            if alert.get("afternoonCapture"):
                windows.append("afternoonCapture")
            if alert.get("allDayExplosion"):
                windows.append("allDayExplosion")
            out.append({
                "id": _sig_id("explosion", sym, side, strike),
                "horizon": "EXPLOSION",
                "symbol": sym,
                "side": side,
                "strike": strike,
                "premium": alert.get("premium"),
                "confidence": score,
                "tradeable": tradeable,
                "summary": f"{sym} {side} {strike} · {tier} · score {score:.0f}",
                "detail": str(alert.get("reason") or ""),
                "tier": tier,
                "dailyMovePct": daily,
                "velocity3s": alert.get("velocity3s"),
                "volumeSurge": alert.get("volumeSurge"),
                "windows": windows,
                "blockers": blockers,
                "source": "explosion_radar",
            })
    out.sort(key=lambda s: (s.get("tradeable", False), s.get("confidence", 0), s.get("dailyMovePct", 0)), reverse=True)
    return out


def _swing_signals(snapshots: dict[str, SymbolSnapshot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.swingAlerts or []:
            conf = float(alert.get("confidence") or 0)
            out.append({
                "id": _sig_id("swing", sym, alert.get("side"), alert.get("strike")),
                "horizon": "SWING",
                "symbol": sym,
                "side": alert.get("side"),
                "strike": alert.get("strike"),
                "premium": alert.get("premium"),
                "confidence": conf,
                "tradeable": bool(alert.get("tradeable")),
                "summary": f"{sym} {alert.get('side')} {alert.get('strike')} · {alert.get('swingType')}",
                "detail": str(alert.get("reason") or ""),
                "targets": {
                    "targetPct": alert.get("targetPct"),
                    "stopPct": alert.get("stopPct"),
                    "maxHoldDays": alert.get("maxHoldDays"),
                },
                "blockers": [] if alert.get("tradeable") else ["swing_gate"],
                "source": "swing_engine",
            })
    out.sort(key=lambda s: s.get("confidence", 0), reverse=True)
    return out


def _scalp_signals(snapshots: dict[str, SymbolSnapshot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for t in snap.suggestedTrades or []:
            conf = float(t.confidence or 0)
            side = t.side.value if hasattr(t.side, "value") else str(t.side)
            out.append({
                "id": _sig_id("scalp", sym, side, t.strike, t.id),
                "horizon": "SCALP",
                "symbol": sym,
                "side": side,
                "strike": t.strike,
                "premium": t.lastPremium,
                "confidence": conf,
                "tradeable": conf >= 50,
                "summary": f"{sym} {side} {t.strike} · TQS {t.tqs:.0f}",
                "detail": str(t.strategyType.value if hasattr(t.strategyType, "value") else t.strategyType),
                "targets": {"adaptiveTarget": t.adaptiveTarget},
                "blockers": [] if conf >= 50 else ["low_confidence"],
                "source": "suggested_trades",
            })
    out.sort(key=lambda s: s.get("confidence", 0), reverse=True)
    return out[:12]


def _strategy_signals(snapshots: dict[str, SymbolSnapshot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for entry in snap.strategyMatrix or []:
            if str(entry.get("status", "")).lower() not in ("active", "ready"):
                continue
            ml = float(entry.get("mlProbability") or 0)
            conf = float(entry.get("confidence") or 0)
            out.append({
                "id": _sig_id("strategy", sym, entry.get("id")),
                "horizon": "STRATEGY",
                "symbol": sym,
                "confidence": max(conf, ml * 100 if ml <= 1 else ml),
                "tradeable": ml >= 0.52 or conf >= 55,
                "summary": f"{entry.get('name')} · {sym}",
                "detail": f"ML win {ml * 100 if ml <= 1 else ml:.0f}%",
                "blockers": [] if ml >= 0.52 else ["ml_below_threshold"],
                "source": "strategy_matrix",
            })
    return out[:8]


def _premarket_signals(snapshots: dict[str, SymbolSnapshot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, snap in snapshots.items():
        pm = snap.premarket
        if not snap.dataAvailable or not pm:
            continue
        conf = float(pm.confidence or 0)
        out.append({
            "id": _sig_id("premarket", sym),
            "horizon": "OPEN",
            "symbol": sym,
            "confidence": conf,
            "tradeable": pm.openPlay not in ("WAIT", "MIXED_OPEN"),
            "summary": f"{sym} · {pm.openPlay} · gap {pm.gapDirection}",
            "detail": "; ".join((pm.scenarios or [])[:2]) or str(pm.analysis or "")[:120],
            "openPlay": pm.openPlay,
            "explosionRisk": pm.explosionRisk,
            "gapPct": pm.gapPct,
            "blockers": [] if pm.openPlay != "WAIT" else ["wait_for_open"],
            "source": "premarket",
        })
    return out


def _risk_signals(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    verdict = identify_worst_day(state, snapshots)
    if verdict.is_worst or verdict.early_prediction:
        out.append({
            "id": "risk:worst_day",
            "horizon": "RISK",
            "symbol": "SESSION",
            "confidence": verdict.score,
            "tradeable": False,
            "summary": "Worst-day forecast" + (" (early)" if verdict.early_prediction else ""),
            "detail": "; ".join(verdict.reasons[:4]),
            "blockers": verdict.reasons,
            "source": "worst_day_guard",
        })
    policy, meta = session_entry_policy(state, snapshots)
    if policy != "NORMAL":
        out.append({
            "id": "risk:entry_policy",
            "horizon": "RISK",
            "symbol": "SESSION",
            "confidence": 70.0,
            "tradeable": policy == "BREAKOUT_ONLY",
            "summary": f"Entry policy: {policy}",
            "detail": str(meta.get("message") or meta.get("reason") or policy),
            "blockers": [policy] if policy == "PAUSED" else [],
            "source": "session_entry_policy",
        })
    expiry = expiry_guard_summary(state, snapshots)
    if expiry.get("nearExpirySymbols"):
        out.append({
            "id": "risk:near_expiry",
            "horizon": "RISK",
            "symbol": ",".join(expiry.get("nearExpirySymbols") or []),
            "confidence": 60.0,
            "tradeable": bool(expiry.get("entriesAllowed")),
            "summary": f"Near-expiry: {', '.join(expiry.get('nearExpirySymbols') or [])}",
            "detail": str(expiry.get("blockReason") or "Pre-expiry routing may apply"),
            "blockers": [] if expiry.get("entriesAllowed") else [str(expiry.get("blockReason") or "blocked")],
            "source": "expiry_guards",
        })
    return out


def _brief_field(brief: Any, key: str, default: Any = None) -> Any:
    """Read composer brief fields from dict (API) or dataclass (in-process)."""
    if isinstance(brief, dict):
        return brief.get(key, default)
    return getattr(brief, key, default)


def _composer_signal() -> Optional[dict[str, Any]]:
    brief = get_latest_brief()
    if not brief:
        return None
    trade_bias = str(_brief_field(brief, "tradeBias", "STAND_ASIDE") or "STAND_ASIDE")
    confidence = str(_brief_field(brief, "confidence", "LOW") or "LOW")
    stand_down = bool(_brief_field(brief, "standDown", False))
    market_read = str(_brief_field(brief, "marketRead", "") or "")
    session_plan = str(_brief_field(brief, "sessionPlan", "") or "")
    conf_map = {"HIGH": 85, "MEDIUM": 55, "LOW": 30}
    return {
        "id": "advisory:composer",
        "horizon": "ADVISORY",
        "symbol": "SESSION",
        "side": trade_bias if trade_bias in ("CALL", "PUT") else None,
        "confidence": conf_map.get(confidence, 40),
        "tradeable": not stand_down and trade_bias not in ("STAND_ASIDE",),
        "summary": market_read[:140] if market_read else "Composer session read",
        "detail": session_plan,
        "tradeBias": trade_bias,
        "risks": _brief_field(brief, "risks", []) or [],
        "actions": _brief_field(brief, "actions", []) or [],
        "standDown": stand_down,
        "blockers": ["stand_down"] if stand_down else [],
        "source": "composer",
        "at": _brief_field(brief, "at"),
    }


def _playbook_signals(state: AutoTraderState) -> list[dict[str, Any]]:
    ds = state.dailyStrategy or {}
    if not ds:
        return []
    playbook = ds.get("playbook") or []
    if not playbook:
        return []
    return [{
        "id": "advisory:playbook",
        "horizon": "ADVISORY",
        "symbol": "SESSION",
        "confidence": float(ds.get("marketConfidence") or ds.get("progressPct") or 50),
        "tradeable": bool(ds.get("allowExplosion") or ds.get("allowQuickSideways")),
        "summary": str(ds.get("message") or ds.get("phase") or "Daily playbook"),
        "detail": " · ".join(str(p) for p in playbook[:4]),
        "phase": ds.get("phase"),
        "playbook": playbook,
        "blockers": [],
        "source": "daily_strategy",
    }]


def build_forward_signals(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> dict[str, Any]:
    """Aggregate forward-looking moments, setups, and risk into one dashboard payload."""
    state = state or get_state()
    chop = chop_guard_summary(state, snapshots)

    moments = _build_moments()
    signals: list[dict[str, Any]] = []
    signals.extend(_premarket_signals(snapshots))
    signals.extend(_explosion_signals(snapshots))
    signals.extend(_swing_signals(snapshots))
    signals.extend(_scalp_signals(snapshots))
    signals.extend(_strategy_signals(snapshots))
    signals.extend(_risk_signals(state, snapshots))
    signals.extend(_playbook_signals(state))
    composer = _composer_signal()
    if composer:
        signals.append(composer)

    tradeable = [s for s in signals if s.get("tradeable")]
    upcoming = [m for m in moments if m.get("status") == "UPCOMING"]
    live_moments = [m for m in moments if m.get("status") == "LIVE"]

    top_explosion = next((s for s in signals if s.get("horizon") == "EXPLOSION"), None)
    parts: list[str] = []
    if live_moments:
        parts.append(f"Live: {live_moments[0]['label']}")
    elif upcoming:
        parts.append(f"Next: {upcoming[0]['label']} in {upcoming[0].get('startsInMin')}m")
    if top_explosion:
        parts.append(top_explosion["summary"])
    if composer:
        parts.append(f"Bias {composer.get('tradeBias', '—')}")

    counts: dict[str, int] = {}
    for s in signals:
        h = str(s.get("horizon") or "OTHER")
        counts[h] = counts.get(h, 0) + 1

    from app.engines.morning_premium_capture import (
        in_all_day_explosion_window,
        in_afternoon_premium_capture_window,
        in_morning_premium_capture_window,
    )

    return {
        "at": datetime.now(IST).isoformat(),
        "summary": " · ".join(parts) if parts else "Scanning for forward setups",
        "moments": moments,
        "signals": signals[:40],
        "tradeableCount": len(tradeable),
        "counts": counts,
        "indexMoments": chop.get("indexMoments") or {},
        "windows": {
            "morningCapture": in_morning_premium_capture_window(),
            "afternoonCapture": in_afternoon_premium_capture_window(),
            "allDayExplosion": in_all_day_explosion_window(),
            "momentumRally": chop.get("momentumRallyWindow"),
        },
        "entriesAllowed": not bool(state.dailyProfitGate and state.dailyProfitGate.get("newEntriesAllowed") is False),
        "composer": composer,
    }
