"""Aug6 78800 PE entry guards — counter-trend, trap soft-cap, flip velocity, worst-day elite."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import cap_fake_explosion_trap_lots
from app.engines.session_mode_feedback import cap_opposite_side_flip_after_win
from app.engines.spot_direction import chart_blocks_side, hard_counter_trend_chart
from app.engines.worst_day_guard import worst_day_allows_candidate
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def test_hard_counter_trend_put_bullish():
    chart = SpotChart(direction="BULLISH", momentum5Pct=0.04, trendStrength=70)
    assert hard_counter_trend_chart(Side.PUT, chart) is True
    assert hard_counter_trend_chart(Side.CALL, chart) is False


@patch("app.engines.spot_direction.get_settings")
def test_aug6_put_blocked_on_bullish_chart(mock_settings):
    s = MagicMock()
    s.chart_alignment_enabled = True
    s.chart_live_direction_hard_block = True
    s.chart_counter_trend_bypass_block_enabled = True
    s.chart_min_trend_strength = 25.0
    s.chart_min_momentum_pct = 0.04
    s.chart_override_min_score = 75
    mock_settings.return_value = s
    chart = SpotChart(
        direction="BULLISH", momentum5Pct=0.042, momentum15Pct=0.081, trendStrength=77.7,
    )
    blocked, reason = chart_blocks_side(
        Side.PUT, chart, trade_score=102.0,
        expiry_explosion_bypass=True,
        premium_led_bypass=True,
        breadth_aligned_bypass=True,
    )
    assert blocked
    assert "bullish_no_puts" in reason


def test_aug6_trap_soft_cap_not_restored():
    meta = {
        "fakeExplosionTrap": True,
        "action": "cut_size",
        "lotCap": 6,
        "chopRegime": True,
        "eliteHot": True,
        "conflictFlags": ["chop_regime", "midday_chop", "elite_hot"],
        "conflictCount": 3,
    }
    with patch("app.engines.explosion_entry_guards.get_settings") as gs:
        s = MagicMock()
        s.fake_explosion_trap_honor_soft_cap_on_chop = True
        gs.return_value = s
        assert cap_fake_explosion_trap_lots(27, meta, bypass_soft_cap=True) == 6


def test_aug6_weak_flip_blocked():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="w", symbol="SENSEX", side=Side.CALL, strike=78700.0,
            entryPremium=380.0, currentPremium=430.0, lots=25,
            strategyType=StrategyType.EXPLOSIVE,
            openedAt=datetime.now(IST) - timedelta(minutes=40),
            closedAt=datetime.now(IST) - timedelta(minutes=30),
            pnlInr=24130.0,
        )
    ]
    lots, meta = cap_opposite_side_flip_after_win(
        27, state, symbol="SENSEX", side=Side.PUT, velocity_3s=0.54,
    )
    assert lots == 0
    assert meta["blocked"] is True


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
@patch("app.engines.elite_never_block.elite_never_block_active", return_value=True)
def test_worst_day_elite_bypass_denied_counter_chart(mock_enb, mock_policy):
    from app.engines.explosion_detector import ExplosionEvent

    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.CHOP,
        spot=78786.0,
        atmStrike=78800.0,
        tradeQualityScore=50,
        breadth=Breadth(bias="BEARISH", score=55, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.04, trendStrength=77),
    )
    event = ExplosionEvent(
        symbol="SENSEX", side=Side.PUT, strike=78800, premium=346,
        velocity_3s=0.54, velocity_9s=1.0, velocity_15s=1.0,
        volume_surge=2.5, explosion_score=46.7, tier="ELITE", reason="t",
    )
    cand = MagicMock()
    cand.mode = "explosion"
    cand.tier = "ELITE"
    cand.score = 102.0
    cand.symbol = "SENSEX"
    cand.side = Side.PUT
    cand.snap = snap
    cand.explosion_event = event
    cand.alert = None

    ok, reason, meta = worst_day_allows_candidate(cand, AutoTraderState(), {"SENSEX": snap})
    # Elite bypass denied for PUT into BULLISH — must not short-circuit as elite_never_block.
    assert meta.get("worstDayBypass") != "elite_never_block"
    assert meta.get("eliteNeverBlockDenied") == "elite_bypass_chart_misaligned"
    assert ok is False
