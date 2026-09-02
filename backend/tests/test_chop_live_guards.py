"""Live chop guards — tightened blocks + adoption parser fixes."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chop_live_guards import (
    broker_adopted_trade_exit_blocked,
    chop_live_entry_blocked,
    chop_live_session_lift_allowed,
    parse_broker_option_symbol,
    reset_chop_live_adoption_cache,
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
    s.chop_live_disable_session_lift = True
    s.chop_live_hard_block_worst_day = True
    s.chop_live_block_faded_rip = True
    s.chop_live_block_extended_chase = True
    s.chop_live_extended_chase_min_session_move_pct = 28.0
    s.chop_live_min_trusted_local_base_pct = 15.0
    s.live_broker_reconciliation_enabled = True
    s.enable_live_trading = True
    s.explosion_immature_block_enabled = True
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_immature_min_session_move_pct = 28.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.explosion_faded_rip_caution_enabled = True
    s.explosion_faded_rip_min_peak_pct = 35.0
    s.explosion_faded_rip_max_live_velocity_3s = 0.5
    s.worst_day_breakout_min_velocity_3s = 2.0
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


def _candidate(side=Side.PUT, base_move=8.0, daily_move=30.0):
    ict = SimpleNamespace(
        base_relative_move_pct=base_move,
        local_swing_base=True,
        flat_then_vertical=True,
        active=True,
        session_move_pct=daily_move,
        base_armed=False,
        armed_base_launch=False,
        v_rip_ready=False,
        volume_awakening=True,
        displacement=False,
        reasons=[],
    )
    event = SimpleNamespace(
        tier="EXPLODING",
        daily_move_pct=daily_move,
        peak_move_pct=daily_move,
        explosion_score=240.0,
        velocity_3s=2.0,
        velocity_9s=1.0,
        side=side,
        symbol="NIFTY",
        strike=24050.0,
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


def test_parse_upstox_compact_symbol():
    assert parse_broker_option_symbol("NIFTY2690124050PE") == ("NIFTY", 24050.0, Side.PUT)
    assert parse_broker_option_symbol("NIFTY2690123950PE") == ("NIFTY", 23950.0, Side.PUT)
    assert parse_broker_option_symbol("NIFTY 24050 PE") == ("NIFTY", 24050.0, Side.PUT)
    assert parse_broker_option_symbol("NIFTY2690124050PE") != ("NIFTY", 2690124050.0, Side.PUT)


@patch("app.engines.chop_live_guards.get_settings")
def test_session_lift_disallowed_on_chop_live_day(mock_settings):
    mock_settings.return_value = _settings()
    assert chop_live_session_lift_allowed(_state(), _snap(), {"NIFTY": _snap()}) is False


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.engines.worst_day_guard.identify_worst_day")
def test_hard_block_worst_day_live(mock_worst, mock_settings):
    from app.engines.worst_day_guard import WorstDayVerdict

    mock_settings.return_value = _settings()
    mock_worst.return_value = WorstDayVerdict(True, 80.0, ["chop_regime"])

    blocked, reason, meta = chop_live_entry_blocked(
        _candidate(base_move=20.0, daily_move=35.0),
        _snap(),
        _state(),
        snapshots={"NIFTY": _snap()},
    )
    assert blocked
    assert reason == "chop_live_worst_day_hard_block"
    assert meta.get("worstDayHardBlock") is True


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.bullish_local_base.bullish_local_base_prediction")
def test_chop_live_blocks_immature_local_base(mock_bullish, mock_imm_settings, mock_settings):
    mock_settings.return_value = _settings(chop_live_hard_block_worst_day=False)
    mock_imm_settings.return_value = _settings()
    mock_bullish.return_value = {"active": False}

    with patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=8.0,
    ), patch(
        "app.engines.explosion_entry_guards.trustworthy_local_base_move",
        return_value=8.0,
    ), patch(
        "app.engines.worst_day_guard.identify_worst_day",
        return_value=__import__(
            "app.engines.worst_day_guard", fromlist=["WorstDayVerdict"]
        ).WorstDayVerdict(False, 0.0, []),
    ):
        blocked, reason, _ = chop_live_entry_blocked(
            _candidate(base_move=8.0),
            _snap(),
            _state(),
            snapshots={"NIFTY": _snap()},
        )
    assert blocked
    assert "chop_live_immature" in reason or "chop_live_extended_chase" in reason


@patch("app.engines.chop_live_guards.get_settings")
def test_broker_adopted_bad_row_blocks_profit_exit(mock_settings):
    mock_settings.return_value = _settings()
    trade = PaperTrade(
        id="bad",
        symbol="NIFTY",
        side=Side.PUT,
        strike=2690124050.0,
        entryPremium=0.0,
        currentPremium=64.0,
        lots=1,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        entryContext={"brokerAdopted": True},
    )
    assert broker_adopted_trade_exit_blocked(trade) is True


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.services.trade_store.record_trade_opened")
def test_adoption_dedupes_same_instrument_key(mock_record, mock_settings):
    mock_settings.return_value = _settings()
    reset_chop_live_adoption_cache()
    state = AutoTraderState(openPaperTrades=[])
    client = AsyncMock()
    row = {
        "instrument_token": "NSE_FO|46988",
        "trading_symbol": "NIFTY2690124050PE",
        "quantity": 65,
        "average_price": 78.8,
        "last_price": 67.5,
    }
    client.get_positions.return_value = [row, row]
    snapshots = {"NIFTY": _snap()}

    adopted = asyncio.run(adopt_untracked_broker_legs(state, client, snapshots))
    assert len(adopted) == 1
    assert len(state.openPaperTrades) == 1
    assert state.openPaperTrades[0].strike == 24050.0
