"""Aug26 SENSEX PUT v_rip_session_low — strict pad-lane chart bypass must reach live gates."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.pad_lane_capture import resolve_strict_pad_lane_chart_bypass
from app.engines.spot_direction import chart_blocks_side, live_direction_blocks_side
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.pad_lane_chart_bypass_enabled = True
    s.pad_lane_first_lift_local_base_chart_bypass_enabled = True
    s.pad_lane_armed_base_launch_chart_bypass_enabled = True
    s.pad_lane_chart_bypass_min_velocity_3s = 0.5
    s.pad_lane_chart_bypass_volume_awaken_min_velocity_3s = 0.2
    s.pad_lane_chart_bypass_max_off_low_pct = 30.0
    s.pad_lane_chart_bypass_max_peak_move_pct = 38.0
    s.pad_lane_elite_ftv_chart_bypass_max_peak_move_pct = 45.0
    s.pad_lane_chart_bypass_max_adverse_index_mom5_pct = 0.25
    s.pad_lane_chart_bypass_min_premium_velocity_9s = -0.3
    s.ict_v_rip_pad_min_move_pct = 2.0
    s.ict_v_rip_max_move_pct = 25.0
    s.chart_alignment_enabled = True
    s.chart_live_direction_hard_block = True
    s.chart_counter_trend_bypass_block_enabled = True
    s.chart_min_trend_strength = 20
    s.chart_min_momentum_pct = 0.05
    s.chart_override_min_score = 75
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _bullish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 26, 13, 15, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
        spot=77700.0,
        atmStrike=77700.0,
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.08,
            momentum10Pct=0.07,
            momentum15Pct=0.06,
            trendStrength=35,
            spot=77700.0,
        ),
    )


def _aug26_put_77600_alert(**overrides) -> dict:
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77600.0,
        "premium": 144.6,
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "explosionScore": 100.0,
        "ictFirstLift": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "localBaseMovePct": 23.6,
        "ictBaseRelativeMovePct": 23.6,
        "offLowMovePct": 23.6,
        "peakMovePct": 32.79,
        "velocity3s": -0.03,
        "velocity9s": 0.1,
        "volumeAwaken": True,
        "ictBaseReadinessReason": "v_rip_session_low_ready",
    }
    alert.update(overrides)
    return alert


class _Candidate:
    def __init__(self, alert: dict):
        self.mode = "explosion"
        self.side = Side.PUT
        self.alert = alert
        self.explosion_event = None


@patch("app.engines.pad_lane_capture.get_settings")
def test_resolve_strict_pad_lane_bypass_for_v_rip_session_low(mock_settings):
    mock_settings.return_value = _settings()
    snap = _bullish_snap()
    candidate = _Candidate(_aug26_put_77600_alert())

    pad_lane, strict = resolve_strict_pad_lane_chart_bypass(candidate, snap)

    assert pad_lane is True
    assert strict is True


@patch("app.engines.spot_direction.get_settings")
@patch("app.engines.pad_lane_capture.get_settings")
def test_strict_bypass_clears_chart_live_bullish_no_puts(mock_pad, mock_spot):
    settings = _settings()
    mock_pad.return_value = settings
    mock_spot.return_value = settings
    chart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.08,
        trendStrength=35,
        spot=77700.0,
    )

    blocked, reason = live_direction_blocks_side(
        Side.PUT,
        chart,
        strict_first_lift_bypass=True,
    )
    assert blocked is False
    assert reason == "ok"

    blocked, reason = chart_blocks_side(
        Side.PUT,
        chart,
        strict_first_lift_bypass=True,
        premium_led_bypass=True,
    )
    assert blocked is False
    assert reason == "ok"
