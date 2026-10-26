"""CE ATM/ITM base capture — rank + chop-deep waive (all session days)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    call_atm_itm_base_capture_eligible,
    call_atm_itm_base_selector_rank_delta,
    call_atm_itm_near_base_pad,
    symbols_with_call_atm_itm_base_ready,
)
from app.engines.rally_capture import explosion_near_miss_waive
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


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


def test_symbols_ready_when_near_base_pad_without_full_eligible():
    """#676 PUT −36 must arm when CE passes the lighter near-base pad bar only."""
    s = settings_mock()
    snap = _nifty_snap()
    snapshots = {"NIFTY": snap}
    alert = _oct23_base_alert(
        momentType="v_rip_session_low",
        offLowMovePct=17.0,
        localBaseMovePct=9.0,
        ictBaseRelativeMovePct=9.0,
        vRipReady=True,
        ictVRipReady=True,
    )
    call_c = _call(strike=22400.0, alert=alert)
    call_c.symbol = "NIFTY"
    call_c.snap = snap
    put_c = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22450.0,
        alert={"tier": "ELITE", "score": 92},
        pretrade_meta={},
        snap=snap,
    )
    with patch(
        "app.engines.best_trade_policy.call_atm_itm_base_capture_eligible",
        return_value=(False, {"reason": "launch_not_confirmed"}),
    ):
        syms = symbols_with_call_atm_itm_base_ready(
            [call_c, put_c], MagicMock(), snapshots, settings=s,
        )
    assert "NIFTY" in syms
    put_delta = call_atm_itm_base_selector_rank_delta(
        put_c, MagicMock(), snapshots, symbols_call_atm_itm_base=syms, settings=s,
    )
    assert put_delta == -36.0


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


def _nifty_snap(*, spot: float = 22429.0, atm: float = 22400.0, tqs: float = 28.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 10, 23, 13, 34, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=spot,
        atmStrike=atm,
        dataAvailable=True,
        tradeQualityScore=tqs,
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias="NEUTRAL", score=40.0, aligned=False),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.04,
            momentum10Pct=0.02,
            momentum15Pct=0.01,
        ),
    )


def _oct23_base_alert(**overrides) -> dict:
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22400.0,
        "tier": "EXPLODING",
        "momentType": "armed_base_launch",
        "ictBaseArmed": True,
        "ictArmedBaseLaunch": True,
        "armedBaseLaunch": True,
        "ictFirstLift": False,
        "firstLift": False,
        "ictBaseRelativeMovePct": 8.0,
        "localBaseMovePct": 8.0,
        "explosionScore": 93.0,
        "flatVerticalQuality": 70.0,
        "velocity3s": -0.4,
        "velocity9s": 0.1,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "volume": 2_000_000,
        "volumeSurge": 2.5,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseSpanSeconds": 20.0,
        "tradeQualityScore": 28.0,
    }
    alert.update(overrides)
    return alert


def test_oct23_atm_call_on_the_base_waives_chop_without_first_lift():
    """13:34 IST was the low. Armed base without a hot lift is still the #676 call."""
    s = settings_mock()
    snap = _nifty_snap()
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22400.0,
        premium=190.0,
        tier="EXPLODING",
        alert=_oct23_base_alert(),
        pretrade_meta={},
        snap=snap,
    )
    ok, meta = call_atm_itm_base_capture_eligible(cand, snap, settings=s)
    assert ok is True
    assert meta["moneyness"] == "ATM"
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        {"dayMode": "CHOP DAY", "localBasePct": 8.0, "setup": "EXPLOSIVE", "eliteScore": 72.0},
        day_mode="CHOP DAY",
        settings=s,
    )
    assert blocked is False
    assert reason == ""


def test_oct23_v_rip_at_the_low_is_the_same_base():
    s = settings_mock()
    snap = _nifty_snap()
    alert = _oct23_base_alert(
        strike=22350.0,
        momentType="v_rip_session_low",
        ictBaseArmed=False,
        ictArmedBaseLaunch=False,
        armedBaseLaunch=False,
        ictVRipReady=True,
        vRipReady=True,
        ictBaseRelativeMovePct=11.0,
        localBaseMovePct=11.0,
    )
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22350.0,
        premium=220.0,
        tier="EXPLODING",
        alert=alert,
        pretrade_meta={},
        snap=snap,
    )
    ok, meta = call_atm_itm_base_capture_eligible(cand, snap, settings=s)
    assert ok is True
    assert meta["moneyness"] in ("ATM", "ITM")
    assert meta.get("nearBasePad") is True


def test_extended_or_otm_call_stays_a_chop_chase():
    s = settings_mock()
    snap = _nifty_snap(spot=22522.0, atm=22500.0)
    extended = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22400.0,
        premium=269.0,
        tier="EXPLODING",
        alert=_oct23_base_alert(
            localBaseMovePct=28.0,
            ictBaseRelativeMovePct=28.0,
        ),
        pretrade_meta={},
        snap=snap,
    )
    ok, _ = call_atm_itm_base_capture_eligible(extended, snap, settings=s)
    assert ok is False
    blocked, reason = best_trade_chop_deep_chase_blocked(
        extended,
        {},
        {"dayMode": "CHOP DAY", "localBasePct": 28.0, "setup": "EXPLOSIVE"},
        day_mode="CHOP DAY",
        settings=s,
    )
    assert blocked is True
    assert reason == "best_trade_block_chop_deep_itm_chase"

    otm = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22650.0,
        premium=120.35,
        tier="ELITE",
        alert=_oct23_base_alert(strike=22650.0, tier="ELITE"),
        pretrade_meta={},
        snap=snap,
    )
    ok, meta = call_atm_itm_base_capture_eligible(otm, snap, settings=s)
    assert ok is False
    assert meta.get("moneyness") == "OTM"
    blocked, reason = best_trade_chop_deep_chase_blocked(
        otm,
        {},
        {"dayMode": "CHOP DAY", "localBasePct": 8.0, "setup": "EXPLOSIVE"},
        day_mode="CHOP DAY",
        settings=s,
    )
    assert blocked is True
    assert reason == "best_trade_block_chop_deep_itm_chase"


def test_cold_velocity_on_the_atm_base_is_not_a_reject():
    ranking = rank_trade_evidence(_oct23_base_alert(spot=22429.0, atmStrike=22400.0))
    assert ranking["grade"] != "REJECT"
    extended = rank_trade_evidence(
        _oct23_base_alert(
            spot=22522.0,
            atmStrike=22500.0,
            localBaseMovePct=28.0,
            ictBaseRelativeMovePct=28.0,
            velocity3s=-0.4,
        )
    )
    assert extended["grade"] == "REJECT"


def test_oct23_index_led_off_low_18pct_still_on_structural_pad():
    """13:34 tape: offLow ~16–19% while local base ~8–11% and v-rip at session low."""
    s = settings_mock()
    snap = _nifty_snap()
    alert = _oct23_base_alert(
        momentType="v_rip_session_low",
        localBaseMovePct=10.0,
        ictBaseRelativeMovePct=10.0,
        offLowMovePct=18.0,
        ictVRipReady=True,
        vRipReady=True,
    )
    assert call_atm_itm_near_base_pad(alert, snap, settings=s) is True
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22400.0,
        premium=200.0,
        tier="EXPLODING",
        alert=alert,
        pretrade_meta={},
        snap=snap,
    )
    ok, meta = call_atm_itm_base_capture_eligible(cand, snap, settings=s)
    assert ok is True
    assert meta.get("indexLedPad") is True


def test_index_led_does_not_widen_structural_pad():
    s = settings_mock()
    snap = _nifty_snap()
    alert = _oct23_base_alert(
        momentType="v_rip_session_low",
        localBaseMovePct=28.0,
        ictBaseRelativeMovePct=28.0,
        offLowMovePct=18.0,
    )
    assert call_atm_itm_near_base_pad(alert, snap, settings=s) is False


def test_near_base_call_waives_structure_near_miss():
    s = settings_mock()
    snap = _nifty_snap()
    alert = _oct23_base_alert(
        momentType="v_rip_session_low",
        offLowMovePct=17.0,
        localBaseMovePct=9.0,
        ictBaseRelativeMovePct=9.0,
    )
    assert explosion_near_miss_waive(
        alert,
        snap=snap,
        readiness_reason="first_lift_structure_not_confirmed",
        settings=s,
    )


def test_cold_armed_base_call_clears_first_lift_velocity_and_tqs():
    snap = _nifty_snap()
    ready, reason = first_lift_entry_readiness(snap=snap, alert=_oct23_base_alert())
    assert ready is True, reason
    assert reason != "first_lift_live_velocity_negative"
    assert not str(reason).startswith("first_lift_velocity3s")
    assert not str(reason).startswith("armed_base_tqs")

    put_snap = _nifty_snap()
    put_ready, put_reason = first_lift_entry_readiness(
        snap=put_snap,
        alert=_oct23_base_alert(side="PUT", strike=22450.0),
    )
    assert put_ready is False
    assert put_reason == "first_lift_live_velocity_negative"
