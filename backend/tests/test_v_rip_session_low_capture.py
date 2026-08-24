"""V-rip session-low capture — do not miss sparse-poll lifts off the trough."""

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_detector import (
    _local_base_hist,
    _open_key,
    _session_low,
    _session_peak,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import (
    analyze_ict_breakout,
    first_lift_entry_readiness,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(side: Side = Side.PUT) -> SymbolSnapshot:
    adverse = 0.08 if side == Side.PUT else -0.08
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=76900.0,
        atmStrike=76900.0,
        breadth=Breadth(
            bias="BEARISH" if side == Side.PUT else "BULLISH",
            score=70.0,
            aligned=True,
        ),
        spotChart=SpotChart(
            direction="BEARISH" if side == Side.PUT else "BULLISH",
            momentum5Pct=adverse,
            momentum10Pct=adverse * 0.5,
            momentum15Pct=adverse * 0.2,
        ),
    )


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_v_rip_ready_when_sparse_poll_skips_elite_2_to_5_window(mock_settings):
    """125 → 140 (~12%) must still authorize — elite 2–5% alone would miss."""
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings()
    side = Side.PUT
    key = _open_key("SENSEX", 76900.0, side)
    now = datetime(2026, 8, 19, 10, 20, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(8 - i) * 3), 125.0 + (i % 2) * 0.2) for i in range(9)],
        maxlen=1200,
    )
    _session_low[key] = 125.0
    _session_peak[key] = 140.0

    ict = analyze_ict_breakout(
        symbol="SENSEX",
        strike=76900.0,
        side=side,
        premium=140.0,
        session_move_pct=12.0,
        peak_move_pct=12.0,
        velocity_3s=1.8,
        velocity_9s=1.2,
        volume=2_000_000,
        volume_surge=2.5,
        tier="BUILDING",
        reason="volAwaken",
    )
    assert ict.base_premium == 125.0
    assert 10.0 <= ict.base_relative_move_pct <= 15.0
    assert ict.elite_base_ready is False  # outside 2–5%
    assert ict.v_rip_ready is True
    assert any(
        isinstance(r, str) and r.startswith("v_rip_session_low_")
        for r in ict.reasons
    )


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_v_rip_entry_readiness_admits_building(mock_settings):
    reset_detector_state_for_tests()
    settings = Settings()
    mock_settings.return_value = settings
    side = Side.PUT
    key = _open_key("SENSEX", 76900.0, side)
    now = datetime(2026, 8, 19, 10, 20, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(8 - i) * 3), 125.0 + (i % 2) * 0.2) for i in range(9)],
        maxlen=1200,
    )
    _session_low[key] = 125.0
    _session_peak[key] = 140.0

    ict = analyze_ict_breakout(
        symbol="SENSEX",
        strike=76900.0,
        side=side,
        premium=140.0,
        session_move_pct=12.0,
        peak_move_pct=12.0,
        velocity_3s=1.8,
        velocity_9s=1.2,
        volume=2_000_000,
        volume_surge=2.5,
        tier="BUILDING",
        reason="volAwaken",
    )
    # Force quality into the soft V-rip band for readiness.
    ict.flat_vertical_quality = 55.0
    alert = {
        "side": "PUT",
        "strike": 76900.0,
        "tier": "BUILDING",
        "explosionScore": 48.0,
        "velocity3s": 1.8,
        "velocity9s": 1.2,
        "volumeSurge": 2.5,
        "volume": 2_000_000,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "ictVRipReady": True,
        "ictEliteBaseReady": False,
        "ictArmedBaseLaunch": False,
        "ictFirstLift": False,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": ict.base_relative_move_pct,
        "ictBasePremium": ict.base_premium,
        "ictBaseArmed": ict.base_armed,
        "ictArmedBaseSamples": ict.armed_base_samples,
        "ictArmedBaseSpanSeconds": ict.armed_base_span_seconds,
        "flatVerticalQuality": 55.0,
    }
    ready, reason = first_lift_entry_readiness(
        snap=_snap(side),
        ict=ict,
        alert=alert,
    )
    assert ready is True
    assert reason == "v_rip_session_low_ready"


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_v_rip_not_ready_on_mid_rip_coil(mock_settings):
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings()
    side = Side.PUT
    key = _open_key("SENSEX", 76900.0, side)
    now = datetime(2026, 8, 19, 12, 45, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(8 - i) * 3), 161.5 + (i % 2) * 0.3) for i in range(9)],
        maxlen=1200,
    )
    _session_low[key] = 125.0
    _session_peak[key] = 220.0

    ict = analyze_ict_breakout(
        symbol="SENSEX",
        strike=76900.0,
        side=side,
        premium=168.15,
        session_move_pct=34.5,
        peak_move_pct=34.5,
        velocity_3s=2.0,
        velocity_9s=1.5,
        volume=2_000_000,
        volume_surge=2.5,
        tier="EXPLODING",
        reason="volAwaken",
    )
    assert ict.v_rip_ready is False
    assert ict.elite_base_ready is False


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_v_rip_lane_prefers_softer_path_over_armed_launch(mock_settings):
    """Armed stamp + low TQS must not block when V-rip pad is active (Aug24 24→30)."""
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings()
    side = Side.PUT
    key = _open_key("NIFTY", 24200.0, side)
    now = datetime(2026, 8, 24, 10, 3, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(8 - i) * 3), 24.45 + (i % 2) * 0.1) for i in range(9)],
        maxlen=1200,
    )
    _session_low[key] = 24.45
    _session_peak[key] = 30.0

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=now,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=48.0,
        spot=24200.0,
        atmStrike=24200.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.08,
            momentum10Pct=-0.05,
            momentum15Pct=-0.02,
        ),
    )
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        strike=24200.0,
        side=side,
        premium=30.0,
        session_move_pct=22.7,
        peak_move_pct=22.7,
        velocity_3s=1.3,
        velocity_9s=1.0,
        volume=80_000,
        volume_surge=2.2,
        tier="EXPLODING",
        reason="volAwaken",
    )
    alert = {
        "side": "PUT",
        "strike": 24200.0,
        "premium": 30.0,
        "explosionScore": 90.1,
        "tier": "EXPLODING",
        "velocity3s": 1.3,
        "velocity9s": 1.0,
        "volumeSurge": 2.2,
        "volume": 80_000,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "ictVRipReady": True,
        "ictArmedBaseLaunch": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": ict.base_relative_move_pct,
        "flatVerticalQuality": 55.0,
    }
    ready, reason = first_lift_entry_readiness(snap=snap, ict=ict, alert=alert)
    assert ready is True
    assert reason == "v_rip_session_low_ready"


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_v_rip_slow_grind_at_30_with_volume_awake(mock_settings):
    """24→30 grind with v3=0.9 passes when volume awakening confirms the pad."""
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings()
    side = Side.PUT
    key = _open_key("NIFTY", 24200.0, side)
    now = datetime(2026, 8, 24, 10, 4, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(8 - i) * 3), 24.45 + (i % 2) * 0.1) for i in range(9)],
        maxlen=1200,
    )
    _session_low[key] = 24.45
    _session_peak[key] = 30.0

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=now,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=58.0,
        spot=24200.0,
        atmStrike=24200.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.08,
            momentum10Pct=-0.05,
            momentum15Pct=-0.02,
        ),
    )
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        strike=24200.0,
        side=side,
        premium=30.0,
        session_move_pct=22.7,
        peak_move_pct=22.7,
        velocity_3s=0.9,
        velocity_9s=0.85,
        volume=80_000,
        volume_surge=2.2,
        tier="EXPLODING",
        reason="volAwaken",
    )
    alert = {
        "side": "PUT",
        "strike": 24200.0,
        "premium": 30.0,
        "explosionScore": 90.1,
        "tier": "EXPLODING",
        "velocity3s": 0.9,
        "velocity9s": 0.85,
        "volumeSurge": 2.2,
        "volume": 80_000,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "ictVRipReady": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": ict.base_relative_move_pct,
        "flatVerticalQuality": 55.0,
    }
    ready, reason = first_lift_entry_readiness(snap=snap, ict=ict, alert=alert)
    assert ready is True
    assert reason == "v_rip_session_low_ready"


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_aug24_v_rip_early_pad_volume_awake_skips_velocity(mock_settings):
    """Aug24 NIFTY PUT 24250 — ~7% local-base pad, v3<1.2, volume awakening (mfe 86%)."""
    reset_detector_state_for_tests()
    mock_settings.return_value = Settings()
    side = Side.PUT
    key = _open_key("NIFTY", 24250.0, side)
    now = datetime(2026, 8, 24, 11, 5, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(now - timedelta(seconds=(8 - i) * 3), 47.95 + (i % 2) * 0.15) for i in range(9)],
        maxlen=1200,
    )
    _session_low[key] = 47.95
    _session_peak[key] = 52.0

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=now,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=56.0,
        spot=24250.0,
        atmStrike=24250.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.08,
            momentum10Pct=-0.05,
            momentum15Pct=-0.02,
        ),
    )
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        strike=24250.0,
        side=side,
        premium=51.5,
        session_move_pct=7.4,
        peak_move_pct=7.4,
        velocity_3s=0.65,
        velocity_9s=0.55,
        volume=120_000,
        volume_surge=2.1,
        tier="BUILDING",
        reason="volAwaken",
    )
    alert = {
        "side": "PUT",
        "strike": 24250.0,
        "premium": 51.5,
        "explosionScore": 55.6,
        "tier": "BUILDING",
        "velocity3s": 0.65,
        "velocity9s": 0.55,
        "volumeSurge": 2.1,
        "volume": 120_000,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "ictVRipReady": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 7.3,
        "localBaseMovePct": 7.3,
        "flatVerticalQuality": 52.0,
    }
    ready, reason = first_lift_entry_readiness(snap=snap, ict=ict, alert=alert)
    assert ready is True
    assert reason == "v_rip_session_low_ready"
