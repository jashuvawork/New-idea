"""Guards derived from Jul 7 trade review — cheap premium lots, counter-breadth, scalp blocks."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import cap_explosion_lots, check_explosion_entry, expiry_session_lot_cap
from app.engines.explosion_detector import ExplosionEvent
from app.engines.simple_profit import check_entry_gate
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _expiry_snap(**kwargs) -> SymbolSnapshot:
    base = dict(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-07",
        spot=24480.0,
        tradeQualityScore=37.6,
        psychology={"label": "CAUTION"},
        breadth=Breadth(bias="BULLISH", score=55, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05),
    )
    base.update(kwargs)
    return SymbolSnapshot(**base)


@patch("app.engines.explosion_profit.get_settings")
def test_cheap_premium_explosion_lot_cap(mock_settings):
    s = MagicMock()
    s.explosion_high_premium_threshold_inr = 90.0
    s.explosion_high_premium_lot_cap = 10
    s.expiry_cheap_premium_threshold_inr = 55.0
    s.expiry_cheap_premium_lot_cap = 20
    mock_settings.return_value = s
    assert cap_explosion_lots(75, 28.9) == 20
    assert cap_explosion_lots(16, 75.0) == 16


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
def test_expiry_session_lot_cap_low_tqs(mock_expiry, mock_settings):
    s = MagicMock()
    s.expiry_day_guards_enabled = True
    s.expiry_cheap_premium_threshold_inr = 55.0
    s.expiry_cheap_premium_lot_cap = 20
    s.expiry_low_tqs_lot_cap_tqs = 40.0
    s.expiry_low_tqs_lot_cap = 15
    mock_settings.return_value = s
    snaps = {"NIFTY": _expiry_snap()}
    assert expiry_session_lot_cap(56, 27.0, 34.0, snaps) == 15


@patch("app.engines.simple_profit.get_settings")
def test_expiry_scalp_blocks_caution_psychology(mock_settings):
    s = MagicMock()
    s.aggressive_lot_sizing = True
    s.aggressive_min_tqs = 35
    s.enhanced_velocity_threshold = 1.2
    s.midday_chop_block_scalps = True
    s.neutral_breadth_min_score = 55
    s.counter_breadth_min_score = 70
    s.premium_led_counter_breadth_min_score = 48
    mock_settings.return_value = s
    snap = _expiry_snap()
    trade = SuggestedTrade(
        id="t2", symbol="NIFTY", side=Side.CALL, strike=24500.0, lastPremium=28.9,
        tqs=37.6, confidence=55.0,
    )
    with patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True):
        ok, reason = check_entry_gate(
            trade, snap.breadth, 37.6, 1.5, False, snap=snap,
        )
    assert not ok
    assert reason == "expiry_psychology_block_caution"


@patch("app.engines.explosion_profit.get_settings")
def test_expiry_counter_breadth_requires_elite(mock_settings):
    s = MagicMock()
    s.aggressive_min_explosion_score = 45
    s.expiry_counter_breadth_elite_only = True
    s.expiry_min_rank_score = 62.0
    mock_settings.return_value = s
    snap = _expiry_snap(symbol="SENSEX", tradeQualityScore=33.5)
    event = ExplosionEvent(
        symbol="SENSEX", side=Side.CALL, strike=78700, premium=225.6,
        velocity_3s=2.5, velocity_9s=3.0, velocity_15s=3.5,
        volume_surge=1.6, explosion_score=55, tier="EXPLODING", reason="t",
    )
    trade = SuggestedTrade(
        id="t1", symbol="SENSEX", side=Side.CALL, strike=78700, lastPremium=225.6, tqs=33.5,
    )
    breadth = Breadth(bias="BEARISH", score=42, aligned=False)
    with patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True):
        with patch("app.engines.chop_day_guards.neutral_breadth_blocks_entry", return_value=(False, "ok")):
            with patch("app.engines.spot_direction.chart_blocks_side", return_value=(False, "ok")):
                ok, reason = check_explosion_entry(event, trade, breadth, False, snap=snap)
    assert not ok
    assert reason in (
        "expiry_counter_breadth_elite_only",
        "explosion_call_vs_bearish_breadth",
        "hard_block_call_vs_bearish_breadth",
    )
