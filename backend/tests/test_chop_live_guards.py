"""Live chop guards — immature base, premium fade, second leg, early exit, adoption."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chop_live_guards import (
    chop_live_early_fail_exit_reason,
    chop_live_entry_blocked,
    chop_live_guard_day_active,
    chop_second_same_side_leg_blocked,
    parse_broker_option_symbol,
    adopt_untracked_broker_legs,
)
from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import (
    AutoTraderState,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.chop_live_guards_enabled = True
    s.chop_live_block_immature_local_base = True
    s.chop_live_block_premium_5m_fade = True
    s.chop_live_premium_5m_fade_min_mom_pct = -0.12
    s.chop_live_second_leg_block_enabled = True
    s.chop_live_second_leg_cooldown_seconds = 900
    s.chop_live_early_fail_exit_enabled = True
    s.chop_live_early_fail_min_hold_seconds = 30
    s.chop_live_early_fail_max_hold_seconds = 180
    s.chop_live_early_fail_max_best_points = 0.5
    s.chop_live_early_fail_min_loss_points = 3.0
    s.chop_live_early_fail_max_velocity_3s = 0.0
    s.live_broker_reconciliation_enabled = True
    s.enable_live_trading = True
    s.explosion_immature_block_enabled = True
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_immature_min_session_move_pct = 28.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.explosion_local_base_trust_min_move_pct = 8.0
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _snap(regime=Regime.CHOP):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        regime=regime,
    )


def _state(day_mode="WORST_DAY"):
    return AutoTraderState(
        dailyStrategy={"dayMode": day_mode},
    )


def _candidate(side=Side.PUT, base_move=8.0):
    ict = SimpleNamespace(
        base_relative_move_pct=base_move,
        local_swing_base=True,
        flat_then_vertical=True,
        active=True,
        session_move_pct=base_move,
        base_armed=False,
        armed_base_launch=False,
        v_rip_ready=False,
        volume_awakening=True,
        displacement=False,
        reasons=[],
    )
    event = SimpleNamespace(
        tier="EXPLODING",
        daily_move_pct=base_move,
        peak_move_pct=base_move,
        explosion_score=240.0,
        velocity_3s=2.0,
        side=side,
    )
    return SimpleNamespace(
        mode="explosion",
        side=side,
        symbol="NIFTY",
        strike=24050.0,
        explosion_event=event,
        alert={"tier": "EXPLODING"},
        snap=_snap(),
    )


def test_parse_broker_option_symbol_variants():
    assert parse_broker_option_symbol("NIFTY 24050 PE") == ("NIFTY", 24050.0, Side.PUT)
    assert parse_broker_option_symbol("NIFTY24500CE") == ("NIFTY", 24500.0, Side.CALL)


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.bullish_local_base.bullish_local_base_prediction")
def test_chop_live_blocks_immature_local_base(mock_bullish, mock_imm_settings, mock_settings):
    mock_settings.return_value = _settings()
    mock_imm_settings.return_value = _settings()
    mock_bullish.return_value = {"active": False}

    blocked, reason, _ = chop_live_entry_blocked(
        _candidate(base_move=8.0),
        _snap(),
        _state(),
        snapshots={"NIFTY": _snap()},
    )
    assert blocked
    assert "chop_live_immature" in reason


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.bullish_local_base.bullish_local_base_prediction")
def test_chop_live_blocks_premium_5m_fade(mock_bullish, mock_imm_settings, mock_settings):
    mock_settings.return_value = _settings()
    mock_imm_settings.return_value = _settings()
    mock_bullish.return_value = {"active": False}

    with patch(
        "app.engines.explosion_entry_guards.immature_explosion_blocked",
        return_value=(False, ""),
    ):
        blocked, reason, _ = chop_live_entry_blocked(
            _candidate(base_move=20.0),
            _snap(),
            _state(),
            snapshots={"NIFTY": _snap()},
            chart_meta={
                "premiumChart": {
                    "momentum5Pct": -0.25,
                    "direction": "BEARISH",
                }
            },
        )
    assert blocked
    assert reason == "chop_live_premium_5m_fade"


@patch("app.engines.chop_live_guards.get_settings")
def test_chop_second_same_side_leg_blocks_open_put(mock_settings):
    mock_settings.return_value = _settings()
    state = _state()
    state.openPaperTrades = [
        PaperTrade(
            id="open1",
            symbol="NIFTY",
            side=Side.PUT,
            strike=23950.0,
            entryPremium=37.5,
            currentPremium=32.0,
            lots=2,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            status="OPEN",
        )
    ]
    blocked, reason, _ = chop_second_same_side_leg_blocked(
        _candidate(),
        state,
        _snap(),
        snapshots={"NIFTY": _snap()},
    )
    assert blocked
    assert reason == "chop_live_second_same_side_open"


@patch("app.engines.chop_live_guards.get_settings")
def test_chop_live_early_fail_exits_despite_hold_to_sl(mock_settings):
    mock_settings.return_value = _settings()
    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        entryPremium=78.8,
        currentPremium=74.0,
        lots=1,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=90),
        bestPnlPoints=0.0,
        entryContext={"chopLiveGuard": True, "exitPlan": {"stopPoints": 8.0}},
    )
    reason = chop_live_early_fail_exit_reason(
        trade,
        hold_seconds=90,
        best_points=0.0,
        pnl_points=-4.8,
        live_velocity_3s=-0.5,
    )
    assert reason == "chop_live_early_fail"


def test_evaluate_explosion_exit_chop_early_fail_with_structural_hold():
    from app.config import get_settings

    s = get_settings()
    trade = PaperTrade(
        id="live-chop",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        entryPremium=78.8,
        currentPremium=73.0,
        lots=1,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=90),
        bestPnlPoints=0.0,
        entryContext={
            "chopLiveGuard": True,
            "exitPlan": {"stopPoints": 8.0, "adaptiveStop": True},
        },
    )
    with (
        patch.object(s, "enable_live_trading", True),
        patch.object(s, "live_hold_to_structural_sl", True),
        patch.object(s, "chop_live_early_fail_exit_enabled", True),
        patch.object(s, "chop_live_early_fail_min_hold_seconds", 30),
        patch.object(s, "chop_live_early_fail_max_hold_seconds", 180),
        patch.object(s, "chop_live_early_fail_max_best_points", 0.5),
        patch.object(s, "chop_live_early_fail_min_loss_points", 3.0),
        patch.object(s, "chop_live_early_fail_max_velocity_3s", 0.0),
        patch.object(s, "explosion_peak_fade_lock_enabled", False),
        patch.object(s, "explosion_peak_capture_enabled", False),
        patch.object(s, "explosion_no_progress_enabled", False),
    ):
        reason, _ = evaluate_explosion_exit(trade, 73.0, "EXPLODING", 65, live_velocity_3s=-0.5)
    assert reason == "chop_live_early_fail"


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.services.trade_store.record_trade_opened")
def test_adopt_untracked_broker_leg(mock_record, mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState(openPaperTrades=[])
    client = AsyncMock()
    client.get_positions.return_value = [
        {
            "instrument_token": "NSE_FO|NIFTY24050PE",
            "trading_symbol": "NIFTY 24050 PE",
            "quantity": 65,
            "average_price": 78.8,
            "last_price": 67.5,
        }
    ]
    snapshots = {"NIFTY": _snap()}
    adopted = asyncio.run(adopt_untracked_broker_legs(state, client, snapshots))
    assert len(adopted) == 1
    assert len(state.openPaperTrades) == 1
    ctx = state.openPaperTrades[0].entryContext or {}
    assert ctx.get("brokerAdopted") is True
    assert ctx.get("executionMode") == "LIVE"
    mock_record.assert_called_once()


def test_chop_live_guard_day_active_on_worst_day_mode():
    assert chop_live_guard_day_active(_state(), _snap()) is True
