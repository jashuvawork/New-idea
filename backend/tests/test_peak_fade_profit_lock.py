"""Peak-fade profit lock — book remaining green when a peaked trade fades to losses."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import (
    ExplosionExitParams,
    evaluate_explosion_exit,
    peak_fade_profit_lock_reason,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.explosion_peak_fade_lock_enabled = True
    s.explosion_peak_fade_min_best_points = 6.0
    s.explosion_peak_fade_giveback_ratio = 0.55
    s.explosion_peak_fade_min_giveback_points = 4.0
    s.explosion_peak_fade_min_remain_points = 0.4
    s.explosion_peak_fade_breakeven_lock = True
    s.explosion_peak_fade_breakeven_buffer = 0.5
    s.explosion_peak_fade_max_profit_min_best = 15.0
    s.explosion_peak_fade_max_profit_giveback_ratio = 0.70
    s.explosion_peak_fade_defer_when_bullish = True
    s.explosion_peak_fade_bullish_min_remain_points = 3.0
    s.explosion_peak_fade_bullish_min_velocity_3s = 1.5
    s.explosion_faded_rip_no_green_exit_enabled = False
    s.bullish_hold_enabled = True
    s.explosion_stop_min_hold_seconds = 0
    s.emergency_stop_enabled = False
    s.ict_max_profit_skip_hard_target = True
    s.ict_max_profit_target_points = 180.0
    s.ict_max_profit_trail_keep_ratio = 0.42
    s.high_conviction_trail_keep_ratio = 0.30
    s.high_conviction_defer_profit_lock = True
    s.runner_min_best_points = 25.0
    s.runner_trail_keep_ratio = 0.55
    s.runner_micro_giveback_points = 4.0
    s.explosion_trail_arm_points = 22.0
    s.explosion_trail_keep_ratio = 0.55
    s.explosion_trail_step_points = 2.0
    s.explosion_trail_tight_arm = 999.0
    s.explosion_trail_tight_points = 0.0
    s.explosion_target_standard = 27.0
    s.explosion_no_progress_enabled = False
    s.chart_confidence_defer_tp_min = 90.0
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _trade(
    *,
    entry: float = 42.55,
    best: float = 12.53,
    current: float = 45.0,
    ctx: dict | None = None,
) -> PaperTrade:
    base = {
        "selectionMode": "explosion",
        "explosionTier": "EXPLODING",
        "psychologyLabel": "CAUTION",
        "psychologyExitBias": "PROTECT",
        "exitPlan": {
            "stopPoints": 11.5,
            "entryStopPoints": 11.5,
            "targetPoints": 27.66,
            "trailArmPoints": 22.88,
            "trailKeepRatio": 0.53,
            "microTargetPoints": 9.0,
            "psychologyLabel": "CAUTION",
        },
    }
    if ctx:
        base.update(ctx)
    return PaperTrade(
        id="4936659f",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500.0,
        entryPremium=entry,
        currentPremium=current,
        lots=6,
        openedAt=datetime.now(IST) - timedelta(minutes=80),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        pnlPoints=current - entry,
        entryContext=base,
    )


def _params() -> ExplosionExitParams:
    return ExplosionExitParams(
        stop_points=11.5,
        target_points=27.66,
        trail_arm_points=22.88,
        trail_keep_ratio=0.53,
        micro_target_points=9.0,
        adaptive_stop=True,
    )


@patch("app.engines.explosion_profit.get_settings")
def test_jul31_fade_from_12pt_books_remaining_green(mock_s):
    """best +12.5 → +2.3 with trail unarmed → lock remaining profit."""
    mock_s.return_value = _settings()
    # current 44.85 → +2.3pt; giveback 10.23 ≈ 82% of peak
    reason = peak_fade_profit_lock_reason(
        _trade(current=44.85), best=12.53, pnl_pts=2.3, max_profit=False,
    )
    assert reason == "explosion_peak_fade_profit_lock"


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
def test_evaluate_exit_locks_jul31_profile(mock_s, _hc, _mp):
    mock_s.return_value = _settings()
    trade = _trade(current=44.85, best=12.53)
    reason, pnl = evaluate_explosion_exit(
        trade, 44.85, "EXPLODING", 65, params=_params(),
    )
    assert reason == "explosion_peak_fade_profit_lock"
    assert pnl > 0


@patch("app.engines.explosion_profit.get_settings")
def test_breakeven_lock_after_peak(mock_s):
    mock_s.return_value = _settings()
    reason = peak_fade_profit_lock_reason(
        _trade(current=42.4, best=12.53), best=12.53, pnl_pts=-0.15, max_profit=False,
    )
    assert reason == "explosion_peak_fade_breakeven"


@patch("app.engines.explosion_profit.get_settings")
def test_still_rising_not_locked(mock_s):
    """+10pt and still near peak — do not force early bank."""
    mock_s.return_value = _settings()
    reason = peak_fade_profit_lock_reason(
        _trade(current=52.0, best=10.0), best=10.0, pnl_pts=9.45, max_profit=False,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_max_profit_needs_larger_peak(mock_s):
    mock_s.return_value = _settings()
    # Same 12.5→2.3 fade must NOT kill ICT max-profit runners early.
    reason = peak_fade_profit_lock_reason(
        _trade(current=44.85, best=12.53, ctx={"maxProfitCapture": True}),
        best=12.53,
        pnl_pts=2.3,
        max_profit=True,
    )
    assert reason is None
    # After a real expansion peak, deep fade does lock.
    reason2 = peak_fade_profit_lock_reason(
        _trade(current=50.0, best=40.0),
        best=40.0,
        pnl_pts=7.45,
        max_profit=True,
    )
    assert reason2 == "explosion_peak_fade_profit_lock"


@patch("app.engines.explosion_profit._chart_aligned_with_trade", return_value=True)
@patch("app.engines.bullish_hold.direction_aligned_with_breadth", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_bullish_continuation_defers_soft_lock(mock_s, _br, _ch):
    """Aligned + live heat + still ≥3pt green → hold pullback (not force bank)."""
    mock_s.return_value = _settings()
    trade = _trade(
        current=48.0,
        best=12.53,
        ctx={
            "breadth": "BULLISH",
            "liveVelocity3s": 3.5,
            "psychologyLabel": "NEUTRAL",
            "psychologyExitBias": "BALANCED",
        },
    )
    # +5.45 remain, giveback 7.08 (56% of peak) — would soft-lock without bullish defer.
    reason = peak_fade_profit_lock_reason(
        trade, best=12.53, pnl_pts=5.45, max_profit=False,
    )
    assert reason is None


@patch("app.engines.explosion_profit._chart_aligned_with_trade", return_value=True)
@patch("app.engines.bullish_hold.direction_aligned_with_breadth", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_bullish_chart_still_locks_near_breakeven(mock_s, _br, _ch):
    """Stale BULLISH chart must not ride a peaked winner into hard SL."""
    mock_s.return_value = _settings()
    trade = _trade(
        current=42.6,
        best=12.53,
        ctx={"breadth": "BULLISH", "liveVelocity3s": 4.0, "psychologyLabel": "NEUTRAL"},
    )
    reason = peak_fade_profit_lock_reason(
        trade, best=12.53, pnl_pts=0.05, max_profit=False,
    )
    assert reason == "explosion_peak_fade_breakeven"


@patch("app.engines.explosion_profit._chart_aligned_with_trade", return_value=True)
@patch("app.engines.bullish_hold.direction_aligned_with_breadth", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_bullish_but_dead_premium_still_soft_locks(mock_s, _br, _ch):
    """Chart bullish but velocity dead and only +2pt left → book (not wait for bearish flip)."""
    mock_s.return_value = _settings()
    trade = _trade(
        current=44.85,
        best=12.53,
        ctx={
            "breadth": "BULLISH",
            "liveVelocity3s": 0.2,
            "entryVelocity3s": 0.2,
            "psychologyLabel": "NEUTRAL",
            "psychologyExitBias": "BALANCED",
        },
    )
    reason = peak_fade_profit_lock_reason(
        trade, best=12.53, pnl_pts=2.3, max_profit=False,
    )
    assert reason == "explosion_peak_fade_profit_lock"
