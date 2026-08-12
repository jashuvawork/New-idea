"""Aug12 SENSEX 77800 PE — seed session low/peak from chain day OHLC.

Sparse LTP polls missed the ~120 trough and ~238 peak; radar stamped base ~190
with only ~11% move and stuck BUILDING/not_tradeable while the chart printed a
classic V-bottom flat→vertical.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import (
    ExplosionEvent,
    _open_key,
    _session_low,
    _session_open,
    _session_peak,
    _session_open_move_pct,
    _session_peak_move_pct,
    apply_day_extremes_baseline,
    day_extremes_from_option_leg,
    event_to_dict,
    reset_detector_state_for_tests,
    session_low_relative_move_pct,
)
from app.models.schemas import Side
from app.services.upstox import normalize_option_leg


def test_normalize_option_leg_preserves_day_high_low():
    leg = normalize_option_leg({
        "instrument_key": "BSE_FO|1",
        "market_data": {
            "ltp": 198.55,
            "volume": 1500000,
            "oi": 100,
            "ohlc": {"open": 135.0, "high": 238.0, "low": 120.0, "close": 134.85},
        },
        "option_greeks": {"iv": 12.0},
    })
    assert float(leg["day_low"]) == 120.0
    assert float(leg["day_high"]) == 238.0
    assert float(leg["ohlc"]["low"]) == 120.0
    assert float(leg["ohlc"]["high"]) == 238.0


def test_day_extremes_from_option_leg():
    low, high = day_extremes_from_option_leg({
        "ltp": 200.0,
        "day_low": 120.0,
        "day_high": 238.0,
    })
    assert low == 120.0
    assert high == 238.0


def test_apply_day_extremes_deepens_low_and_peak():
    reset_detector_state_for_tests()
    key = _open_key("SENSEX", 77800.0, Side.PUT)
    # Mid-rip first poll — wrong open/low around 190.
    _session_open[key] = 190.0
    _session_low[key] = 190.0
    _session_peak[key] = 200.0
    changed = apply_day_extremes_baseline(key, 198.55, day_low=120.0, day_high=238.0)
    assert changed
    assert _session_low[key] == 120.0
    assert _session_peak[key] == 238.0
    assert _session_open[key] == 120.0  # backfilled after ≥8% dump


def test_session_move_sees_vbottom_from_day_ohlc():
    """First LTP at ~199 after a missed trough — day OHLC still yields real move."""
    reset_detector_state_for_tests()
    open_move = _session_open_move_pct(
        "SENSEX", 77800.0, Side.PUT, 198.55,
        prior_close=134.85,
        day_low=120.0,
        day_high=238.0,
    )
    peak_move = _session_peak_move_pct(
        "SENSEX", 77800.0, Side.PUT, 198.55,
        prior_close=134.85,
        day_low=120.0,
        day_high=238.0,
    )
    # Off the true trough (~120), live ~199 is ~65%+; peak 238 is ~98%+.
    assert open_move >= 55.0, open_move
    assert peak_move >= 90.0, peak_move
    off = session_low_relative_move_pct("SENSEX", 77800.0, Side.PUT, 198.55)
    assert off >= 55.0, off


def test_building_volume_awaken_tradeable_in_pad():
    reset_detector_state_for_tests()
    ict = SimpleNamespace(
        active=False,
        pattern="watch",
        score=10.0,
        reasons=["volume_awakening"],
        premium_fvg=False,
        flat_then_vertical=False,
        displacement=False,
        volume_awakening=True,
        mega_rip=False,
        session_move_pct=22.0,
        base_relative_move_pct=22.0,
        base_premium=120.0,
        local_swing_base=True,
    )
    with patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
        return_value=ict,
    ), patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=22.0,
    ), patch(
        "app.engines.morning_premium_capture.is_morning_capture_event",
        return_value=False,
    ), patch(
        "app.engines.morning_premium_capture.is_afternoon_capture_event",
        return_value=False,
    ), patch(
        "app.engines.morning_premium_capture.is_all_day_explosion_event",
        return_value=False,
    ), patch(
        "app.engines.morning_premium_capture.is_premium_capture_event",
        return_value=False,
    ):
        key = _open_key("SENSEX", 77800.0, Side.PUT)
        _session_low[key] = 120.0
        event = ExplosionEvent(
            symbol="SENSEX",
            side=Side.PUT,
            strike=77800.0,
            premium=146.0,
            velocity_3s=1.5,
            velocity_9s=2.0,
            velocity_15s=1.0,
            volume_surge=2.5,
            explosion_score=85.0,
            tier="BUILDING",
            reason="peakV3=3.3% vol×2.5 volAwaken×27k",
            daily_move_pct=22.0,
            peak_move_pct=22.0,
            volume=27264000,
        )
        alert = event_to_dict(event, snap=None)
        assert alert["volumeAwaken"] is True
        assert alert["tradeable"] is True
