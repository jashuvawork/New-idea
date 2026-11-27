"""Nov27-style BEARISH DAY CE mid-pad chase — day-mode counter trap (CE/PE symmetric)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.day_mode_counter_trap import (
    counter_day_exec_post_spike_red_candle_blocked,
    counter_day_mode_side,
    day_mode_counter_side_trap_chopish,
)
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import detect_fake_explosion_trap
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.explosion_early_window_max_move_pct = 55.0
    s.explosion_local_base_chase_max_move_pct = 65.0
    s.fake_explosion_trap_block_chop_elite_armed_base = True
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_midday_require_structure = True
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_post_win_afternoon_block_enabled = True
    s.fake_explosion_trap_post_win_expiry_only = True
    s.fake_explosion_trap_post_win_velocity_block_enabled = True
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.chopish_regime_detection_enabled = True
    s.chopish_midday_union_enabled = True
    s.chopish_regime_mom5_max_pct = 0.25
    s.chopish_regime_strength_max = 45.0
    s.fake_trap_day_mode_counter_side_chopish_enabled = True
    s.fake_trap_day_mode_counter_side_min_pad_pct = 10.0
    s.counter_day_block_post_spike_red_candle_exec = True
    s.counter_day_post_spike_min_big_red_bars = 1
    s.counter_day_post_spike_min_drawdown_pct = 8.0
    s.counter_day_post_spike_min_spike_run_pct = 20.0
    s.premium_post_spike_dump_chart_bars = 24
    s.premium_post_spike_dump_big_body_mult = 1.1
    s.midday_chop_start_hour = 11
    s.midday_chop_start_minute = 30
    s.midday_chop_end_hour = 13
    s.midday_chop_end_minute = 30
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, breadth_bias: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.TREND_EXPANSION,
        breadth=Breadth(bias=breadth_bias, score=40.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            timeframe="5m",
            barCount=12,
            momentum5Pct=0.5,
            trendStrength=60.0,
        ),
    )


def test_counter_day_mode_side_ce_pe_symmetric():
    assert counter_day_mode_side("BEARISH DAY", "CALL")
    assert not counter_day_mode_side("BEARISH DAY", "PUT")
    assert counter_day_mode_side("BULLISH DAY", "PUT")
    assert not counter_day_mode_side("BULLISH DAY", "CALL")


def test_day_mode_counter_chopish_blocks_mid_pad_ce():
    state = AutoTraderState(dailyStrategy={"dayMode": "BEARISH DAY"})
    snap = _snap()
    chopish, meta = day_mode_counter_side_trap_chopish(
        Side.CALL, snap, state, local_pad=14.8, settings=_settings(),
    )
    assert chopish
    assert meta.get("dayModeCounterSideTrap")


def test_day_mode_counter_chopish_pe_mirror():
    state = AutoTraderState(dailyStrategy={"dayMode": "BULLISH DAY"})
    snap = _snap(breadth_bias="BULLISH")
    chopish, _ = day_mode_counter_side_trap_chopish(
        Side.PUT, snap, state, local_pad=12.0, settings=_settings(),
    )
    assert chopish


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.explosion_entry_guards._armed_base_launch_active", return_value=True)
@patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False)
@patch("app.engines.explosion_entry_guards._regime_chopish", return_value=False)
@patch("app.engines.explosion_entry_guards.effective_local_base_move_pct", return_value=14.8)
@patch("app.engines.moneyness.get_settings")
def test_fake_trap_chop_elite_armed_base_on_bearish_day_ce(
    mock_money_settings, _pad, _chop, _mid, _armed, mock_settings,
):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    state = AutoTraderState(dailyStrategy={"dayMode": "BEARISH DAY"})
    snap = _snap()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=25750.0,
        premium=232.0,
        velocity_3s=0.8,
        velocity_9s=0.6,
        velocity_15s=0.5,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="armed_base_launch",
        daily_move_pct=12.0,
        peak_move_pct=12.0,
    )
    cand = MagicMock()
    cand.mode = "explosion"
    cand.side = Side.CALL
    cand.symbol = "NIFTY"
    cand.strike = 25750.0
    cand.explosion_event = event
    cand.alert = {"localBaseMovePct": 14.8, "tier": "ELITE"}
    cand.tier = "ELITE"
    cand.score = 100.0
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap, state=state)
    assert blocked
    assert reason.startswith("fake_explosion_trap_")
    assert meta.get("dayModeCounterSideTrap")


def _make_candles_spike_dump(base: float, peak: float, ltp: float) -> list:
    candles = []
    p = base
    step = (peak - base) / 8
    for _i in range(8):
        o, c = p, p + step
        candles.append([0, o, max(o, c) + 2, min(o, c) - 1, c])
        p = c
    o_red, c_red = peak, peak * 0.75
    candles.append([0, o_red, o_red + 1, c_red - 2, c_red])
    o_b, c_b = c_red, ltp
    candles.append([0, o_b, max(o_b, ltp) + 1, min(o_b, ltp) - 1, c_b])
    return candles


def test_counter_day_exec_red_candle_trap():
    state = AutoTraderState(dailyStrategy={"dayMode": "BEARISH DAY"})
    snap = _snap()
    candles = _make_candles_spike_dump(80.0, 350.0, 232.0)
    blocked, reason, _meta = counter_day_exec_post_spike_red_candle_blocked(
        Side.CALL,
        snap,
        candles,
        232.0,
        state=state,
        local_pad=14.8,
        settings=_settings(),
    )
    assert blocked
    assert reason == "exec_counter_day_post_spike_red_candle_trap"