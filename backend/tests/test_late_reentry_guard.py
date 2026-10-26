"""Late re-entry guards — block chasing a strike after its session peak."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
import app.engines.explosion_detector as ed
from app.engines.explosion_detector import (
    _open_key,
    _session_low,
    _session_peak,
)
from app.engines.session_mode_feedback import (
    cap_post_win_continuation_leg_lots,
    exhausted_ftv_reentry_blocked,
    post_win_session_late_reentry_waive,
    session_peak_late_reentry_blocked,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _seed_session_peak(*, symbol: str, strike: float, side: Side, low: float, peak: float) -> str:
    key = _open_key(symbol, strike, side)
    _session_low[key] = low
    _session_peak[key] = peak
    return key


def test_session_peak_late_reentry_blocks_near_peak_chase():
    _seed_session_peak(
        symbol="NIFTY", strike=24250.0, side=Side.PUT, low=100.5, peak=121.85,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.PUT,
            strike=24250.0,
            premium=110.1,
            velocity_3s=0.14,
            alert={"ictFlatThenVertical": True, "earlyRadarPadCapture": True},
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


def test_session_peak_late_reentry_allows_deep_pullback():
    _seed_session_peak(
        symbol="NIFTY", strike=24250.0, side=Side.PUT, low=100.5, peak=121.85,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
    )
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.PUT,
            strike=24250.0,
            premium=94.0,
            velocity_3s=0.2,
            alert={},
        )
    assert blocked is False
    assert reason == ""


def test_session_peak_late_reentry_waives_first_strike_entry_sep16_style():
    """Sep16 SENSEX 74200 PE — initial armed rip, no prior trade on strike."""
    _seed_session_peak(
        symbol="SENSEX", strike=74200.0, side=Side.PUT, low=294.85, peak=315.9,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_waive_first_strike_entry_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    state = AutoTraderState(closedPaperTrades=[], openPaperTrades=[])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="SENSEX",
            side=Side.PUT,
            strike=74200.0,
            premium=311.7,
            velocity_3s=0.0,
            alert={
                "tier": "EXPLODING",
                "ictArmedBaseLaunch": True,
                "momentType": "armed_base_launch",
                "strikeStepsFromAtm": 1,
            },
            state=state,
        )
    assert blocked is False
    assert reason == ""


def test_session_peak_late_reentry_no_first_strike_waive_on_far_otm():
    _seed_session_peak(
        symbol="SENSEX", strike=75100.0, side=Side.CALL, low=120.0, peak=180.0,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_waive_first_strike_entry_enabled=True,
        explosion_late_reentry_waive_max_otm_steps=2,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
    )
    state = AutoTraderState(closedPaperTrades=[], openPaperTrades=[])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="SENSEX",
            side=Side.CALL,
            strike=75100.0,
            premium=170.0,
            velocity_3s=0.2,
            alert={
                "tier": "ELITE",
                "ictArmedBaseLaunch": True,
                "strikeStepsFromAtm": 4,
            },
            state=state,
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


def test_session_peak_late_reentry_still_blocks_after_prior_close_on_strike():
    _seed_session_peak(
        symbol="SENSEX", strike=74200.0, side=Side.PUT, low=294.85, peak=352.8,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_waive_first_strike_entry_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    prior = PaperTrade(
        id="71f5db55",
        symbol="SENSEX",
        side=Side.PUT,
        strike=74200.0,
        entryPremium=340.88,
        currentPremium=382.3,
        lots=26,
        openedAt=datetime.now(IST) - timedelta(minutes=10),
        closedAt=datetime.now(IST) - timedelta(minutes=5),
        status="CLOSED",
        exitReason="explosion_peak_keep_trail",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=20535.78,
    )
    state = AutoTraderState(closedPaperTrades=[prior])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="SENSEX",
            side=Side.PUT,
            strike=74200.0,
            premium=348.0,
            velocity_3s=0.2,
            alert={"ictFlatThenVertical": True},
            state=state,
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


def test_session_peak_late_reentry_blocks_sep28_shallow_pullback_hot_v3():
    """Sep28 NIFTY 22850 PE — first-lift + v3=2 near peak with ~2% pullback is a chase."""
    _seed_session_peak(
        symbol="NIFTY", strike=22850.0, side=Side.PUT, low=71.6, peak=89.1,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        explosion_late_reentry_first_lift_hot_v3_min_pullback_pct=8.0,
    )
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.PUT,
            strike=22850.0,
            premium=84.15,
            velocity_3s=2.0,
            alert={
                "ictFirstLift": True,
                "firstLiftReadinessReason": "first_lift_local_base_ready",
                "spikeRunPct": 20.39,
                "peakMovePct": 20.39,
            },
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


def test_session_peak_late_reentry_blocks_sep28_shallow_pullback_hot_v3_ce_mirror():
    """PE/CE symmetry — same near-peak shallow-pullback chase on CALL."""
    _seed_session_peak(
        symbol="NIFTY", strike=22900.0, side=Side.CALL, low=71.6, peak=89.1,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        explosion_late_reentry_first_lift_hot_v3_min_pullback_pct=8.0,
    )
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.CALL,
            strike=22900.0,
            premium=84.15,
            velocity_3s=2.0,
            alert={
                "ictFirstLift": True,
                "firstLiftReadinessReason": "first_lift_local_base_ready",
                "spikeRunPct": 20.39,
            },
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


def test_session_peak_late_reentry_allows_unaged_tape_at_new_high():
    """Session peak just printed — cold v3 is the lift, not a late re-entry chase."""
    from collections import deque

    key = _seed_session_peak(
        symbol="NIFTY", strike=24100.0, side=Side.CALL, low=100.0, peak=140.0,
    )
    t0 = datetime(2026, 6, 15, 10, 0, 0, tzinfo=IST)
    ed._local_base_hist[key] = deque(
        (t0 + timedelta(seconds=i), p) for i, p in enumerate([100.0] * 15 + [140.0])
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        explosion_post_peak_chase_min_peak_age_seconds=45.0,
    )
    try:
        with patch(
            "app.engines.session_mode_feedback.get_settings",
            return_value=settings,
        ):
            blocked, reason = session_peak_late_reentry_blocked(
                symbol="NIFTY",
                side=Side.CALL,
                strike=24100.0,
                premium=140.0,
                velocity_3s=0.2,
                alert={"tier": "BUILDING"},
            )
    finally:
        ed._local_base_hist.pop(key, None)
    assert blocked is False, reason


def test_session_peak_late_reentry_allows_fresh_first_lift():
    _seed_session_peak(
        symbol="NIFTY", strike=24250.0, side=Side.PUT, low=100.5, peak=121.85,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, _ = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.PUT,
            strike=24250.0,
            premium=110.1,
            velocity_3s=2.0,
            alert={
                "ictFirstLift": True,
                "firstLiftCapture": True,
                "firstLiftReadinessReason": "first_lift_local_base_ready",
            },
        )
    assert blocked is False


def test_exhausted_ftv_blocks_after_trail_lock_peak():
    settings = Settings(
        explosion_post_peak_reentry_guard_enabled=True,
        explosion_post_peak_reentry_lookback_seconds=1800,
        explosion_post_peak_reentry_min_peak_points=20.0,
        explosion_post_peak_reentry_base_samples=3,
        explosion_post_peak_reentry_base_span_seconds=6.0,
        explosion_post_peak_reentry_min_reacceleration_pct=8.0,
        explosion_post_peak_reentry_min_velocity_3s=1.5,
    )
    closed_at = datetime.now(IST) - timedelta(minutes=8)
    prior = PaperTrade(
        id="first-put",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24250.0,
        entryPremium=100.5,
        currentPremium=100.65,
        lots=3,
        openedAt=closed_at - timedelta(minutes=38),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_trail_lock",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=-50.0,
        pnlPoints=0.0,
        bestPnlPoints=19.92,
        maxLtp=121.85,
        entryContext={
            "selectionMode": "explosion",
            "ictFlatThenVertical": True,
            "afternoonCapture": True,
        },
    )
    state = AutoTraderState(closedPaperTrades=[prior])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, meta = exhausted_ftv_reentry_blocked(
            state,
            symbol="NIFTY",
            side=Side.PUT,
            strike=24250.0,
            premium=110.1,
            velocity_3s=0.14,
        )
    assert blocked is True
    assert meta["applied"] is True
    assert meta["priorPeak"] == pytest.approx(121.85, rel=1e-3)


def _nifty_ce_win_trade(*, strike: float = 22500.0, minutes_ago: int = 120) -> PaperTrade:
    closed_at = datetime.now(IST) - timedelta(minutes=minutes_ago)
    return PaperTrade(
        id="oct26-ce-win",
        symbol="NIFTY",
        side=Side.CALL,
        strike=strike,
        entryPremium=197.6,
        currentPremium=225.0,
        lots=8,
        openedAt=closed_at - timedelta(minutes=6),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_peak_keep_trail",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=5089.0,
        entryContext={"selectionMode": "explosion"},
    )


def test_post_win_new_local_base_waives_session_peak_late_reentry():
    """Oct26-style: re-base on pad after CE win — not a blind session-peak chase."""
    _seed_session_peak(
        symbol="NIFTY", strike=22500.0, side=Side.CALL, low=167.0, peak=225.7,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        post_win_late_reentry_waive_enabled=True,
        post_win_new_local_base_max_pad_pct=22.0,
    )
    state = AutoTraderState(closedPaperTrades=[_nifty_ce_win_trade()])
    alert = {
        "ictBaseArmed": True,
        "ictFlatThenVertical": True,
        "localBaseMovePct": 14.0,
        "tier": "ELITE",
    }
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ), patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(False, {}),
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.CALL,
            strike=22500.0,
            premium=244.0,
            velocity_3s=0.3,
            alert=alert,
            state=state,
        )
    assert blocked is False
    assert reason == "post_win_late_reentry_waive_new_local_base"


def test_post_win_continuation_leg_waives_once_with_hot_v3():
    _seed_session_peak(
        symbol="NIFTY", strike=22500.0, side=Side.CALL, low=167.0, peak=225.7,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        post_win_continuation_leg_enabled=True,
        post_win_continuation_leg_min_velocity_3s=2.0,
    )
    state = AutoTraderState(closedPaperTrades=[_nifty_ce_win_trade()])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ), patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(False, {}),
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.CALL,
            strike=22500.0,
            premium=244.0,
            velocity_3s=2.4,
            alert={"tier": "BUILDING"},
            state=state,
        )
    assert blocked is False
    assert reason == "post_win_late_reentry_waive_continuation_leg"


def test_post_win_continuation_leg_cold_v3_still_blocked():
    _seed_session_peak(
        symbol="NIFTY", strike=22500.0, side=Side.CALL, low=167.0, peak=225.7,
    )
    settings = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        post_win_continuation_leg_min_velocity_3s=2.0,
    )
    state = AutoTraderState(closedPaperTrades=[_nifty_ce_win_trade()])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ), patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(False, {}),
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="NIFTY",
            side=Side.CALL,
            strike=22500.0,
            premium=244.0,
            velocity_3s=0.5,
            alert={"tier": "BUILDING"},
            state=state,
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


def test_post_win_continuation_leg_caps_lots_not_full_rank():
    settings = Settings(
        post_win_continuation_leg_enabled=True,
        post_win_continuation_leg_min_velocity_3s=2.0,
        post_win_continuation_leg_lot_cap=4,
    )
    state = AutoTraderState(closedPaperTrades=[_nifty_ce_win_trade()])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ), patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(False, {}),
    ):
        capped, meta = cap_post_win_continuation_leg_lots(
            20,
            state,
            symbol="NIFTY",
            side=Side.CALL,
            strike=22500.0,
            premium=244.0,
            velocity_3s=2.5,
            alert={"tier": "BUILDING"},
        )
    assert capped == 4
    assert meta.get("postWinContinuationLegCapApplied") is True


def test_post_win_only_one_continuation_leg_after_win():
    settings = Settings(
        post_win_continuation_leg_enabled=True,
        post_win_continuation_leg_min_velocity_3s=2.0,
    )
    win = _nifty_ce_win_trade(minutes_ago=180)
    leg = PaperTrade(
        id="post-win-leg",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22500.0,
        entryPremium=240.0,
        currentPremium=238.0,
        lots=4,
        openedAt=win.closedAt + timedelta(minutes=30),
        closedAt=win.closedAt + timedelta(minutes=35),
        status="CLOSED",
        exitReason="explosion_trail_lock",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=-800.0,
        entryContext={"selectionMode": "explosion"},
    )
    state = AutoTraderState(closedPaperTrades=[win, leg])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ), patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(False, {}),
    ):
        waived, mode, meta = post_win_session_late_reentry_waive(
            state,
            symbol="NIFTY",
            side=Side.CALL,
            strike=22500.0,
            premium=245.0,
            velocity_3s=3.0,
            alert={"tier": "BUILDING"},
        )
    assert waived is False
    assert mode == ""
    assert meta.get("sameStrikeLegsAfterWin") == 1
