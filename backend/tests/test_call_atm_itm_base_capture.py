"""CE ATM/ITM base capture — rank + chop-deep waive (all session days)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    call_atm_itm_base_capture_eligible,
    call_atm_itm_base_selector_rank_delta,
    symbols_with_call_atm_itm_base_ready,
)
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock


def _snap(*, spot: float = 74050.0, atm: float = 74000.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-09-17T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=spot,
        atmStrike=atm,
        dataAvailable=True,
    )


def _call(*, strike: float = 73900.0, alert: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        mode="explosion",
        symbol="SENSEX",
        side=Side.CALL,
        strike=strike,
        premium=320.0,
        alert=alert or {},
        pretrade_meta={},
        snap=_snap(),
    )


def test_atm_itm_call_at_base_eligible():
    s = settings_mock()
    snap = _snap()
    alert = {
        "tier": "EXPLODING",
        "armedBaseLaunch": True,
        "ictFirstLift": True,
        "localBaseMovePct": 11.0,
        "ictBaseRelativeMovePct": 11.0,
    }
    cand = _call(strike=73900.0, alert=alert)
    ok, meta = call_atm_itm_base_capture_eligible(cand, snap, settings=s)
    assert ok is True
    assert meta["moneyness"] == "ITM"


def test_otm_call_not_eligible_for_atm_itm_path():
    s = settings_mock()
    snap = _snap(spot=74050.0)
    alert = {
        "tier": "ELITE",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 8.0,
    }
    cand = _call(strike=74500.0, alert=alert)
    ok, meta = call_atm_itm_base_capture_eligible(cand, snap, settings=s)
    assert ok is False
    assert meta.get("moneyness") == "OTM"


def test_chop_deep_waived_for_atm_itm_call_at_base():
    s = settings_mock()
    snap = _snap()
    alert = {
        "tier": "EXPLODING",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 12.0,
        "setup": "FTV",
    }
    cand = _call(strike=74000.0, alert=alert)
    cand.premium = 410.0
    cand.snap = snap
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        {"dayMode": "CHOP DAY", "localBasePct": 12.0, "setup": "FTV"},
        day_mode="CHOP DAY",
        settings=s,
    )
    assert blocked is False
    assert reason == ""


def test_put_rank_penalty_when_call_atm_itm_base_ready():
    s = settings_mock()
    snap = _snap()
    snapshots = {"SENSEX": snap}
    call_alert = {
        "tier": "BUILDING",
        "armedBaseLaunch": True,
        "ictFirstLift": True,
        "localBaseMovePct": 9.0,
    }
    call_c = _call(strike=73900.0, alert=call_alert)
    put_c = SimpleNamespace(
        mode="explosion",
        symbol="SENSEX",
        side=Side.PUT,
        strike=74100.0,
        alert={"tier": "ELITE", "score": 90},
        pretrade_meta={},
        snap=snap,
    )
    syms = symbols_with_call_atm_itm_base_ready(
        [call_c, put_c], MagicMock(), snapshots, settings=s,
    )
    assert "SENSEX" in syms
    call_delta = call_atm_itm_base_selector_rank_delta(
        call_c, MagicMock(), snapshots, symbols_call_atm_itm_base=syms, settings=s,
    )
    put_delta = call_atm_itm_base_selector_rank_delta(
        put_c, MagicMock(), snapshots, symbols_call_atm_itm_base=syms, settings=s,
    )
    assert call_delta == 44.0
    assert put_delta == -36.0
