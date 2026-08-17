"""Deterministic causal replays for the five executable Aug 17 missed truths."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import explosion_detector
from app.engines.ict_breakout_monitor import (
    _sustained_armed_base_lift,
    first_lift_entry_readiness,
)
from app.engines.explosion_detector import (
    armed_base_anchor,
    event_to_dict,
    scan_chain_explosions,
)
from app.models.schemas import Side


IST = ZoneInfo("Asia/Kolkata")


def _ready_sustained_lift_alert(**overrides):
    alert = {
        "side": "CALL",
        "strike": 24300.0,
        "ictArmedBaseLaunch": True,
        "ictArmedBaseSustainedLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 8.0,
        "ictArmedBaseSamples": 6,
        "ictArmedBaseSpanSeconds": 15.0,
        "flatVerticalQuality": 70.0,
        "explosionScore": 50.0,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "volume": 30_000.0,
    }
    alert.update(overrides)
    return alert


def _readiness_snapshot(*, tqs: float = 70.0):
    return SimpleNamespace(
        symbol="NIFTY",
        spot=24300.0,
        atmStrike=24300.0,
        tradeQualityScore=tqs,
        spotChart=SimpleNamespace(
            momentum5Pct=0.0,
            momentum10Pct=0.0,
            momentum15Pct=0.0,
        ),
    )


@pytest.mark.parametrize(
    ("symbol", "side", "strike", "spot", "atm", "base", "lift"),
    [
        ("NIFTY", Side.PUT, 24300.0, 24351.2, 24350.0, 27.35, 29.80),
        ("NIFTY", Side.PUT, 24350.0, 24351.2, 24350.0, 42.70, 46.20),
        ("NIFTY", Side.PUT, 24400.0, 24351.2, 24350.0, 64.45, 71.45),
        ("SENSEX", Side.CALL, 77700.0, 77662.38, 77700.0, 378.05, 410.40),
        ("SENSEX", Side.CALL, 77600.0, 77694.16, 77700.0, 446.95, 488.70),
    ],
)
@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_aug17_missed_truth_arms_and_surfaces_before_vertical(
    _open,
    symbol,
    side,
    strike,
    spot,
    atm,
    base,
    lift,
):
    settings = Settings()
    current = datetime(2026, 8, 17, 12, 30, tzinfo=IST)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

    option_key = "call_options" if side == Side.CALL else "put_options"

    def scan(premium: float):
        nonlocal current
        events = scan_chain_explosions(
            symbol,
            [{
                "strike_price": strike,
                option_key: {"ltp": premium, "volume": 100_000},
            }],
            spot=spot,
            atm=atm,
        )
        current += timedelta(seconds=15)
        match = next(
            (event for event in events if event.side == side and event.strike == strike),
            None,
        )
        return event_to_dict(match) if match else None

    base_samples = (
        base,
        base * 1.006,
        base * 0.998,
        base * 1.004,
        base,
        base * 1.003,
        base * 1.001,
        base * 1.002,
    )
    lift_path = (base * 1.035, base * 1.06, lift)

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", _Clock),
    ):
        for premium in base_samples:
            scan(premium)
        armed = armed_base_anchor(symbol, strike, side, base)
        assert armed["armed"] is True
        assert armed["sampleCount"] >= 6

        launch = None
        for premium in lift_path:
            launch = scan(premium)

    assert launch is not None
    assert launch["ictArmedBaseLaunch"] is True
    assert launch["ictArmedBaseSustainedLift"] is True
    assert launch["tradeable"] is True
    assert launch["tier"] in {"BUILDING", "EXPLODING", "ELITE"}
    assert launch["explosionScore"] >= 50


def test_sustained_lift_rejects_insufficient_progress():
    settings = Settings()
    start = datetime(2026, 8, 17, 12, 30, tzinfo=IST)
    history = [
        (start, 106.5, 100_000),
        (start + timedelta(seconds=10), 107.0, 100_000),
        (start + timedelta(seconds=20), 108.0, 100_000),
    ]

    assert _sustained_armed_base_lift(
        history,
        base_premium=100.0,
        premium=108.0,
        base_move_pct=8.0,
        settings=settings,
    ) is False


def test_sustained_lift_rejects_excessive_fade():
    settings = Settings()
    start = datetime(2026, 8, 17, 12, 30, tzinfo=IST)
    history = [
        (start, 100.0, 100_000),
        (start + timedelta(seconds=10), 112.0, 100_000),
        (start + timedelta(seconds=20), 108.0, 100_000),
    ]

    assert _sustained_armed_base_lift(
        history,
        base_premium=100.0,
        premium=108.0,
        base_move_pct=8.0,
        settings=settings,
    ) is False


@pytest.mark.parametrize(
    "offsets",
    [
        (0, 20),
        (0, 7, 14),
    ],
    ids=["insufficient-sample-count", "insufficient-sample-span"],
)
def test_sustained_lift_rejects_insufficient_samples_or_span(offsets):
    settings = Settings()
    start = datetime(2026, 8, 17, 12, 30, tzinfo=IST)
    history = [
        (start + timedelta(seconds=offset), 100.0 + index * 4.0, 100_000)
        for index, offset in enumerate(offsets)
    ]

    assert _sustained_armed_base_lift(
        history,
        base_premium=100.0,
        premium=108.0,
        base_move_pct=8.0,
        settings=settings,
    ) is False


@pytest.mark.parametrize(
    ("alert", "tqs", "expected_reason"),
    [
        (
            _ready_sustained_lift_alert(volume=0.0),
            70.0,
            "armed_base_orderflow_below_25000",
        ),
        (
            _ready_sustained_lift_alert(),
            49.0,
            "armed_base_tqs<50",
        ),
    ],
    ids=["weak-orderflow", "weak-tqs"],
)
def test_sustained_lift_rejects_weak_orderflow_or_tqs(
    alert,
    tqs,
    expected_reason,
):
    settings = Settings()
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        ready, reason = first_lift_entry_readiness(
            snap=_readiness_snapshot(tqs=tqs),
            alert=alert,
        )

    assert ready is False
    assert reason == expected_reason


def test_sustained_lift_hard_rejects_otm_contract():
    settings = Settings()
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        ready, reason = first_lift_entry_readiness(
            snap=_readiness_snapshot(),
            alert=_ready_sustained_lift_alert(strike=24400.0),
        )

    assert ready is False
    assert reason == "armed_base_requires_atm_itm_otm"
