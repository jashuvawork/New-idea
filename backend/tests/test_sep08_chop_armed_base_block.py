"""Sep08 NIFTY 23650 PE — chop+elite armed-base below base window must not enter."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.chop_live_guards import (
    chop_live_early_fail_exit_reason,
    chop_live_entry_blocked,
)
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import detect_fake_explosion_trap
from app.engines.explosion_profit import _should_skip_elite_runner_early_exits
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
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
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.explosion_early_window_max_move_pct = 55.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.explosion_local_base_recent_window_enabled = False
    s.explosion_local_base_chase_max_move_pct = 65.0
    s.fake_explosion_trap_max_premium_mom_pct = 0.15
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_block_worst_midday_chop = True
    s.fake_explosion_trap_block_chop_elite_armed_base = True
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.fake_explosion_trap_post_win_lot_cap = 8
    s.fake_explosion_trap_post_win_max_pnl_inr = 3000.0
    s.fake_explosion_trap_post_win_lookback = 1
    s.fake_explosion_trap_post_win_velocity_block_enabled = True
    s.fake_explosion_trap_post_win_min_velocity_3s = 0.0
    s.fake_explosion_trap_post_win_midday_min_velocity_3s = 1.0
    s.fake_explosion_trap_post_win_armed_base_bypass_enabled = False
    s.fake_explosion_trap_post_win_afternoon_block_enabled = True
    s.fake_explosion_trap_post_win_expiry_only = True
    s.fake_explosion_trap_post_win_require_top_confidence = True
    s.fake_explosion_trap_post_win_hc_min_velocity_3s = 2.0
    s.fake_explosion_trap_psychology_escalate = True
    s.fake_explosion_trap_skip_soft_cut_base_window = True
    s.fake_explosion_trap_skip_soft_cut_near_otm = True
    s.moneyness_local_base_max_otm_steps = 3
    s.fake_explosion_trap_midday_require_structure = True
    s.moneyness_explosion_prefer = "ATM"
    s.trade_moneyness_mode = "AUTO"
    s.midday_chop_start_hour = 11
    s.midday_chop_start_minute = 30
    s.midday_chop_end_hour = 13
    s.midday_chop_end_minute = 30
    s.nifty_strike_step = 50
    s.sensex_strike_step = 100
    s.chop_live_guards_enabled = True
    s.chop_live_block_armed_base_launch = True
    s.chop_live_armed_base_max_local_pad_pct = 20.0
    s.chop_live_block_immature_local_base = True
    s.chop_live_block_faded_rip = True
    s.chop_live_block_extended_chase = True
    s.chop_live_extended_chase_min_session_move_pct = 28.0
    s.chop_live_min_trusted_local_base_pct = 15.0
    s.chop_live_block_premium_5m_fade = False
    s.chop_live_hard_block_worst_day = False
    s.enable_live_trading = False
    s.chop_live_trap_early_fail_max_best_points = 2.0
    s.chop_live_trap_early_fail_max_hold_seconds = 600
    s.chop_live_early_fail_min_hold_seconds = 30
    s.chop_live_early_fail_max_hold_seconds = 180
    s.chop_live_early_fail_max_best_points = 0.5
    s.chop_live_early_fail_min_loss_points = 3.0
    s.chop_live_early_fail_max_velocity_3s = 0.0
    s.chop_live_early_fail_exit_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _sep08_ict() -> ICTBreakoutSignal:
    return ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=80.0,
        reasons=["armed_base_launch_29.8_7.7%"],
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=True,
        session_move_pct=7.7,
        base_relative_move_pct=7.7,
        base_premium=29.75,
        local_swing_base=True,
        armed_base_launch=True,
        base_armed=True,
    )


def _event(side=Side.PUT, daily=7.73, strike=23650.0) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=side,
        strike=strike,
        premium=33.55,
        velocity_3s=2.72,
        velocity_9s=2.4,
        velocity_15s=2.0,
        volume_surge=2.5,
        explosion_score=92.3,
        tier="EXPLODING",
        reason="armed_base_launch",
        daily_move_pct=daily,
        peak_move_pct=daily,
    )


def _snap(regime=Regime.CHOP) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=regime,
        spot=23671.0,
        atmStrike=23650.0,
        tradeQualityScore=71,
        spotChart=SpotChart(
            direction="BEARISH",
            timeframe="5m",
            barCount=9,
            momentum5Pct=-0.042,
            momentum15Pct=-0.027,
            trendStrength=17.0,
            emaBias="NEUTRAL",
            candleBias="BEARISH",
            orPosition="BELOW",
            rsi=21.0,
            macdBias="BEARISH",
        ),
    )


def _candidate(event: ExplosionEvent, snap: SymbolSnapshot) -> MagicMock:
    cand = MagicMock()
    cand.mode = "explosion"
    cand.side = event.side
    cand.strike = event.strike
    cand.score = 249.2
    cand.tier = event.tier
    cand.explosion_event = event
    cand.snap = snap
    cand.pretrade_meta = {}
    return cand


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_blocks_chop_elite_armed_base_below_base_window(
    mock_money_settings, mock_settings, side,
):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap()
    event = _event(side=side)
    cand = _candidate(event, snap)
    ict = _sep08_ict()
    ict.base_relative_move_pct = 7.7

    blocked, reason, meta = detect_fake_explosion_trap(cand, snap, ict=ict)

    assert blocked is True
    assert reason == "fake_explosion_trap_chop_elite_armed_base"
    assert meta.get("action") == "block"
    assert meta.get("chopEliteArmedBaseBlock") is True


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_chop_elite_without_armed_launch_still_soft_cut(mock_money_settings, mock_settings):
    """Non-armed chop+elite with structure remains soft-cut (Jul23-style base rips)."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap()
    snap.spotChart.orPosition = "ABOVE"
    event = _event(daily=18.0, strike=23650.0)
    cand = _candidate(event, snap)
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=80.0,
        reasons=["flat_then_vertical"],
        flat_then_vertical=True,
        volume_awakening=True,
        session_move_pct=18.0,
        base_relative_move_pct=18.0,
        armed_base_launch=False,
    )

    blocked, reason, meta = detect_fake_explosion_trap(cand, snap, ict=ict)

    assert blocked is False
    assert meta.get("action") == "cut_size"


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.chop_live_guards.get_settings")
@patch("app.engines.chop_live_guards.chop_live_guard_day_active", return_value=True)
@patch("app.engines.ict_breakout_monitor.analyze_explosion_event_ict")
def test_chop_live_blocks_shallow_armed_base(
    mock_ict, _day_active, mock_settings, side,
):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_ict.return_value = _sep08_ict()
    snap = _snap()
    event = _event(side=side)
    cand = _candidate(event, snap)
    state = AutoTraderState(dailyStrategy={"dayMode": "EXPIRY DAY"})

    blocked, reason, meta = chop_live_entry_blocked(cand, snap, state)

    assert blocked is True
    assert reason == "chop_live_armed_base_chop_day"
    assert meta.get("armedBaseChopBlock") is True


def test_trap_stamped_trade_allows_chop_early_fail_exit():
    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23650.0,
        entryPremium=33.55,
        currentPremium=26.0,
        lots=6,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        entryContext={
            "chopLiveGuard": True,
            "fakeExplosionTrap": True,
            "psychologyTrapOverride": True,
            "conflictFlags": ["chop_regime", "elite_hot"],
            "eliteRunnerExitBundle": True,
            "eliteAssessment": {"grade": "S", "eliteScore": 100.0},
        },
    )
    assert _should_skip_elite_runner_early_exits(trade) is False
    reason = chop_live_early_fail_exit_reason(
        trade,
        hold_seconds=420.0,
        best_points=1.45,
        pnl_points=-6.5,
        live_velocity_3s=-2.0,
    )
    assert reason == "chop_live_early_fail"


def test_trap_stamped_exit_uses_extended_hold_window():
    trade = SimpleNamespace(
        entryContext={
            "chopLiveGuard": True,
            "fakeExplosionTrap": True,
            "conflictFlags": ["chop_regime", "elite_hot"],
        }
    )
    with patch("app.engines.chop_live_guards.get_settings", return_value=_settings()):
        reason = chop_live_early_fail_exit_reason(
            trade,
            hold_seconds=420.0,
            best_points=1.45,
            pnl_points=-6.5,
            live_velocity_3s=-2.0,
        )
    assert reason == "chop_live_early_fail"
