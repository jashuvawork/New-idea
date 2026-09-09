"""Sep09 — CALL near session peak after PUT win: waive late reentry when index flip confirms."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_detector import _open_key, _session_low, _session_peak
from app.engines.session_mode_feedback import (
    cap_opposite_side_flip_after_win,
    session_peak_late_reentry_blocked,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Side,
    SpotChart,
    SymbolSnapshot,
    StrategyType,
)
from app.engines.directional_lock import record_trade_side, reset_directional_lock

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    base = dict(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
        explosion_late_reentry_waive_opposite_side_flip_enabled=True,
        explosion_whipsaw_flip_guard_enabled=True,
        explosion_whipsaw_flip_min_velocity_3s=2.5,
        explosion_whipsaw_flip_block_weak=True,
        explosion_whipsaw_flip_cap_instead_of_block_on_index_flip=True,
        explosion_whipsaw_flip_lot_cap=8,
        index_rally_side_flip_enabled=True,
        index_rally_side_flip_min_pts=130.0,
        index_rally_side_flip_min_rsi=50.0,
        index_rally_side_flip_require_macd_bullish=True,
        index_rally_side_flip_min_mom5_pct=0.05,
    )
    base.update(overrides)
    return Settings(**base)


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=76513.0,
        atmStrike=75100.0,
        breadth=Breadth(bias="BEARISH"),
        spotChart=SpotChart(
            direction="BULLISH",
            spot=76513.0,
            rsi=58.0,
            macdBias="BULLISH",
            macdHistogram=2.5,
            momentum5Pct=0.12,
        ),
    )


def _state_with_put_win() -> AutoTraderState:
    closed_at = datetime.now(IST) - timedelta(minutes=45)
    prior = PaperTrade(
        id="13d6a882",
        symbol="SENSEX",
        side=Side.PUT,
        strike=75100.0,
        entryPremium=222.45,
        currentPremium=238.9,
        lots=40,
        openedAt=closed_at - timedelta(minutes=32),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_peak_keep_trail",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=11940.0,
        pnlPoints=14.9,
        bestPnlPoints=21.4,
    )
    return AutoTraderState(closedPaperTrades=[prior])


def _seed_ce_peak(*, low: float = 280.0, peak: float = 326.2) -> None:
    key = _open_key("SENSEX", 75100.0, Side.CALL)
    _session_low[key] = low
    _session_peak[key] = peak


@patch("app.engines.index_rally_side_flip.get_settings")
@patch("app.engines.session_mode_feedback.get_settings")
def test_late_reentry_waived_for_call_after_put_win_with_index_rally(
    mock_settings, mock_index_settings,
):
    """Sep09 75100 CE: near session peak + cold v3 — allow when index flip confirms."""
    _seed_ce_peak()
    reset_directional_lock()
    s = _settings()
    mock_settings.return_value = s
    mock_index_settings.return_value = s
    state = _state_with_put_win()
    snap = _snap()
    record_trade_side("SENSEX", Side.PUT, snap)
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76513.0),
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="SENSEX",
            side=Side.CALL,
            strike=75100.0,
            premium=319.5,
            velocity_3s=0.14,
            alert={"tier": "EXPLODING", "ictFlatThenVertical": True},
            state=state,
            snap=snap,
        )
    assert blocked is False, reason


@patch("app.engines.session_mode_feedback.get_settings")
def test_late_reentry_still_blocks_without_opposite_win(mock_settings):
    _seed_ce_peak()
    mock_settings.return_value = _settings()
    snap = _snap()
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76513.0),
    ):
        blocked, reason = session_peak_late_reentry_blocked(
            symbol="SENSEX",
            side=Side.CALL,
            strike=75100.0,
            premium=319.5,
            velocity_3s=0.14,
            alert={"tier": "EXPLODING"},
            state=AutoTraderState(closedPaperTrades=[]),
            snap=snap,
        )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


@patch("app.engines.index_rally_side_flip.get_settings")
@patch("app.engines.session_mode_feedback.get_settings")
def test_whipsaw_flip_caps_instead_of_blocks_on_index_flip(
    mock_settings, mock_index_settings,
):
    s = _settings()
    mock_settings.return_value = s
    mock_index_settings.return_value = s
    reset_directional_lock()
    state = _state_with_put_win()
    snap = _snap()
    record_trade_side("SENSEX", Side.PUT, snap)
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76513.0),
    ):
        lots, meta = cap_opposite_side_flip_after_win(
            40,
            state,
            symbol="SENSEX",
            side=Side.CALL,
            velocity_3s=0.14,
            snap=snap,
        )
    assert meta.get("blocked") is not True
    assert lots == 8
    assert meta.get("indexFlipCapInsteadOfBlock") is True


@patch("app.engines.session_mode_feedback.get_settings")
def test_whipsaw_flip_still_blocks_weak_velocity_without_index_flip(mock_settings):
    mock_settings.return_value = _settings()
    state = _state_with_put_win()
    snap = _snap()
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76400.0, 76380.0, 76390.0),
    ):
        lots, meta = cap_opposite_side_flip_after_win(
            40,
            state,
            symbol="SENSEX",
            side=Side.CALL,
            velocity_3s=0.14,
            snap=snap,
        )
    assert meta.get("blocked") is True
    assert lots == 0
    assert meta.get("blockReason") == "whipsaw_flip_velocity_below_breakout"
