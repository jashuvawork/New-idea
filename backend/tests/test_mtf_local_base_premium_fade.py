"""MTF premium fade must honor local-base first-lift shallow floor."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.mtf_chart_analysis import validate_mtf_scalp
from app.models.schemas import Side, TimeframeChartRead


def _settings(**overrides):
    s = MagicMock()
    s.execution_mtf_enabled = True
    s.execution_chart_premium_check_enabled = True
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.execution_mtf_min_align = 1
    s.execution_mtf_block_htf_conflict = False
    s.chart_override_min_score = 999.0
    s.local_base_first_lift_waives_mtf_premium_fade_enabled = True
    s.local_base_first_lift_premium_fade_max_drawdown_pct = -2.8
    s.pad_lane_premium_fade_fill_max_drawdown_pct = -2.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.mtf_chart_analysis.get_settings")
def test_mtf_premium_fade_relaxed_with_local_base_bypass(mock_settings):
    mock_settings.return_value = _settings()
    index_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BULLISH", momentumPct=0.1, trendStrength=40),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=0.1, trendStrength=40),
    }
    premium_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BEARISH", momentumPct=-1.0, trendStrength=20),
        "5m": TimeframeChartRead(label="5m", direction="BEARISH", momentumPct=-0.8, trendStrength=20),
    }
    ok, reason, meta = validate_mtf_scalp(
        Side.CALL,
        index_mtf,
        premium_mtf,
        premium_led_bypass=True,
        local_base_first_lift_bypass=True,
    )
    assert ok is True
    assert reason == "ok"
    assert meta.get("localBaseFirstLiftBypass") is True


@patch("app.engines.mtf_chart_analysis.get_settings")
def test_mtf_premium_fade_still_blocks_deep_collapse(mock_settings):
    mock_settings.return_value = _settings()
    index_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BULLISH", momentumPct=0.1, trendStrength=40),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=0.1, trendStrength=40),
    }
    premium_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BEARISH", momentumPct=-3.5, trendStrength=20),
    }
    ok, reason, _meta = validate_mtf_scalp(
        Side.CALL,
        index_mtf,
        premium_mtf,
        local_base_first_lift_bypass=True,
    )
    assert ok is False
    assert reason == "exec_mtf_premium_1m_fading"
