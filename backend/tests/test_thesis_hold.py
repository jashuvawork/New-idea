"""Green structured thesis: no time-stop — trail/SL own the exit."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import (
    ExplosionExitParams,
    _structured_green_thesis_hold_seconds,
    evaluate_explosion_exit,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    defaults = {
        "explosion_thesis_hold_enabled": True,
        "explosion_thesis_hold_skip_time_exit": True,
        "explosion_thesis_hold_min_best_points": 2.0,
        "explosion_thesis_hold_max_seconds": 10800,
        "explosion_elite_max_hold_seconds": 1800,
        "ict_max_profit_max_hold_seconds": 1200,
        "afternoon_capture_exit_max_hold_seconds": 480,
        "explosion_target_standard": 12.0,
        "explosion_trail_arm_points": 4.0,
        "explosion_trail_keep_ratio": 0.65,
        "explosion_trail_step_points": 3.5,
        "explosion_trail_tight_arm": 999.0,
        "explosion_trail_tight_points": 0.0,
        "runner_min_best_points": 5.0,
        "runner_trail_keep_ratio": 0.55,
        "runner_micro_giveback_points": 4.0,
        "explosion_stop_min_hold_seconds": 0,
        "emergency_stop_enabled": False,
        "explosion_no_progress_enabled": False,
        "explosion_peak_fade_lock_enabled": False,
        "explosion_peak_capture_enabled": False,
        "explosion_faded_rip_no_green_exit_enabled": False,
        "explosion_skip_time_profit_enabled": True,
        "explosion_skip_time_profit_tiers_csv": "ELITE,EXPLODING",
        "explosion_skip_time_profit_until_target_frac": 0.85,
        "high_conviction_defer_profit_lock": True,
        "high_conviction_trail_keep_ratio": 0.30,
        "ict_max_profit_skip_hard_target": True,
        "ict_max_profit_target_points": 180.0,
        "ict_mega_rip_trail_arm_multiplier": 1.0,
        "ict_breakout_trail_arm_multiplier": 1.0,
        "chart_confidence_defer_tp_min": 90.0,
        "chart_confidence_half_tp_giveback_ratio": 0.40,
        "moment_stage_trail_enabled": False,
        "bullish_hold_enabled": False,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _trade(
    *,
    best: float,
    current: float,
    hold_s: int,
    never_green_style: bool = False,
) -> PaperTrade:
    entry = 71.02
    ctx = {
        "selectionMode": "explosion",
        "explosionTier": "ELITE",
        "explosionScore": 100.0,
        "highConviction": True,
        "ictFlatThenVertical": not never_green_style,
        "ictMegaRip": not never_green_style,
        "ictPattern": "watch" if never_green_style else "mega_rip",
        "velocity3s": 0.8,
        "breadth": {"bias": "BEARISH", "aligned": True},
        "indexChart": {"direction": "BEARISH"},
        "exitPlan": {
            "stopPoints": 15.84,
            "targetPoints": 46.16,
            "trailArmPoints": 18.27,
            "trailKeepRatio": 0.59,
            "microTargetPoints": 3.0,
        },
    }
    if never_green_style:
        ctx["highConviction"] = False
        ctx["ictFlatThenVertical"] = False
        ctx["ictMegaRip"] = False
    return PaperTrade(
        id="ba7d90b6",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24550.0,
        entryPremium=entry,
        currentPremium=current,
        lots=41,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=hold_s),
        bestPnlPoints=best,
        pnlPoints=current - entry,
        entryContext=ctx,
    )


def _params() -> ExplosionExitParams:
    return ExplosionExitParams(
        stop_points=15.84,
        target_points=46.16,
        trail_arm_points=18.27,
        trail_keep_ratio=0.59,
        micro_target_points=3.0,
        adaptive_stop=True,
    )


@patch("app.engines.explosion_profit.get_settings")
def test_thesis_hold_qualifies_after_green(mock_s):
    mock_s.return_value = _settings()
    trade = _trade(best=8.54, current=69.15, hold_s=2700)
    assert _structured_green_thesis_hold_seconds(
        trade, best=8.54, settings=_settings()
    ) == 10800


@patch("app.engines.explosion_profit.get_settings")
def test_just_green_best_2pts_qualifies(mock_s):
    """As soon as trade goes green (best ≥ 2), thesis hold arms."""
    mock_s.return_value = _settings()
    trade = _trade(best=2.0, current=73.0, hold_s=600)
    assert (
        _structured_green_thesis_hold_seconds(trade, best=2.0, settings=_settings())
        == 10800
    )


@patch("app.engines.explosion_profit.get_settings")
def test_yesterday_never_green_no_thesis_hold(mock_s):
    mock_s.return_value = _settings()
    trade = _trade(best=0.44, current=55.0, hold_s=1800, never_green_style=True)
    assert (
        _structured_green_thesis_hold_seconds(trade, best=0.44, settings=_settings())
        == 0
    )


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_aug4_holds_past_elite_time_stop(mock_s, _hc, _mp):
    """Aug4: best +8.5, hold ~45min — must NOT explosion_time_stop."""
    s = _settings()
    mock_s.return_value = s
    trade = _trade(best=8.54, current=69.15, hold_s=2700)
    reason, _pnl = evaluate_explosion_exit(
        trade, 69.15, "ELITE", 10, params=_params(), live_velocity_3s=0.1,
    )
    assert reason != "explosion_time_stop"
    assert reason != "explosion_time_profit"


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
def test_yesterday_style_still_time_stops(mock_s, _hc, _mp):
    """Aug3 never-green: best 0.44 at 30min+ — still explosion_time_stop."""
    s = _settings()
    mock_s.return_value = s
    trade = _trade(best=0.44, current=54.0, hold_s=2600, never_green_style=True)
    reason, _pnl = evaluate_explosion_exit(
        trade, 54.0, "ELITE", 10, params=_params(), live_velocity_3s=0.0,
    )
    assert reason == "explosion_per_trade_risk_cap"


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_green_thesis_no_time_stop_after_hours(mock_s, _hc, _mp):
    """Once green, clock never forces exit — trail/SL own it."""
    s = _settings()
    mock_s.return_value = s
    trade = _trade(best=8.54, current=68.0, hold_s=7200)  # 2h
    reason, _pnl = evaluate_explosion_exit(
        trade, 68.0, "ELITE", 10, params=_params(), live_velocity_3s=0.0,
    )
    assert reason not in ("explosion_time_stop", "explosion_time_profit")


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_legacy_cap_when_skip_disabled(mock_s, _hc, _mp):
    s = _settings(
        explosion_thesis_hold_skip_time_exit=False,
        explosion_thesis_hold_max_seconds=3600,
    )
    mock_s.return_value = s
    trade = _trade(best=8.54, current=68.0, hold_s=3700)
    reason, _pnl = evaluate_explosion_exit(
        trade, 68.0, "ELITE", 10, params=_params(), live_velocity_3s=0.0,
    )
    assert reason == "explosion_early_green_breakeven"
