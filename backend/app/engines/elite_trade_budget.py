"""Weekly Elite trade budget — hybrid cap with must-take override."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_BUDGET_KEY = "eliteTradeBudget"


def _iso_week(dt: datetime | None = None) -> str:
    ts = dt or datetime.now(IST)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    else:
        ts = ts.astimezone(IST)
    return ts.strftime("%G-W%V")


def _budget_store(state: Any) -> dict[str, Any]:
    ds = getattr(state, "dailyStrategy", None)
    if not isinstance(ds, dict):
        ds = {}
        state.dailyStrategy = ds
    raw = ds.get(_BUDGET_KEY)
    return raw if isinstance(raw, dict) else {}


def _write_budget_store(state: Any, payload: dict[str, Any]) -> None:
    ds = getattr(state, "dailyStrategy", None)
    if not isinstance(ds, dict):
        ds = {}
    ds[_BUDGET_KEY] = payload
    state.dailyStrategy = ds


def elite_trade_budget_summary(
    state: Any,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """Observability payload for deployment HUD / chop guards."""
    from app.config import get_settings

    settings = settings or get_settings()
    enabled = bool(getattr(settings, "elite_trade_engine_enabled", True))
    weekly_cap = int(getattr(settings, "elite_trade_weekly_cap", 8) or 8)
    week = _iso_week()
    store = _budget_store(state)
    store_week = str(store.get("isoWeek") or "")
    entries_used = int(store.get("entriesUsed") or 0) if store_week == week else 0
    must_take_used = int(store.get("mustTakeUsed") or 0) if store_week == week else 0

    return {
        "enabled": enabled,
        "isoWeek": week,
        "weeklyCap": weekly_cap,
        "entriesUsed": entries_used,
        "entriesRemaining": max(0, weekly_cap - entries_used),
        "mustTakeUsed": must_take_used,
        "capReached": enabled and entries_used >= weekly_cap,
        "lastEntry": store.get("lastEntry") if store_week == week else None,
        "winRateGates": __elite_win_rate_gate_summary(settings),
    }


def __elite_win_rate_gate_summary(settings: Any) -> dict[str, Any]:
    from app.engines.elite_score_engine import elite_win_rate_gate_summary

    return elite_win_rate_gate_summary(settings=settings)


def elite_trade_budget_allows(
    state: Any,
    assessment: Mapping[str, Any],
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """True when weekly cap has room or this is a must-take FTV."""
    from app.config import get_settings

    settings = settings or get_settings()
    summary = elite_trade_budget_summary(state, settings=settings)

    if not summary["enabled"]:
        return True, "disabled", summary

    if bool(assessment.get("mustTake")):
        return True, "must_take_bypass", summary

    if summary["capReached"]:
        return False, "elite_weekly_cap_reached", summary

    return True, "ok", summary


def elite_budget_blocks_entry(
    state: Any,
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    settings: Any = None,
    snapshots: Any = None,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, assessment) for order-boundary weekly cap."""
    from app.config import get_settings
    from app.engines.elite_score_engine import elite_entry_allowed

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_trade_engine_enabled", False)):
        return False, "disabled", {}

    ok, reason, assessment = elite_entry_allowed(
        evidence,
        ranking,
        settings=settings,
        day_mode=day_mode,
        state=state,
        snapshots=snapshots,
        confidence_tier=confidence_tier,
    )
    if not ok:
        return True, reason, assessment

    budget_ok, budget_reason, _ = elite_trade_budget_allows(
        state, assessment, settings=settings,
    )
    if not budget_ok:
        return True, budget_reason, assessment
    return False, "ok", assessment


def record_elite_trade_entry(
    state: Any,
    assessment: Mapping[str, Any],
    *,
    symbol: str = "",
    side: str = "",
    strike: float = 0.0,
    settings: Any = None,
) -> dict[str, Any]:
    """Increment weekly Elite trade counter after a successful entry."""
    from app.config import get_settings

    settings = settings or get_settings()
    week = _iso_week()
    store = _budget_store(state)
    if str(store.get("isoWeek") or "") != week:
        store = {"isoWeek": week, "entriesUsed": 0, "mustTakeUsed": 0}

    store["entriesUsed"] = int(store.get("entriesUsed") or 0) + 1
    if bool(assessment.get("mustTake")):
        store["mustTakeUsed"] = int(store.get("mustTakeUsed") or 0) + 1
    store["lastEntry"] = {
        "symbol": symbol,
        "side": side,
        "strike": strike,
        "eliteScore": assessment.get("eliteScore"),
        "eliteBand": assessment.get("eliteBand"),
        "setup": assessment.get("setup"),
        "stage": assessment.get("stage"),
        "mustTake": bool(assessment.get("mustTake")),
    }
    _write_budget_store(state, store)
    return elite_trade_budget_summary(state, settings=settings)
