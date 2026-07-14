"""ICT / FVG breakout monitor — flat-then-vertical premium rip detection."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent, _history, _record, _strike_key, event_to_dict
from app.engines.ict_breakout_monitor import (
    ICTBreakoutSignal,
    analyze_ict_breakout,
    analyze_explosion_event_ict,
    good_day_ict_capture_active,
    ict_explosion_rank_bonus,
    ict_no_progress_seconds,
    ict_trail_arm_multiplier,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 12.0
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_displacement_min_velocity_3s = 3.0
    s.ict_vertical_min_session_move_pct = 80.0
    s.ict_mega_rip_min_session_move_pct = 200.0
    s.ict_breakout_min_score = 28.0
    s.ict_fvg_score_bonus = 14.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_mega_rip_score_bonus = 22.0
    s.ict_max_rank_bonus = 30.0
    s.ict_good_day_capture_enabled = True
    s.ict_good_day_min_score = 35.0
    s.ict_good_day_rank_bonus = 18.0
    s.ict_mega_rip_rank_bonus = 25.0
    s.ict_breakout_no_progress_seconds = 360
    s.ict_mega_rip_no_progress_seconds = 600
    s.ict_breakout_trail_arm_multiplier = 1.5
    s.ict_mega_rip_trail_arm_multiplier = 2.2
    s.explosion_volume_awaken_min = 25000
    s.explosion_no_progress_seconds = 150
    return s


def _seed_flat_then_rip_history(symbol: str, strike: float, side: Side) -> None:
    """Flat base ~10 then vertical rip to ~90 — mimics 8→393 style."""
    base = datetime.now(IST) - timedelta(seconds=60)
    flat_premiums = [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.3, 9.7]
    for i, prem in enumerate(flat_premiums):
        ts = base + timedelta(seconds=i * 3)
        _history.setdefault(symbol, {})[_strike_key(strike, side)] = _history.get(symbol, {}).get(
            _strike_key(strike, side), __import__("collections").deque(maxlen=40),
        )
        _history[symbol][_strike_key(strike, side)].append((ts, prem, 5000))
    rip_premiums = [12.0, 25.0, 55.0, 90.0]
    for j, prem in enumerate(rip_premiums):
        ts = base + timedelta(seconds=(len(flat_premiums) + j) * 3)
        _history[symbol][_strike_key(strike, side)].append((ts, prem, 250000))


@patch("app.engines.ict_breakout_monitor.get_settings", side_effect=lambda: _settings())
def test_flat_then_vertical_detected(mock_settings):
    _seed_flat_then_rip_history("NIFTY", 23850, Side.PUT)
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850,
        premium=90.0,
        session_move_pct=800.0,
        velocity_3s=5.0,
        volume=300000,
        tier="ELITE",
        reason="volAwaken×250k",
    )
    assert ict.active
    assert ict.flat_then_vertical or ict.premium_fvg
    assert ict.mega_rip
    assert ict.score >= 28


@patch("app.engines.ict_breakout_monitor.get_settings", side_effect=lambda: _settings())
def test_premium_fvg_detected(mock_settings):
    symbol, strike, side = "SENSEX", 76500, Side.PUT
    base = datetime.now(IST) - timedelta(seconds=20)
    for i, prem in enumerate([8.0, 8.5, 15.0, 35.0]):
        ts = base + timedelta(seconds=i * 3)
        _record(symbol, strike, side, prem, 10000 * (i + 1))
    ict = analyze_ict_breakout(
        symbol=symbol,
        side=side,
        strike=strike,
        premium=35.0,
        session_move_pct=337.0,
        velocity_3s=4.5,
        volume=50000,
        tier="EXPLODING",
    )
    assert ict.premium_fvg or ict.active


@patch("app.engines.ict_breakout_monitor.get_settings", side_effect=lambda: _settings())
def test_event_to_dict_includes_ict(mock_settings):
    _seed_flat_then_rip_history("NIFTY", 23850, Side.PUT)
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850,
        premium=90.0,
        velocity_3s=5.0,
        velocity_9s=8.0,
        velocity_15s=12.0,
        volume_surge=3.0,
        explosion_score=72.0,
        tier="ELITE",
        reason="volAwaken×250k",
        daily_move_pct=800.0,
        peak_move_pct=800.0,
    )
    d = event_to_dict(event)
    assert "ictBreakout" in d
    assert "ictPattern" in d
    assert d.get("ictMegaRip") is True
    assert d["tradeable"] is True


def test_ict_rank_bonus_aggressive():
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=45.0,
        reasons=["flat_then_vertical"],
        flat_then_vertical=True,
        mega_rip=False,
    )
    bonus = ict_explosion_rank_bonus(ict, "AGGRESSIVE")
    assert bonus >= 18


def test_ict_exit_helpers():
    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850,
        lots=10,
        entryPremium=50.0,
        openedAt=datetime.now(IST),
        entryContext={"ictBreakout": True, "ictMegaRip": True, "goodDayIctCapture": True},
    )
    with patch("app.engines.ict_breakout_monitor.get_settings", side_effect=lambda: _settings()):
        assert ict_no_progress_seconds(trade) == 600
        assert ict_trail_arm_multiplier(trade) == 2.2


@patch("app.engines.ict_breakout_monitor.get_settings", side_effect=lambda: _settings())
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("AGGRESSIVE", {}))
def test_good_day_ict_capture_active(mock_mode, mock_settings):
    from datetime import datetime

    from app.models.schemas import MarketPhase

    state = AutoTraderState()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55,
    )
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850,
        premium=90.0,
        velocity_3s=5.0,
        velocity_9s=8.0,
        velocity_15s=12.0,
        volume_surge=3.0,
        explosion_score=72.0,
        tier="ELITE",
        reason="volAwaken",
        daily_move_pct=800.0,
    )
    ict = ICTBreakoutSignal(
        active=True,
        pattern="mega_rip",
        score=50.0,
        reasons=["mega_rip"],
        mega_rip=True,
        flat_then_vertical=True,
        session_move_pct=800.0,
    )
    active, meta = good_day_ict_capture_active(
        state, {"NIFTY": snap}, event=event, ict=ict,
    )
    assert active
    assert meta.get("maxProfitCapture") is True
