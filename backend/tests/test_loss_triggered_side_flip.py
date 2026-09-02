"""Loss-triggered opposite side flip — CE/PE symmetry."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.loss_triggered_side_flip import (
    consecutive_same_side_losses,
    loss_triggered_opposite_flip_ready,
    reset_loss_triggered_side_flip,
)
from app.engines.pretrade_validator import TradeRecord
from app.engines.whipsaw_guards import (
    check_opposite_side_cooldown,
    record_trade_close,
    reset_whipsaw_guards,
)
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    s = Settings()
    s.loss_triggered_side_flip_enabled = True
    s.loss_triggered_side_flip_min_same_side_losses = 1
    s.loss_triggered_side_flip_elite_only = True
    s.opposite_side_cooldown_after_loss_seconds = 0
    s.opposite_side_cooldown_seconds = 420
    s.index_rally_side_flip_min_pts = 130.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(
    *,
    rally_pts: float = 140.0,
    session_low: float = 76000.0,
    spot: float = 76140.0,
    rsi: float = 55.0,
    macd_bias: str = "BULLISH",
    mom5: float = 0.08,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 9, 2, 9, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=spot,
        dataAvailable=True,
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias="BEARISH", score=40),
        spotChart=SpotChart(
            direction="NEUTRAL",
            rsi=rsi,
            macdBias=macd_bias,
            macdHistogram=1.0,
            momentum5Pct=mom5,
            sessionLow=session_low,
            sessionHigh=spot + 50,
        ),
    )


def _elite_candidate():
    from types import SimpleNamespace

    return SimpleNamespace(
        tier="ELITE",
        score=95.0,
        confidence=95.0,
        mode="explosion",
        side=Side.CALL,
        symbol="SENSEX",
    )


@pytest.fixture(autouse=True)
def _reset():
    reset_whipsaw_guards()
    reset_loss_triggered_side_flip()


def test_consecutive_same_side_losses_counts_trailing_puts():
    trades = [
        TradeRecord("SENSEX", "CALL", 200),
        TradeRecord("SENSEX", "PUT", -500),
        TradeRecord("SENSEX", "PUT", -1000),
    ]
    assert consecutive_same_side_losses(trades, "SENSEX", "PUT") == 2
    assert consecutive_same_side_losses(trades, "SENSEX", "CALL") == 0


@patch("app.engines.loss_triggered_side_flip.get_settings", return_value=_settings())
@patch(
    "app.engines.index_rally_side_flip._session_extremes_and_spot",
    return_value=(76200.0, 76000.0, 76140.0),
)
def test_loss_triggered_call_after_put_loss_and_rally(mock_ext, mock_settings):
    trades = [TradeRecord("SENSEX", "PUT", -5643)]
    snap = _snap()
    ok, reason, meta = loss_triggered_opposite_flip_ready(
        "SENSEX",
        Side.CALL,
        snap,
        trades=trades,
        candidate=_elite_candidate(),
    )
    assert ok is True
    assert reason == "loss_triggered_side_flip"
    assert meta["consecutiveLosses"] == 1


@patch("app.engines.loss_triggered_side_flip.get_settings", return_value=_settings())
@patch(
    "app.engines.index_rally_side_flip._session_extremes_and_spot",
    return_value=(76200.0, 76000.0, 76140.0),
)
def test_loss_triggered_bypasses_opposite_cooldown(mock_ext, mock_settings):
    record_trade_close("SENSEX", Side.PUT, -10_000, "stop")
    snap = _snap()
    state = AutoTraderState()

    with patch(
        "app.engines.whipsaw_guards.get_settings",
        return_value=_settings(),
    ), patch(
        "app.engines.loss_triggered_side_flip.get_settings",
        return_value=_settings(),
    ), patch(
        "app.engines.index_rally_side_flip.get_settings",
        return_value=_settings(),
    ), patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76200.0, 76000.0, 76140.0),
    ), patch(
        "app.engines.loss_triggered_side_flip.collect_session_trades",
        return_value=[TradeRecord("SENSEX", "PUT", -10_000)],
    ):
        blocked, reason = check_opposite_side_cooldown(
            "SENSEX",
            Side.CALL,
            snap,
            state=state,
            candidate=_elite_candidate(),
        )
    assert blocked is False
    assert reason == "ok"


@patch("app.engines.loss_triggered_side_flip.get_settings", return_value=_settings())
def test_no_flip_without_index_rally(mock_settings):
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76200.0, 76000.0, 76020.0),
    ):
        trades = [TradeRecord("SENSEX", "PUT", -1000)]
        snap = _snap(spot=76020.0)
        ok, reason, _ = loss_triggered_opposite_flip_ready(
            "SENSEX",
            Side.CALL,
            snap,
            trades=trades,
            candidate=_elite_candidate(),
        )
    assert ok is False
    assert "rally" in reason or "pts" in reason
