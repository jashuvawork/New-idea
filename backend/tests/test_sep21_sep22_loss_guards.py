"""Sep21/Sep22 loss guards — counter-trend chop FTV + post-win afternoon giveback."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.best_trade_policy import (
    symmetric_chop_counter_trend_blocks_entry,
    symmetric_chop_ftv_launch_evidence,
)
from app.engines.chop_day_guards import chop_post_win_afternoon_fomo_risk
from app.engines.explosion_entry_guards import detect_fake_explosion_trap
from app.engines.rally_capture import chart_blocks_explosion_side
from app.engines.pretrade_validator import TradeRecord
from app.models.schemas import (
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _enable_symmetric_capture():
    with patch(
        "app.engines.best_trade_policy.symmetric_best_trade_capture_active",
        return_value=True,
    ):
        yield


def _bullish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 21, 10, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=23350.0,
        atmStrike=23350.0,
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.3, trendStrength=55.0),
    )


def _bearish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 22, 10, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=23350.0,
        atmStrike=23350.0,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.3, trendStrength=55.0),
    )


def _sep21_put_evidence(**overrides):
    base = {
        "tier": "EXPLODING",
        "side": "PUT",
        "localBaseMovePct": 17.9,
        "ictBaseRelativeMovePct": 17.9,
        "explosionScore": 95.0,
        "vRipReady": True,
        "ictVRipReady": True,
    }
    base.update(overrides)
    return base


def _sep21_put_assessment(**overrides):
    base = {
        "mustTake": False,
        "eliteScore": 92.9,
        "grade": "A",
        "setup": "V",
        "localBasePct": 17.9,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_symmetric_chop_ftv_launch_requires_flat_vertical_not_vrip(side):
    vrip_only = {"side": side, "vRipReady": True, "ictVRipReady": True}
    assert symmetric_chop_ftv_launch_evidence(vrip_only) is False

    ftv = {
        "side": side,
        "ictFlatThenVertical": True,
        "ictFirstLift": True,
    }
    assert symmetric_chop_ftv_launch_evidence(ftv) is True


def test_sep21_counter_trend_put_blocked_without_ftv_launch():
    """Sep21 NIFTY 23350 PE — counter-trend V-rip chop pad must not pass symmetric mode."""
    settings = Settings(
        symmetric_chop_counter_trend_guard_enabled=True,
        symmetric_best_trade_capture_enabled=True,
    )
    blocked, reason = symmetric_chop_counter_trend_blocks_entry(
        _sep21_put_evidence(),
        _sep21_put_assessment(),
        day_mode="CHOP + RALLY",
        side="PUT",
        snap=_bullish_snap(),
        settings=settings,
    )
    assert blocked is True
    assert reason == "symmetric_chop_counter_trend_requires_ftv"


def test_sep21_aligned_call_passes_counter_trend_guard():
    """Sep21 morning CALL winners — aligned side on CHOP+RALLY is not blocked."""
    settings = Settings()
    evidence = {
        "tier": "ELITE",
        "side": "CALL",
        "localBaseMovePct": 12.0,
        "explosionScore": 88.0,
    }
    assessment = {
        "mustTake": False,
        "eliteScore": 94.0,
        "grade": "A",
        "setup": "FTV",
        "localBasePct": 12.0,
    }
    blocked, reason = symmetric_chop_counter_trend_blocks_entry(
        evidence,
        assessment,
        day_mode="CHOP + RALLY",
        side="CALL",
        snap=_bullish_snap(),
        settings=settings,
    )
    assert blocked is False
    assert reason == ""


def test_sep22_aligned_put_ftv_passes_counter_trend_guard():
    """Sep22 NIFTY 23350 PE — bearish aligned PUT with FTV launch passes."""
    settings = Settings()
    evidence = {
        "tier": "ELITE",
        "side": "PUT",
        "localBaseMovePct": 12.0,
        "ictFlatThenVertical": True,
        "ictFirstLift": True,
    }
    assessment = {
        "mustTake": False,
        "eliteScore": 95.0,
        "grade": "A",
        "setup": "FTV",
        "localBasePct": 12.0,
    }
    blocked, reason = symmetric_chop_counter_trend_blocks_entry(
        evidence,
        assessment,
        day_mode="EXPIRY WORST",
        side="PUT",
        snap=_bearish_snap(),
        settings=settings,
    )
    assert blocked is False


def test_sep22_counter_trend_ce_passes_with_ftv_launch():
    """Sep22 afternoon CE rip — counter-trend but true FTV at base is allowed."""
    settings = Settings()
    evidence = {
        "tier": "ELITE",
        "side": "CALL",
        "localBaseMovePct": 14.0,
        "ictFlatThenVertical": True,
        "ictFirstLift": True,
    }
    assessment = {
        "mustTake": False,
        "eliteScore": 93.0,
        "grade": "A",
        "setup": "FTV",
        "localBasePct": 14.0,
    }
    blocked, reason = symmetric_chop_counter_trend_blocks_entry(
        evidence,
        assessment,
        day_mode="EXPIRY WORST",
        side="CALL",
        snap=_bearish_snap(),
        settings=settings,
    )
    assert blocked is False


def test_chart_blocks_counter_trend_elite_without_ftv():
    settings = Settings()
    snap = _bullish_snap()
    blocked, reason = chart_blocks_explosion_side(
        "PUT",
        snap.spotChart,
        "ELITE",
        snap=snap,
        alert=_sep21_put_evidence(tier="ELITE"),
    )
    assert blocked is True
    assert reason == "explosion_put_vs_bullish_chart"


def test_chart_allows_counter_trend_elite_with_ftv_launch():
    snap = _bullish_snap()
    blocked, reason = chart_blocks_explosion_side(
        "PUT",
        snap.spotChart,
        "ELITE",
        snap=snap,
        alert=_sep21_put_evidence(
            tier="ELITE",
            ictFlatThenVertical=True,
            ictFirstLift=True,
        ),
    )
    assert blocked is False


def test_chop_post_win_afternoon_fomo_after_large_trail_win():
    """Sep21 afternoon — large trail win must still trigger chop post-win gate."""
    settings = Settings(
        chop_post_win_afternoon_block_enabled=True,
        fake_explosion_trap_chop_post_win_afternoon_enabled=True,
    )
    state = MagicMock(
        dailyStrategy={"dayMode": "CHOP + RALLY"},
    )
    with patch(
        "app.engines.explosion_entry_guards._post_session_win",
        return_value=(
            True,
            {"lastPnlInr": 4407.0, "postSessionWin": True},
        ),
    ):
        fomo, reasons = chop_post_win_afternoon_fomo_risk(
            state,
            day_mode="CHOP + RALLY",
            settings=settings,
        )
    assert fomo is True
    assert "chop_day" in reasons
    assert "post_session_win" in reasons


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_sep21_chop_post_win_afternoon_hard_blocks(mock_money, mock_settings):
    settings = Settings(
        chop_post_win_afternoon_block_enabled=True,
        fake_explosion_trap_chop_post_win_afternoon_enabled=True,
    )
    mock_settings.return_value = settings
    mock_money.return_value = settings

    snap = _bullish_snap()
    event = MagicMock(
        tier="EXPLODING",
        side=Side.PUT,
        strike=23350.0,
        premium=62.0,
        velocity_3s=1.5,
        daily_move_pct=18.0,
        peak_move_pct=18.0,
        explosion_score=90.0,
        reason="test",
    )
    cand = MagicMock(
        mode="explosion",
        side=Side.PUT,
        strike=23350.0,
        score=90.0,
        tier="EXPLODING",
        explosion_event=event,
        alert={"localBaseMovePct": 18.0},
    )

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side=Side.CALL,
                pnl_inr=4407.0,
                exit_reason="explosion_peak_keep_trail",
                strike=23450.0,
            ),
        ],
    ), patch(
        "app.engines.explosion_entry_guards._midday_chop_active",
        return_value=False,
    ), patch(
        "app.engines.morning_premium_capture.is_afternoon_capture_event",
        return_value=True,
    ), patch(
        "app.engines.explosion_entry_guards._post_small_win",
        return_value=(False, {}),
    ), patch(
        "app.engines.explosion_entry_guards._post_session_win",
        return_value=(True, {"lastPnlInr": 4407.0, "postSessionWin": True}),
    ):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand,
            snap,
            state=MagicMock(dailyStrategy={"dayMode": "CHOP + RALLY"}),
            ict=MagicMock(base_relative_move_pct=18.0),
        )

    assert blocked is True
    assert reason == "fake_explosion_trap_chop_post_win_afternoon"
    assert meta.get("postWinChopAfternoon") is True
