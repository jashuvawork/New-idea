"""Jul 17 NIFTY 24400 CE miss fixes — CALL vs bearish chart, faded rip hold, trail defer."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import cross_index_elite_priority_bonus
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import faded_rip_no_green_exit_reason
from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.explosion_profit import explosion_exit_params_from_plan
from app.engines.morning_premium_capture import (
    counter_trend_entry_allowed,
    premium_led_explosion_bypass,
)
from app.engines.rally_capture import chart_blocks_explosion_side
from app.engines.trade_selector import EntryCandidate
from app.engines.adaptive_exits import AdaptiveExitPlan
from app.models.schemas import (
    Breadth,
    PaperTrade,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _bearish_chart() -> SpotChart:
    return SpotChart(
        direction="BEARISH",
        trendStrength=35.0,
        momentum5Pct=-0.08,
        macdBias="BEARISH",
    )


def _bullish_chart() -> SpotChart:
    return SpotChart(
        direction="BULLISH",
        trendStrength=40.0,
        momentum5Pct=0.06,
        macdBias="BULLISH",
    )


def _call_rip_event(**kwargs) -> ExplosionEvent:
    base = dict(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400.0,
        premium=45.0,
        velocity_3s=3.2,
        velocity_9s=3.8,
        velocity_15s=2.5,
        volume_surge=4.0,
        explosion_score=88.0,
        tier="EXPLODING",
        reason="vertical_rip",
        daily_move_pct=22.0,
        peak_move_pct=32.0,
    )
    base.update(kwargs)
    return ExplosionEvent(**base)


def _snap(**kwargs) -> SymbolSnapshot:
    base = dict(
        symbol="NIFTY",
        timestamp="2026-07-17T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=24350.0,
        dataAvailable=True,
        spotChart=_bearish_chart(),
        breadth=Breadth(bias="NEUTRAL", score=50.0),
        tradeQualityScore=55.0,
        explosionAlerts=[],
    )
    base.update(kwargs)
    return SymbolSnapshot(**base)


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.config.get_settings")
def test_premium_led_bypass_call_vs_bearish_chart(mock_settings, _window):
    s = MagicMock()
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0
    s.premium_led_elite_counter_min_score = 90.0
    s.vertical_rip_bypass_enabled = True
    s.vertical_rip_bypass_min_peak_pct = 30.0
    s.vertical_rip_bypass_min_score = 38.0
    s.vertical_rip_bypass_min_peak_velocity_3s = 2.0
    s.vertical_rip_bypass_min_volume_surge = 3.0
    s.open_premium_min_move_pct = 25.0
    s.open_premium_bypass_min_score = 35.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.morning_capture_extreme_velocity_3s = 4.0
    s.morning_capture_extreme_velocity_9s = 5.0
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.5
    s.morning_capture_building_min_score = 38.0
    s.morning_capture_min_vol_surge = 2.0
    mock_settings.return_value = s

    event = _call_rip_event()
    assert premium_led_explosion_bypass(event, _bearish_chart(), "NEUTRAL") is True
    blocked, reason = chart_blocks_explosion_side(
        Side.CALL, _bearish_chart(), "EXPLODING", event=event, breadth_bias="NEUTRAL",
    )
    assert blocked is False, reason


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.config.get_settings")
def test_counter_trend_allows_exploding_call_rip(mock_settings, _window):
    s = MagicMock()
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0
    s.premium_led_elite_counter_min_score = 90.0
    s.vertical_rip_bypass_enabled = True
    s.vertical_rip_bypass_min_peak_pct = 30.0
    s.vertical_rip_bypass_min_score = 38.0
    s.vertical_rip_bypass_min_peak_velocity_3s = 2.0
    s.vertical_rip_bypass_min_volume_surge = 3.0
    mock_settings.return_value = s

    event = _call_rip_event()
    snap = _snap()
    assert counter_trend_entry_allowed(Side.CALL, snap, explosion_event=event) is True


def test_faded_rip_skips_no_green_on_bullish_flip():
    trade = PaperTrade(
        id="f1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400.0,
        entryPremium=63.62,
        currentPremium=62.0,
        lots=10,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=75),
        entryContext={
            "fadedRipCaution": True,
            "selectionMode": "explosion",
            "dailyMovePct": 65.0,
            "peakMovePct": 70.0,
            "executionChart": {"indexChart": {"direction": "BULLISH"}},
        },
    )
    reason = faded_rip_no_green_exit_reason(trade, hold_seconds=70, best_points=0.0)
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_high_conf_trail_stops_when_winner_gives_back_to_loss(mock_conf, mock_exp):
    """A high-chart-conf explosion that peaked +8.5pt then faded to a LOSS is stopped
    out by the armed trail — not held. High conviction/chart-confidence defers the
    profit *lock* (won't book a runner early) but an armed trail must not defer into a
    loss (recent 'hard-stop never-green / do-not-defer-into-loss' tightening)."""
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 48.2
    s.chart_confidence_hold_min_target_pct = 0.85
    s.chart_confidence_half_tp_lock_pct = 0.50
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    s.chart_confidence_elevated_threshold = 56.9
    s.chart_confidence_defer_tp_min = 60.6
    s.chart_confidence_runner_hold_min = 54.2
    s.high_confidence_min_score = 72.0
    s.all_day_min_chart_confidence = 48.2
    s.explosion_stop_min_hold_seconds = 15
    s.runner_min_best_points = 5.0
    s.runner_trail_keep_ratio = 0.38
    s.runner_micro_giveback_points = 4.0
    s.emergency_stop_enabled = False
    s.explosion_no_progress_enabled = True
    s.explosion_no_progress_skip_when_aligned = True
    s.explosion_no_progress_aligned_seconds = 420
    s.explosion_no_progress_seconds = 150
    s.explosion_target_standard = 18.0
    s.explosion_trail_arm_points = 4.0
    s.afternoon_capture_exit_max_hold_seconds = 600
    s.chart_confidence_hold_stop_mult = 1.35
    s.explosion_faded_rip_no_green_exit_enabled = True
    s.high_conviction_defer_profit_lock = True
    mock_conf.return_value = s
    mock_exp.return_value = s

    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24400.0,
        entryPremium=63.62,
        currentPremium=61.95,
        lots=10,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        bestPnlPoints=8.5,
        entryContext={
            # Display-scale high conviction (was 95 on old clamp; still clears defer_tp_min 60.6)
            "chartConfidence": 96.0,
            "breadth": "BULLISH",
            "selectionScore": 100.0,
            "exitPlan": {"targetPoints": 120.0, "stopPoints": 8.0, "chartConfidence": 96.0},
        },
    )
    plan = AdaptiveExitPlan(stopPoints=8.0, targetPoints=12.0, trailArmPoints=4.0, trailKeepRatio=0.65)
    params = explosion_exit_params_from_plan(plan, "ELITE")
    # Peaked +8.5pt, now -1.67pt (gave the whole winner back) → protective trail exit.
    reason, _ = evaluate_explosion_exit(trade, 61.95, "ELITE", 25, params=params)
    assert reason == "explosion_trail_sl"


def test_cross_index_elite_priority_bonus():
    settings = MagicMock()
    settings.cross_index_elite_priority_enabled = True
    settings.cross_index_elite_min_session_move_pct = 40.0
    settings.cross_index_elite_priority_bonus = 22.0

    nifty_snap = _snap(
        symbol="NIFTY",
        explosionAlerts=[
            {
                "side": "CALL",
                "tier": "ELITE",
                "explosionScore": 100.0,
                "dailyMovePct": 55.0,
                "peakMovePct": 65.0,
            }
        ],
    )
    sensex_snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-07-17T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=78500.0,
        dataAvailable=True,
        tradeQualityScore=50.0,
        explosionAlerts=[
            {
                "side": "CALL",
                "tier": "EXPLODING",
                "explosionScore": 70.0,
                "dailyMovePct": 15.0,
            }
        ],
    )
    event = _call_rip_event(tier="ELITE", explosion_score=100.0, daily_move_pct=55.0, peak_move_pct=65.0)
    cand = EntryCandidate(
        symbol="NIFTY",
        snap=nifty_snap,
        mode="explosion",
        score=100.0,
        side=Side.CALL,
        strike=24400.0,
        premium=65.0,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=100.0,
        tqs=55.0,
        tier="ELITE",
        explosion_event=event,
    )
    with patch("app.engines.bad_day_routing.get_settings", return_value=settings):
        bonus = cross_index_elite_priority_bonus(cand, {"NIFTY": nifty_snap, "SENSEX": sensex_snap})
    assert bonus >= 22.0
