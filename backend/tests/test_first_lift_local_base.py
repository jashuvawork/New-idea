"""First lift off the lowest flat→vertical local base — appear at ~15%, not chase."""

from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_detector import (
    _history,
    _local_base_hist,
    _open_key,
    _strike_key,
    event_to_dict,
    scan_chain_explosions,
)
from app.engines.ict_breakout_monitor import (
    _detect_flat_base,
    _detect_recent_window_base,
    analyze_ict_breakout,
    first_lift_entry_ready,
)
from app.engines.winner_entry_guards import chop_weak_explosion_blocks_entry
from app.models.schemas import (
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 12.0
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_flat_base_use_lowest = True
    s.ict_displacement_min_velocity_3s = 2.2
    s.ict_vertical_min_session_move_pct = 80.0
    s.ict_early_vertical_min_session_move_pct = 12.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_volume_surge_awaken_min = 2.0
    s.ict_mega_rip_min_session_move_pct = 200.0
    s.ict_breakout_min_score = 28.0
    s.ict_fvg_score_bonus = 14.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 22.0
    s.ict_max_rank_bonus = 30.0
    s.explosion_volume_awaken_min = 25000
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_structured_early_max_move_pct = 65.0
    s.elite_local_base_max_move_pct = 40.0
    s.ict_first_lift_appear_enabled = True
    s.ict_first_lift_min_velocity_3s = 1.2
    s.first_lift_trade_enabled = True
    s.first_lift_trade_min_score = 45.0
    s.first_lift_trade_min_quality = 55.0
    s.first_lift_trade_min_volume_surge = 2.0
    s.first_lift_trade_min_velocity_3s = 1.2
    s.first_lift_trade_min_velocity_9s = 0.8
    s.first_lift_trade_max_move_pct = 25.0
    s.first_lift_trade_min_momentum_shift_pct = 0.03
    s.session_move_max_credible_pct = 500.0
    s.explosion_immature_min_session_move_pct = 28.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _seed_flat_then_lift(*, lift_premium: float) -> None:
    """Flat trough at 89–92 then first lift — true low is 89, not the avg (~90.5)."""
    symbol, strike, side = "NIFTY", 24350.0, Side.CALL
    key = _strike_key(strike, side)
    base = datetime.now(IST) - timedelta(seconds=120)
    hist = deque(maxlen=40)
    for i, prem in enumerate([91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0]):
        hist.append((base + timedelta(seconds=i * 5), prem, 12000))
    hist.append((base + timedelta(seconds=45), lift_premium, 160000))
    _history.setdefault(symbol, {})[key] = hist


def test_flat_base_uses_lowest_premium_not_average():
    settings = _settings()
    base_t = datetime.now(IST)
    history = [
        (base_t + timedelta(seconds=i), p, 1000.0)
        for i, p in enumerate([91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0, 95.0, 102.0])
    ]
    flat, _dev, level = _detect_flat_base(history, settings)
    assert flat is True
    assert level == 89.0  # trough, not ~90.5 avg


def test_flat_base_can_use_average_when_disabled():
    settings = _settings(ict_flat_base_use_lowest=False)
    base_t = datetime.now(IST)
    history = [
        (base_t + timedelta(seconds=i), p, 1000.0)
        for i, p in enumerate([91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0, 95.0, 102.0])
    ]
    flat, _dev, level = _detect_flat_base(history, settings)
    assert flat is True
    assert level > 89.0


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_appears_at_15pct_off_lowest_base(mock_settings):
    mock_settings.return_value = _settings()
    # 89 → 102.35 ≈ 15% off the trough
    _seed_flat_then_lift(lift_premium=102.35)
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24350.0,
        premium=102.35,
        session_move_pct=15.0,
        peak_move_pct=15.0,
        velocity_3s=2.4,
        volume_surge=3.5,
        volume=160000,
        tier="BUILDING",
        reason="volAwaken",
    )
    assert ict.base_premium == 89.0
    assert 14.0 <= ict.base_relative_move_pct <= 16.5
    assert ict.first_lift is True
    assert ict.flat_then_vertical is True
    assert ict.active is True
    assert any("first_lift_local_base" in r for r in ict.reasons)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_recent_flat_trough_wins_over_older_session_low(mock_settings):
    """An earlier deep low must not turn a fresh 15% coil break into a 46% chase."""
    mock_settings.return_value = _settings()
    _seed_flat_then_lift(lift_premium=102.35)

    with (
        patch(
            "app.engines.ict_breakout_monitor._detect_local_swing_base",
            return_value=(True, 70.0, 46.2),
        ),
        patch(
            "app.engines.explosion_detector.get_session_low_premium",
            return_value=70.0,
        ),
    ):
        ict = analyze_ict_breakout(
            symbol="NIFTY",
            side=Side.CALL,
            strike=24350.0,
            premium=102.35,
            session_move_pct=46.2,
            peak_move_pct=46.2,
            velocity_3s=2.4,
            volume_surge=3.5,
            volume=160000,
            tier="BUILDING",
            reason="volAwaken",
        )

    assert ict.base_premium == 89.0
    assert 14.0 <= ict.base_relative_move_pct <= 16.5
    assert ict.first_lift is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_chase_past_40pct_is_not_first_lift(mock_settings):
    mock_settings.return_value = _settings()
    # 89 → 131 ≈ 47% — Aug14-style chase print
    _seed_flat_then_lift(lift_premium=131.0)
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24350.0,
        premium=131.0,
        session_move_pct=47.0,
        peak_move_pct=47.0,
        velocity_3s=0.2,
        volume_surge=2.0,
        volume=160000,
        tier="ELITE",
        reason="volAwaken",
    )
    assert ict.base_premium == 89.0
    assert ict.base_relative_move_pct >= 40.0
    assert ict.first_lift is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_long_five_minute_style_base_reaches_first_lift(
    mock_settings, side,
):
    """A 10-minute U/flat base survives beyond the two-minute velocity tape."""
    settings = _settings()
    mock_settings.return_value = settings
    symbol, strike = "SENSEX", 77900.0
    now = datetime.now(IST)
    base_rows = [
            (now - timedelta(seconds=600 - i * 55), premium)
            for i, premium in enumerate(
                [92.0, 91.0, 90.0, 89.0, 89.5, 90.0, 89.0, 90.5, 91.0, 92.0]
            )
    ]
    base_rows.append((now, 102.35))
    _local_base_hist[_open_key(symbol, strike, side)] = deque(
        base_rows,
        maxlen=1200,
    )
    # Only the recent staircase is visible to the fast 120s history. It is too
    # short/wide to qualify as a flat base on its own.
    _history.setdefault(symbol, {})[_strike_key(strike, side)] = deque(
        [
            (now - timedelta(seconds=18), 94.0, 10_000),
            (now - timedelta(seconds=12), 97.0, 20_000),
            (now - timedelta(seconds=6), 100.0, 40_000),
            (now, 102.35, 80_000),
        ],
        maxlen=240,
    )

    ict = analyze_ict_breakout(
        symbol=symbol,
        side=side,
        strike=strike,
        premium=102.35,
        session_move_pct=15.0,
        peak_move_pct=15.0,
        velocity_3s=1.4,
        velocity_9s=1.0,
        volume_surge=3.0,
        volume=80_000,
        tier="WATCH",
    )

    assert ict.local_swing_base is True
    assert ict.base_premium == 89.0
    assert 14.0 <= ict.base_relative_move_pct <= 16.5
    assert ict.first_lift is True
    assert ict.active is True
    assert any("recent_window_base" in reason for reason in ict.reasons)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_recent_window_base_rejects_single_bad_tick(mock_settings):
    settings = _settings()
    mock_settings.return_value = settings
    symbol, strike, side = "NIFTY", 24350.0, Side.CALL
    now = datetime.now(IST)
    _local_base_hist[_open_key(symbol, strike, side)] = deque(
        [
            (now - timedelta(seconds=300), 89.0),
            (now - timedelta(seconds=240), 100.0),
            (now - timedelta(seconds=180), 101.0),
            (now - timedelta(seconds=120), 100.5),
            (now - timedelta(seconds=90), 101.5),
            (now - timedelta(seconds=60), 102.0),
            (now, 104.0),
        ],
        maxlen=1200,
    )

    found, _base, _move = _detect_recent_window_base(
        symbol=symbol,
        strike=strike,
        side=side,
        premium=104.0,
        settings=settings,
    )

    assert found is False


@pytest.mark.parametrize(
    ("side", "mom5", "mom10", "mom15"),
    [
        (Side.CALL, 0.06, 0.01, -0.05),
        (Side.PUT, -0.06, -0.01, 0.05),
    ],
)
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_high_quality_first_lift_is_actionable_before_tier_upgrade(
    mock_settings, side, mom5, mom10, mom15,
):
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24300.0,
        atmStrike=24300.0,
        spotChart=SpotChart(
            direction="NEUTRAL",
            momentum5Pct=mom5,
            momentum10Pct=mom10,
            momentum15Pct=mom15,
        ),
    )
    alert = {
        "side": side.value,
        "tier": "WATCH",
        "ictFirstLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 15.0,
        "flatVerticalQuality": 61.0,
        "explosionScore": 51.0,
        "velocity3s": 1.35,
        "velocity9s": 1.35,
        "volumeSurge": 4.0,
        "ictVolumeAwakening": True,
    }

    assert first_lift_entry_ready(snap=snap, alert=alert) is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_does_not_trade_without_quality_and_live_turn(mock_settings):
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24300.0,
        atmStrike=24300.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.10,
            momentum10Pct=-0.05,
            momentum15Pct=0.0,
        ),
    )
    event = SimpleNamespace(
        side=Side.CALL,
        explosion_score=51.0,
        velocity_3s=1.35,
        velocity_9s=1.35,
        volume_surge=4.0,
    )
    ict = SimpleNamespace(
        active=True,
        first_lift=True,
        flat_then_vertical=True,
        base_relative_move_pct=15.0,
        flat_vertical_quality=50.0,
        volume_awakening=True,
        volume_surge=4.0,
    )

    assert first_lift_entry_ready(
        snap=snap, event=event, ict=ict,
    ) is False


@patch("app.engines.winner_entry_guards.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_confirmed_first_lift_is_not_blocked_as_immature_chop(
    mock_ict_settings, mock_guard_settings,
):
    settings = _settings()
    mock_ict_settings.return_value = settings
    mock_guard_settings.return_value = settings
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24300.0,
        atmStrike=24300.0,
        regime=Regime.RANGE_BOUND,
        spotChart=SpotChart(
            direction="NEUTRAL",
            momentum5Pct=0.06,
            momentum10Pct=0.01,
            momentum15Pct=-0.05,
            trendStrength=30.0,
        ),
    )
    event = SimpleNamespace(
        side=Side.CALL,
        tier="WATCH",
        explosion_score=51.0,
        velocity_3s=1.35,
        velocity_9s=1.35,
        volume_surge=4.0,
        daily_move_pct=15.0,
        peak_move_pct=15.0,
    )
    candidate = SimpleNamespace(
        mode="explosion",
        tier="WATCH",
        explosion_event=event,
        alert={
            "side": "CALL",
            "ictFirstLift": True,
            "ictBreakout": True,
            "ictFlatThenVertical": True,
            "ictBaseRelativeMovePct": 15.0,
            "flatVerticalQuality": 61.0,
            "explosionScore": 51.0,
            "velocity3s": 1.35,
            "velocity9s": 1.35,
            "volumeSurge": 4.0,
            "ictVolumeAwakening": True,
        },
    )

    blocked, reason = chop_weak_explosion_blocks_entry(candidate, snap)

    assert blocked is False
    assert reason == "first_lift_local_base_confirmed"


@pytest.mark.parametrize(
    ("side", "option_key"),
    [
        (Side.CALL, "call_options"),
        (Side.PUT, "put_options"),
    ],
)
@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_soft_first_lift_reaches_radar_before_building_tier(_open, side, option_key):
    """A slow 15% lift must appear even while the raw detector still calls it WATCH."""
    settings = Settings()
    symbol, strike = "NIFTY", 24300.0
    key = _strike_key(strike, side)
    premiums = [
        91.0, 89.0, 90.5, 89.5, 92.0, 90.0, 91.5, 89.0,
        93.0, 95.0, 97.0, 99.0, 100.0, 101.0, 101.0, 101.0, 101.0, 101.0,
    ]
    # Keep the final seeded sample three seconds behind the live lift. A stale
    # multi-minute gap must not be interpreted as 3s explosion velocity.
    start = datetime.now(IST) - timedelta(seconds=(len(premiums) - 1) * 5 + 3)
    _history.setdefault(symbol, {})[key] = deque(
        (
            (start + timedelta(seconds=i * 5), premium, 1000.0)
            for i, premium in enumerate(premiums)
        ),
        maxlen=40,
    )
    chain = [{
        "strike_price": strike,
        option_key: {"ltp": 102.35, "volume": 1000},
    }]

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
    ):
        events = scan_chain_explosions(
            symbol, chain, spot=strike, atm=strike,
        )
        matching = [event for event in events if event.side == side]
        assert matching, "first lift was dropped before ICT/radar analysis"
        assert matching[0].tier == "WATCH"
        radar = event_to_dict(matching[0])

    assert radar["ictFirstLift"] is True
    assert radar["tradeable"] is True
    assert radar["momentType"] == "first_lift_local_base"
    assert 14.0 <= radar["ictBaseRelativeMovePct"] <= 16.5
    assert radar["flatVerticalQuality"] > 0
    assert radar["flatVerticalGrade"] in ("A+", "A", "B", "C")
