"""Post-09:45 open rip continuation — exec MTF premium fade should not choke ELITE first lifts."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.mtf_chart_analysis import TimeframeChartRead, validate_mtf_scalp
from app.engines.pad_lane_capture import post_open_setup_premium_fade_bypass
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
POST_OPEN = datetime(2026, 11, 2, 10, 5, tzinfo=IST)


def _settings(**overrides):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.execution_mtf_enabled = True
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.open_caution_premium_fade_max_drawdown_pct = -2.8
    s.pad_lane_premium_fade_fill_max_drawdown_pct = -1.2
    s.post_open_setup_premium_fade_fill_enabled = True
    s.open_caution_premium_fade_max_local_base_pct = 28.0
    s.shallow_otm_local_base_min_move_pct = 2.0
    s.open_caution_premium_fade_min_rank_score = 90.0
    s.open_caution_premium_fade_allow_grade_s = True
    s.open_caution_itm_band_enabled = False
    for key, val in overrides.items():
        setattr(s, key, val)
    return s


def _nifty_ce_alert() -> dict:
    return {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 23300.0,
        "tier": "ELITE",
        "ictFirstLift": True,
        "momentType": "ict_base_armed",
        "localBaseMovePct": 8.0,
        "causalRankScore": 92.0,
    }


@patch("app.engines.pad_lane_capture.get_settings")
def test_post_open_bypass_active_after_open_caution(mock_settings):
    mock_settings.return_value = _settings()
    assert post_open_setup_premium_fade_bypass(
        _nifty_ce_alert(),
        SimpleNamespace(tier="ELITE"),
        when=POST_OPEN,
    )


@patch("app.engines.pad_lane_capture.get_settings")
def test_post_open_bypass_idle_after_post_window(mock_settings):
    mock_settings.return_value = _settings()
    late = datetime(2026, 11, 2, 10, 45, tzinfo=IST)
    assert not post_open_setup_premium_fade_bypass(
        _nifty_ce_alert(), SimpleNamespace(tier="ELITE"), when=late,
    )


@patch("app.engines.mtf_chart_analysis.get_settings")
def test_mtf_uses_open_shallow_floor_when_post_open_bypass(mock_settings):
    mock_settings.return_value = _settings()
    index_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BULLISH", momentumPct=0.1, trendStrength=20),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=0.05, trendStrength=20),
        "15m": TimeframeChartRead(label="15m", direction="BULLISH", momentumPct=0.02, trendStrength=20),
        "1h": TimeframeChartRead(label="1h", direction="BULLISH", momentumPct=0.01, trendStrength=20),
        "4h": TimeframeChartRead(label="4h", direction="BULLISH", momentumPct=0.0, trendStrength=20),
    }
    premium_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BEARISH", momentumPct=-1.5, trendStrength=10),
        "5m": TimeframeChartRead(label="5m", direction="BEARISH", momentumPct=-2.0, trendStrength=10),
    }
    ok, reason, meta = validate_mtf_scalp(
        Side.CALL,
        index_mtf,
        premium_mtf,
        open_setup_fade_bypass=True,
    )
    assert ok, reason
    assert meta.get("openSetupFadeBypass") is True
