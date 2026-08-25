"""Late re-entry guards — block chasing a strike after its session peak."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_detector import (
    _open_key,
    _session_low,
    _session_peak,
)
from app.engines.session_mode_feedback import (
    exhausted_ftv_reentry_blocked,
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
