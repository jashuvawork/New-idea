"""Sep07 session fixes — deep ITM substitute block + near-strike near-miss waive."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import deep_itm_near_strike_substitute_blocked
from app.engines.rally_capture import near_strike_armed_near_miss_waive
from app.models.schemas import MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = SimpleNamespace(
        explosion_deep_itm_substitute_block_enabled=True,
        explosion_deep_itm_substitute_min_itm_steps=1,
        explosion_deep_itm_substitute_near_strike_max_steps=2,
        near_strike_armed_near_miss_waive_enabled=True,
        near_strike_armed_near_miss_min_grade="S",
        near_strike_armed_near_miss_max_steps=2,
        near_strike_armed_near_miss_max_local_pct=15.0,
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(alerts=None, spot=23837.0, atm=23850.0):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=spot,
        atmStrike=atm,
        dataAvailable=True,
        explosionAlerts=alerts or [],
    )


def test_blocks_deep_itm_when_near_strike_armed_on_same_side():
    """Sep07: 23900 ITM must not enter when 23750 near-strike armed is live."""
    alerts = [
        {
            "side": "PUT",
            "strike": 23750.0,
            "tier": "ELITE",
            "strikeStepsFromAtm": 2,
            "moneyness": "OTM",
            "ictArmedBaseLaunch": True,
            "momentType": "armed_base_launch",
        },
    ]
    snap = _snap(alerts)
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(),
    ):
        blocked, reason = deep_itm_near_strike_substitute_blocked(
            Side.PUT,
            23900.0,
            snap,
        )
    assert blocked is True
    assert reason == "explosion_deep_itm_near_strike_substitute"


def test_allows_deep_itm_when_no_near_strike_armed_alternative():
    snap = _snap([])
    with patch(
        "app.engines.explosion_entry_guards.get_settings",
        return_value=_settings(),
    ):
        blocked, _ = deep_itm_near_strike_substitute_blocked(
            Side.PUT,
            23900.0,
            snap,
        )
    assert blocked is False


def test_near_strike_armed_near_miss_waive_grade_s_at_base():
    """Sep07 23750 PE: grade-S armed launch at ~8% local base."""
    alert = {
        "causalGrade": "S",
        "tier": "ELITE",
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "momentType": "armed_base_launch",
        "localBaseMovePct": 8.0,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert near_strike_armed_near_miss_waive(alert) is True


def test_near_strike_armed_near_miss_waive_call_mirror():
    alert = {
        "causalGrade": "S",
        "tier": "EXPLODING",
        "strikeStepsFromAtm": 1,
        "moneyness": "OTM",
        "armedBaseLaunch": True,
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 10.0,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert near_strike_armed_near_miss_waive(alert) is True


def test_near_strike_near_miss_blocks_chase_above_local_cap():
    alert = {
        "causalGrade": "S",
        "tier": "ELITE",
        "strikeStepsFromAtm": 2,
        "moneyness": "OTM",
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 22.0,
    }
    with patch(
        "app.engines.rally_capture.get_settings",
        return_value=_settings(),
    ):
        assert near_strike_armed_near_miss_waive(alert) is False
