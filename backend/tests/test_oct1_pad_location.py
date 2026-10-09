"""Side-aware Oct 1 pad location (CE session-high chase vs PE slide pad)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.engines.live_oct1_pad_entry_guard import live_oct1_pad_entry_blocked
from app.engines.oct1_pad_location import oct1_premium_location_chase_blocked
from app.models.schemas import Side
from tests.mock_defaults import settings_mock


def _parity_settings(**kwargs):
    return settings_mock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        **kwargs,
    )


def test_put_slide_at_option_session_high_not_chase_blocked():
    settings = _parity_settings()
    evidence = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 10.0,
        "offHighMovePct": 4.0,
    }
    blocked, reason = oct1_premium_location_chase_blocked(
        "PUT",
        0.95,
        0.0,
        evidence,
        settings=settings,
    )
    assert blocked is False
    assert reason == ""


def test_put_extended_dump_at_session_low_blocked():
    settings = _parity_settings()
    evidence = {
        "side": "PUT",
        "tier": "ELITE",
        "localBaseMovePct": 18.0,
        "ictBaseRelativeMovePct": 18.0,
    }
    blocked, reason = oct1_premium_location_chase_blocked(
        "PUT",
        0.02,
        -20.0,
        evidence,
        settings=settings,
    )
    assert blocked is True
    assert reason == "live_oct1_put_chase_at_session_low"


@patch(
    "app.engines.best_trade_policy.symmetric_best_trade_at_base_capture",
    return_value=(True, "near_base"),
)
def test_pad_guard_put_slide_waives_session_high(_base):
    settings = _parity_settings()
    alert = {
        "tier": "ELITE",
        "side": "PUT",
        "momentType": "v_rip_session_high",
        "localBaseMovePct": 9.0,
        "offHighMovePct": 3.5,
        "premium": 180.0,
        "sessionLowPremium": 120.0,
        "sessionPeakPremium": 185.0,
    }
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22400.0,
        premium=180.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "sessionRangePosition": 0.92},
    )
    blocked, reason, meta = live_oct1_pad_entry_blocked(cand, settings=settings)
    assert blocked is False
    assert meta.get("octOpenPutSlidePadWaive") or not reason


@patch(
    "app.engines.best_trade_policy.symmetric_best_trade_at_base_capture",
    return_value=(True, "near_base"),
)
def test_pad_guard_call_still_blocks_oct7_session_high_chase(_base):
    settings = _parity_settings()
    alert = {
        "tier": "EXPLODING",
        "side": "CALL",
        "momentType": "armed_base_launch",
        "localBaseMovePct": 6.81,
        "premium": 158.0,
        "armedBaseLaunch": True,
    }
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=158.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "sessionRangePosition": 0.98},
    )
    blocked, reason, _ = live_oct1_pad_entry_blocked(cand, settings=settings)
    assert blocked is True
    assert reason in (
        "live_oct1_chase_at_session_high",
        "live_oct1_chase_session_range_high",
    )
