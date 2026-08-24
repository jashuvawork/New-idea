"""WS volume=0 must not wipe REST volume history or drop ICT volume_awakening."""

from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import (
    ExplosionEvent,
    _history,
    _last_known_volume,
    _record,
    _strike_key,
    _volume_surge,
    _volume_surge_with_chain,
    event_to_dict,
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.config import Settings
from app.engines.ict_breakout_monitor import analyze_explosion_event_ict
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def setup_function(_):
    reset_detector_state_for_tests()


def test_record_carries_forward_volume_when_ws_passes_zero():
    _record("NIFTY", 23900.0, Side.PUT, 100.0, 50_000)
    _record("NIFTY", 23900.0, Side.PUT, 110.0, 0)  # WS rescan
    key = _strike_key(23900.0, Side.PUT)
    hist = _history["NIFTY"][key]
    assert hist[-1][2] == 50_000
    assert _last_known_volume(hist) == 50_000


def test_ws_zeros_do_not_collapse_volume_surge():
    # Build rising volume history, then WS zeros — without carry-forward recent_vol→0
    # and surge collapses to 0; with carry-forward last volume stays and surge > 0.
    for i, vol in enumerate([10_000, 12_000, 15_000, 40_000, 55_000]):
        _record("SENSEX", 76300.0, Side.PUT, 30.0 + i, vol)
    for i in range(3):
        _record("SENSEX", 76300.0, Side.PUT, 40.0 + i, 0)
    hist = _history["SENSEX"][_strike_key(76300.0, Side.PUT)]
    assert hist[-1][2] == 55_000
    after = _volume_surge(hist)
    assert after > 0.5  # not collapsed to 0 by zero pollution


def test_high_cumulative_volume_without_price_heat_is_not_synthetic_surge():
    now = datetime.now(IST)
    hist = deque(
        [
            (now - timedelta(seconds=12), 100.0, 50_000.0),
            (now - timedelta(seconds=9), 100.0, 50_000.0),
            (now - timedelta(seconds=6), 100.0, 50_000.0),
            (now - timedelta(seconds=3), 100.0, 50_000.0),
            (now, 100.0, 50_000.0),
        ]
    )
    settings = MagicMock()
    settings.explosion_volume_awaken_min = 25_000
    settings.explosion_volume_awaken_min_velocity_3s = 1.0

    assert _volume_surge_with_chain(50_000, hist, settings) < 2.0


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_ws_price_launch_reuses_rest_volume_for_detector_and_ict(_open):
    """Aug17 REST/WS split: fresh WS acceleration keeps authoritative REST volume."""
    from app.engines import explosion_detector

    settings = Settings()
    current = datetime.now(IST)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

    def scan(premium: float, volume: float):
        return scan_chain_explosions(
            "NIFTY",
            [{
                "strike_price": 24300.0,
                "call_options": {"ltp": premium, "volume": volume},
            }],
            spot=24285.0,
            atm=24300.0,
        )

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", _Clock),
    ):
        for premium in (51.8, 51.6, 51.9, 51.7, 51.8, 51.6, 51.9, 51.7):
            scan(premium, 27_127_300)
            current += timedelta(seconds=3)
        events = []
        for premium in (54.0, 55.5, 57.0, 58.7, 59.8):
            events = scan(premium, 0)
            current += timedelta(seconds=3)

        target = next(
            event for event in events
            if event.side == Side.CALL and event.strike == 24300.0
        )
        radar = event_to_dict(target)

    assert target.volume == 27_127_300
    assert target.volume_surge >= 2.0
    assert radar["ictVolumeAwakening"] is True
    assert radar["ictFirstLift"] is True
    assert radar["velocity3s"] >= 1.5
    assert radar["velocity9s"] >= 1.5


def _ict_settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.explosion_volume_awaken_min = 25_000
    s.ict_volume_surge_awaken_min = 2.0
    s.ict_displacement_min_velocity_3s = 2.0
    s.ict_vertical_min_session_move_pct = 40.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_mega_rip_min_session_move_pct = 80.0
    s.ict_breakout_min_score = 20.0
    s.ict_fvg_score_bonus = 12.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 20.0
    s.explosion_immature_min_session_move_pct = 22.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ict_sees_volume_from_event_field(mock_s):
    mock_s.return_value = _ict_settings()

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        premium=40.0,
        velocity_3s=8.0,
        velocity_9s=10.0,
        velocity_15s=9.0,
        volume_surge=1.2,
        explosion_score=70.0,
        tier="ELITE",
        reason="momentum",
        daily_move_pct=33.0,
        peak_move_pct=33.0,
        volume=50_000,
    )
    ict = analyze_explosion_event_ict(event, snap=None)
    assert ict.volume_awakening is True
    assert any("volume" in r for r in ict.reasons)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ict_surge_awaken_at_2x_matches_detector_boost(mock_s):
    mock_s.return_value = _ict_settings()

    event = SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23900.0,
        premium=150.0,
        velocity_3s=3.0,
        velocity_9s=4.0,
        volume_surge=2.0,  # detector volAwaken boost level
        daily_move_pct=32.0,
        peak_move_pct=32.0,
        tier="ELITE",
        reason="+3.0%/3s",
        volume=0,
    )
    ict = analyze_explosion_event_ict(event, snap=None)
    assert ict.volume_awakening is True
