"""Live best-trades-only gate tests."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.live_best_trades import (
    live_best_trade_entry_blocked,
    live_early_fail_exit_reason,
    live_session_loss_count,
)
from app.models.schemas import (
    AutoTraderState,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.enable_live_trading = True
    s.live_best_trades_only_enabled = True
    s.live_best_trades_min_grade = "S"
    s.live_best_trades_min_explosion_score = 200.0
    s.live_best_trades_tiers_csv = "ELITE,EXPLODING"
    s.live_best_trades_require_first_lift = True
    s.live_best_trades_min_local_base_pct = 15.0
    s.live_best_trades_require_chart_aligned = True
    s.live_max_open_positions = 1
    s.live_max_same_side_positions = 1
    s.live_pause_after_session_losses = 1
    s.live_early_fail_exit_enabled = True
    s.live_early_fail_min_hold_seconds = 45
    s.live_early_fail_max_hold_seconds = 240
    s.live_early_fail_max_best_points = 1.0
    s.live_early_fail_min_loss_points = 2.5
    s.live_early_fail_max_velocity_3s = 0.5
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _snap():
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        regime=Regime.CHOP,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.2),
    )


def _candidate(score=240.0, pad=8.0):
    event = SimpleNamespace(
        tier="EXPLODING",
        explosion_score=score,
        side=Side.PUT,
        symbol="NIFTY",
        strike=24050.0,
        daily_move_pct=30.0,
        peak_move_pct=30.0,
    )
    return SimpleNamespace(
        mode="explosion",
        side=Side.PUT,
        symbol="NIFTY",
        strike=24050.0,
        explosion_event=event,
        alert={"tier": "EXPLODING"},
        snap=_snap(),
    )


@patch("app.engines.live_best_trades.get_settings")
def test_blocks_sub_s_grade(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason, _ = live_best_trade_entry_blocked(
        _candidate(),
        _snap(),
        AutoTraderState(),
        ranking={"grade": "A", "evidence": {"tier": "EXPLODING"}},
    )
    assert blocked
    assert reason == "live_best_trades_requires_grade_s"


@patch("app.engines.live_best_trades.get_settings")
@patch("app.engines.top_moment_gate.top_moment_entry_allowed", return_value=(True, "ok", "EXPLODING"))
@patch("app.engines.spot_direction.side_aligned_with_chart", return_value=True)
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness", return_value=(False, "cold"))
@patch("app.engines.ict_breakout_monitor.analyze_explosion_event_ict")
@patch("app.engines.explosion_entry_guards.effective_local_base_move_pct", return_value=8.0)
@patch("app.engines.explosion_entry_guards.trustworthy_local_base_move", return_value=8.0)
def test_blocks_immature_pad_without_first_lift(
    _trust, _eff, _ict, _lift, _chart, _top, mock_settings,
):
    mock_settings.return_value = _settings()
    blocked, reason, _ = live_best_trade_entry_blocked(
        _candidate(pad=8.0),
        _snap(),
        AutoTraderState(),
        ranking={"grade": "S", "evidence": {"tier": "EXPLODING"}},
    )
    assert blocked
    assert "live_best_trades_immature_pad" in reason


@patch("app.engines.live_best_trades.get_settings")
def test_pauses_after_one_live_loss(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState(
        closedPaperTrades=[
            PaperTrade(
                id="l1",
                symbol="NIFTY",
                side=Side.PUT,
                strike=23950.0,
                entryPremium=37.0,
                currentPremium=29.0,
                lots=2,
                pnlInr=-1000.0,
                openedAt=datetime.now(IST),
                closedAt=datetime.now(IST),
                status="CLOSED",
                strategyType=StrategyType.EXPLOSIVE,
                entryContext={"executionMode": "LIVE"},
            )
        ]
    )
    assert live_session_loss_count(state) == 1
    with patch(
        "app.engines.top_moment_gate.top_moment_entry_allowed",
        return_value=(True, "ok", "EXPLODING"),
    ), patch(
        "app.engines.spot_direction.side_aligned_with_chart",
        return_value=True,
    ), patch(
        "app.engines.ict_breakout_monitor.first_lift_entry_readiness",
        return_value=(True, "first_lift"),
    ), patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
    ), patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=18.0,
    ), patch(
        "app.engines.explosion_entry_guards.trustworthy_local_base_move",
        return_value=18.0,
    ):
        blocked, reason, _ = live_best_trade_entry_blocked(
            _candidate(),
            _snap(),
            state,
            ranking={"grade": "S", "evidence": {"tier": "EXPLODING"}},
        )
    assert blocked
    assert reason == "live_best_trades_session_loss_pause"


@patch("app.engines.live_best_trades.get_settings")
def test_live_early_fail_exit(mock_settings):
    mock_settings.return_value = _settings()
    trade = PaperTrade(
        id="x",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        entryPremium=78.0,
        currentPremium=74.0,
        lots=1,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=90),
        entryContext={"executionMode": "LIVE", "liveBestTradeGate": True},
    )
    reason = live_early_fail_exit_reason(
        trade,
        hold_seconds=90,
        best_points=0.0,
        pnl_points=-4.0,
        live_velocity_3s=0.0,
    )
    assert reason == "live_early_fail"
