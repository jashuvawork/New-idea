"""Aug 24 NIFTY PUT 24150 armed-base launch blocked by orderflow floor."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import Settings
from app.engines.ict_breakout_monitor import first_lift_entry_readiness


def _readiness_snapshot(*, tqs: float = 70.0):
    return SimpleNamespace(
        symbol="NIFTY",
        spot=24150.0,
        atmStrike=24150.0,
        tradeQualityScore=tqs,
        spotChart=SimpleNamespace(
            momentum5Pct=-0.08,
            momentum10Pct=-0.05,
            momentum15Pct=-0.02,
        ),
    )


def _aug24_24150_launch_alert(**overrides):
    """ELITE armed_base_launch at ~₹18.6 base with volume awakening but low absolute vol."""
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24150.0,
        "tier": "ELITE",
        "ictArmedBaseLaunch": True,
        "ictArmedBaseSustainedLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 8.0,
        "localBaseMovePct": 9.7,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseSpanSeconds": 20.0,
        "flatVerticalQuality": 70.0,
        "explosionScore": 100.0,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "volume": 0.0,
        "absoluteVolume": 0.0,
        "ictVolumeAwakening": True,
        "volumeAwaken": True,
        "orderflowConfirmed": False,
        "optionCvdBuying": False,
    }
    alert.update(overrides)
    return alert


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_aug24_24150_armed_launch_accepts_volume_awakening_as_orderflow(_open):
    settings = Settings()
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        ready, reason = first_lift_entry_readiness(
            snap=_readiness_snapshot(),
            alert=_aug24_24150_launch_alert(),
        )

    assert ready is True
    assert reason == "armed_base_option_led_ready"


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_aug24_24150_still_rejects_when_no_orderflow_or_volume_awakening(_open):
    settings = Settings()
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        ready, reason = first_lift_entry_readiness(
            snap=_readiness_snapshot(),
            alert=_aug24_24150_launch_alert(
                ictVolumeAwakening=False,
                volumeAwaken=False,
            ),
        )

    assert ready is False
    assert reason == "armed_base_orderflow_below_25000"
