"""Peak-fade / peak-capture profit locks — book near the top when a peaked trade dies."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import (
    ExplosionExitParams,
    evaluate_explosion_exit,
    peak_capture_profit_lock_reason,
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
    s.explosion_peak_fade_max_profit_min_best = 28.0
    s.explosion_peak_fade_max_profit_giveback_ratio = 0.80
    s.explosion_peak_fade_defer_when_bullish = True
    s.explosion_peak_fade_bullish_min_remain_points = 3.0
    s.explosion_peak_fade_bullish_min_velocity_3s = 1.5
    s.explosion_near_base_hold_enabled = True
    s.explosion_near_base_hold_max_entry_rel_pct = 20.0
    s.explosion_near_base_hold_min_best_points = 28.0
    s.explosion_peak_capture_enabled = True
    s.explosion_peak_capture_min_best_points = 8.0
    s.explosion_peak_capture_giveback_ratio = 0.22
    s.explosion_peak_capture_min_giveback_points = 2.0
    s.explosion_peak_capture_min_remain_points = 1.0
    s.explosion_peak_capture_max_live_velocity_3s = 1.0
    s.explosion_peak_capture_max_premium_mom_pct = 0.15
    s.explosion_peak_capture_max_profit_min_best = 28.0
    s.explosion_peak_capture_max_profit_giveback_ratio = 0.35
    s.explosion_peak_capture_big_peak_points = 25.0
    s.explosion_peak_capture_big_peak_giveback_ratio = 0.22
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
def test_peak_capture_near_12pt_top_when_rolling_over(mock_s):
    """best +12 → +9.2 with cold velocity → bank near the peak (not wait for time-stop)."""
    mock_s.return_value = _settings()
    trade = _trade(
        current=51.75,
        best=12.0,
        ctx={
            "liveVelocity3s": 0.3,
            "psychologyLabel": "NEUTRAL",
            "psychologyExitBias": "BALANCED",
            "premiumChart": {"momentum3Pct": -0.2},
        },
    )
    # giveback 2.8 ≈ 23% of 12 — above 22% capture threshold, still ~+9 green
    reason = peak_capture_profit_lock_reason(
        trade, best=12.0, pnl_pts=9.2, max_profit=False, live_velocity_3s=0.3,
    )
    assert reason == "explosion_peak_capture"


@patch("app.engines.explosion_profit.get_settings")
def test_big_peak_banks_near_top_on_max_profit_rollover(mock_s):
    """Aug12 NIFTY 24350 PE: +36.7pt max-profit peak rolled over (cold tape).

    Old max-profit giveback 0.35 held until ~+23.9 (gave back ~13pt). The big-peak
    tighten keeps ~78%, so a ~9pt giveback (still +27.5) banks near the top.
    """
    mock_s.return_value = _settings()
    ctx = {
        "liveVelocity3s": -0.1,
        "localBaseBaseRelPct": 33.1,
        "ictFlatThenVertical": True,
        "maxProfitCapture": True,
        "psychologyLabel": "GREED",
        "psychologyExitBias": "LET_RUNNERS",
        "premiumChart": {"momentum3Pct": -0.1},
    }
    trade = _trade(entry=98.32, best=36.74, current=125.82, ctx=ctx)
    # giveback 9.24 ≈ 25% of 36.74 — above the 22% big-peak threshold, still +27.5.
    reason = peak_capture_profit_lock_reason(
        trade, best=36.74, pnl_pts=27.5, max_profit=True, live_velocity_3s=-0.1,
    )
    assert reason == "explosion_peak_capture"


@patch("app.engines.explosion_profit.get_settings")
def test_big_peak_disabled_keeps_loose_max_profit_giveback(mock_s):
    """Below the big-peak threshold the loose max-profit giveback (0.35) still
    holds at +27.5 (giveback 9.24 < 0.35×36.74) — proving the new lock is what
    banks near the top once the peak is large."""
    mock_s.return_value = _settings(explosion_peak_capture_big_peak_points=999.0)
    ctx = {
        "liveVelocity3s": -0.1,
        "localBaseBaseRelPct": 33.1,
        "ictFlatThenVertical": True,
        "maxProfitCapture": True,
        "premiumChart": {"momentum3Pct": -0.1},
    }
    trade = _trade(entry=98.32, best=36.74, current=125.82, ctx=ctx)
    reason = peak_capture_profit_lock_reason(
        trade, best=36.74, pnl_pts=27.5, max_profit=True, live_velocity_3s=-0.1,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_peak_capture_skips_hot_velocity(mock_s):
    """Same giveback while still ripping → do not force near-top bank."""
    mock_s.return_value = _settings()
    trade = _trade(
        current=51.75,
        best=12.0,
        ctx={"liveVelocity3s": 3.8, "premiumChart": {"momentum3Pct": 1.2}},
    )
    reason = peak_capture_profit_lock_reason(
        trade, best=12.0, pnl_pts=9.2, max_profit=False, live_velocity_3s=3.8,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_peak_fade_prefers_capture_before_deep_fade(mock_s):
    """Ladder: near-top capture fires before deep 55% fade lock."""
    mock_s.return_value = _settings()
    trade = _trade(
        current=51.75,
        best=12.0,
        ctx={
            "liveVelocity3s": 0.2,
            "psychologyLabel": "NEUTRAL",
            "psychologyExitBias": "BALANCED",
        },
    )
    reason = peak_fade_profit_lock_reason(
        trade, best=12.0, pnl_pts=9.2, max_profit=False, live_velocity_3s=0.2,
    )
    assert reason == "explosion_peak_capture"


@patch("app.engines.explosion_profit.get_settings")
def test_jul31_fade_from_12pt_books_remaining_green(mock_s):
    """best +12.5 → +2.3 with trail unarmed → capture/lock remaining profit."""
    mock_s.return_value = _settings()
    # current 44.85 → +2.3pt; giveback 10.23 — peak capture fires first (cold tape).
    reason = peak_fade_profit_lock_reason(
        _trade(current=44.85, ctx={"liveVelocity3s": 0.1}),
        best=12.53,
        pnl_pts=2.3,
        max_profit=False,
        live_velocity_3s=0.1,
    )
    assert reason == "explosion_peak_capture"


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=False)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
def test_evaluate_exit_locks_jul31_profile(mock_s, _hc, _mp):
    mock_s.return_value = _settings()
    trade = _trade(current=44.85, best=12.53, ctx={"liveVelocity3s": 0.1})
    reason, pnl = evaluate_explosion_exit(
        trade, 44.85, "EXPLODING", 65, params=_params(), live_velocity_3s=0.1,
    )
    assert reason == "explosion_peak_capture"
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
        _trade(current=52.0, best=10.0, ctx={"liveVelocity3s": 2.5}),
        best=10.0,
        pnl_pts=9.45,
        max_profit=False,
        live_velocity_3s=2.5,
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
        live_velocity_3s=0.1,
    )
    assert reason is None
    # After a real expansion peak (≥28), deep fade / capture does lock.
    reason2 = peak_fade_profit_lock_reason(
        _trade(
            current=50.0,
            best=40.0,
            ctx={
                "liveVelocity3s": 0.2,
                "psychologyLabel": "NEUTRAL",
                "psychologyExitBias": "BALANCED",
                "premiumChart": {"momentum3Pct": -0.2},
            },
        ),
        best=40.0,
        pnl_pts=7.45,
        max_profit=True,
        live_velocity_3s=0.2,
    )
    assert reason2 == "explosion_peak_capture"


@patch("app.engines.explosion_profit.get_settings")
def test_aug6_78700_max_profit_holds_first_pullback(mock_s):
    """Aug6 SENSEX 78700 CE: best +15.4 → +6.5 with OVERCONFIDENCE must HOLD.

    Old path tightened giveback to 50% and disabled near-base hold, booking before
    the extension to ~460. Max-profit + near-base must wait for a ≥28pt peak.
    """
    mock_s.return_value = _settings()
    trade = _trade(
        entry=380.1,
        best=15.42,
        current=386.65,
        ctx={
            "selectionMode": "explosion",
            "explosionTier": "EXPLODING",
            "maxProfitCapture": True,
            "ictFlatThenVertical": True,
            "defensiveBaseRip": True,
            "localBaseBasePremium": 330.6,
            "localBaseBaseRelPct": 14.5,
            "psychologyLabel": "OVERCONFIDENCE",
            "psychologyExitBias": "BALANCED",
            "liveVelocity3s": 0.5,
            "premiumChart": {"momentum3Pct": 0.0},
        },
    )
    reason = peak_fade_profit_lock_reason(
        trade, best=15.42, pnl_pts=6.55, max_profit=True, live_velocity_3s=0.5,
    )
    assert reason is None


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
            "premiumChart": {"momentum3Pct": 1.5},
        },
    )
    # +5.45 remain, giveback 7.08 (56% of peak) — would soft-lock without bullish defer.
    # Hot velocity also vetoes near-top capture.
    reason = peak_fade_profit_lock_reason(
        trade, best=12.53, pnl_pts=5.45, max_profit=False, live_velocity_3s=3.5,
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
        trade, best=12.53, pnl_pts=0.05, max_profit=False, live_velocity_3s=4.0,
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
        trade, best=12.53, pnl_pts=2.3, max_profit=False, live_velocity_3s=0.2,
    )
    assert reason == "explosion_peak_capture"
