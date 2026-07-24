"""Hard breadth side alignment — no PUT on BULLISH / CALL on BEARISH."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.aligned_side_guard import (
    breadth_hard_blocks_side,
    chart_mtf_breadth_bypass_active,
    chart_mtf_bullish_confirmed,
    counter_breadth_side_blocked,
)
from app.models.schemas import ChartAnalysis
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.engines.morning_premium_capture import (
    counter_trend_entry_allowed,
    premium_led_explosion_bypass,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _elite_put_event() -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77100.0,
        premium=120.0,
        velocity_3s=5.0,
        velocity_9s=7.0,
        velocity_15s=10.0,
        volume_surge=2.5,
        explosion_score=95.0,
        tier="ELITE",
        reason="+5%/3s",
        daily_move_pct=45.0,
    )


def _bullish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77200.0,
        spotChart=SpotChart(
            direction="BULLISH",
            spot=77200.0,
            momentum5Pct=0.12,
            trendStrength=40.0,
            emaBias="BULLISH",
            macdBias="BULLISH",
        ),
        breadth=Breadth(score=68, bias="BULLISH", aligned=True),
    )


def _trade() -> SuggestedTrade:
    return SuggestedTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77100.0,
        lastPremium=120.0,
        tqs=55,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=95,
    )


def test_hard_block_put_on_bullish_breadth():
    blocked, reason = breadth_hard_blocks_side(Side.PUT, "BULLISH")
    assert blocked is True
    assert reason == "hard_block_put_vs_bullish_breadth"
    assert counter_breadth_side_blocked(Side.CALL, "BULLISH") is False


def test_hard_block_call_on_bearish_breadth():
    blocked, reason = breadth_hard_blocks_side(Side.CALL, "BEARISH")
    assert blocked is True
    assert reason == "hard_block_call_vs_bearish_breadth"


def test_neutral_breadth_allows_both_sides():
    assert breadth_hard_blocks_side(Side.PUT, "NEUTRAL") == (False, "ok")
    assert breadth_hard_blocks_side(Side.CALL, "NEUTRAL") == (False, "ok")


def _bullish_chart_mtf_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24200.0,
        spotChart=SpotChart(
            direction="BULLISH",
            spot=24200.0,
            momentum5Pct=0.08,
            trendStrength=45.0,
            rsi=65.0,
            macdBias="BULLISH",
        ),
        breadth=Breadth(score=52, bias="BEARISH", aligned=True),
        chartAnalysis=ChartAnalysis(
            consensus="BULLISH",
            alignedCount=4,
            totalTimeframes=4,
            ichimoku={"cloudBias": "BULLISH", "priceVsCloud": "ABOVE"},
        ),
    )


@patch("app.engines.aligned_side_guard.get_settings")
def test_chart_mtf_bypass_allows_call_on_bearish_breadth(mock_settings):
    s = mock_settings.return_value
    s.breadth_hard_side_block_enabled = True
    s.chart_mtf_breadth_bypass_enabled = True
    s.chart_mtf_breadth_bypass_min_explosion_score = 42.0
    s.chart_mtf_breadth_bypass_min_aligned = 3
    s.chart_mtf_breadth_bypass_min_rsi = 52.0

    snap = _bullish_chart_mtf_snap()
    assert chart_mtf_bullish_confirmed(snap) is True
    bypassed, reason = chart_mtf_breadth_bypass_active(Side.CALL, "BEARISH", snap, score=45.0)
    assert bypassed is True
    assert "bullish" in reason

    blocked, block_reason = breadth_hard_blocks_side(
        Side.CALL,
        "BEARISH",
        snap=snap,
        event=ExplosionEvent(
            symbol="NIFTY",
            side=Side.CALL,
            strike=24350.0,
            premium=30.0,
            velocity_3s=3.0,
            velocity_9s=4.0,
            velocity_15s=5.0,
            volume_surge=2.0,
            explosion_score=45.0,
            tier="ELITE",
            reason="test",
        ),
    )
    assert blocked is False


@patch("app.engines.aligned_side_guard.get_settings")
def test_chart_mtf_bypass_requires_min_score(mock_settings):
    s = mock_settings.return_value
    s.breadth_hard_side_block_enabled = True
    s.chart_mtf_breadth_bypass_enabled = True
    s.chart_mtf_breadth_bypass_min_explosion_score = 45.0
    s.chart_mtf_breadth_bypass_min_aligned = 3
    s.chart_mtf_breadth_bypass_min_rsi = 52.0

    snap = _bullish_chart_mtf_snap()
    blocked, reason = breadth_hard_blocks_side(Side.CALL, "BEARISH", snap=snap, alert={"explosionScore": 40})
    assert blocked is True
    assert reason == "hard_block_call_vs_bearish_breadth"


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_elite_put_blocked_on_bullish_breadth(mock_settings, _window):
    s = mock_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.premium_led_elite_counter_min_score = 90.0
    s.breadth_hard_side_block_enabled = True

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77100.0,
        premium=120.0,
        velocity_3s=5.0,
        velocity_9s=7.0,
        velocity_15s=10.0,
        volume_surge=2.5,
        explosion_score=82.0,
        tier="ELITE",
        reason="+5%/3s",
        daily_move_pct=18.0,
        peak_move_pct=18.0,
    )
    chart = _bullish_snap().spotChart
    assert premium_led_explosion_bypass(event, chart, "BULLISH") is False
    assert counter_trend_entry_allowed(Side.PUT, _bullish_snap(), explosion_event=event) is False


@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=False)
@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.aligned_side_guard.get_settings")
@patch("app.engines.local_base_chart_bypass.get_settings")
def test_explosion_entry_blocks_elite_put_on_rally(
    mock_lb, mock_ag, mock_explosion_settings, mock_morning_settings, _window, _morning_win,
):
    s = mock_morning_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.breadth_hard_side_block_enabled = True
    s.explosion_breadth_alignment_enabled = True
    s.aggressive_min_explosion_score = 45
    s.local_base_overrides_session_chart_enabled = True
    s.local_base_overrides_bearish_breadth = True
    s.local_base_chart_bypass_require_ichimoku = False
    s.local_base_chart_bypass_min_score = 38.0
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.local_base_chart_bypass_radar_min_move_pct = 28.0
    s.local_base_ichimoku_max_adverse_mom5_pct = 0.12
    s.explosion_live_confirm_enabled = False
    s.chart_mtf_breadth_bypass_min_score = 999.0
    s.extreme_explosion_all_in_enabled = False
    mock_explosion_settings.return_value = s
    mock_ag.return_value = s
    mock_lb.return_value = s

    snap = _bullish_snap()
    with patch(
        "app.engines.aligned_side_guard.chart_mtf_breadth_bypass_active",
        return_value=(False, {}),
    ), patch(
        "app.engines.extreme_explosion_moment.is_extreme_explosion_all_in_bypass",
        return_value=False,
    ), patch(
        "app.engines.vertical_rip_bypass.vertical_rip_bypasses_hard_breadth",
        return_value=False,
    ), patch(
        "app.engines.local_base_chart_bypass.local_base_structure_active",
        return_value=False,
    ):
        ok, reason = check_explosion_entry(
            _elite_put_event(),
            _trade(),
            snap.breadth,
            False,
            chart=snap.spotChart,
            snap=snap,
        )
    assert ok is False
    assert reason == "hard_block_put_vs_bullish_breadth"
