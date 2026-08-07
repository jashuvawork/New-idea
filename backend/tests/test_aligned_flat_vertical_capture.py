"""Catch flat→vertical at the base — only when chart aligns — hold toward max TP."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.elite_never_block import top_explosion_must_take_active
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import (
    _ict_flat_vertical_entry_ok,
    _near_base_top_runner,
    check_explosion_entry,
)
from app.engines.premium_filter import premium_in_band
from app.engines.trade_selector import _building_aligned_ict_alert_ok
from app.models.schemas import (
    Breadth,
    MarketPhase,
    PaperTrade,
    Side,
    SpotChart,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(direction: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77250.0,
        atmStrike=77200.0,
        tradeQualityScore=55,
        breadth=Breadth(bias=direction, score=60, aligned=True),
        spotChart=SpotChart(
            direction=direction, momentum5Pct=-0.08 if direction == "BEARISH" else 0.08,
            trendStrength=55.0,
        ),
    )


def _event(tier: str = "BUILDING", side: Side = Side.PUT) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=side,
        strike=77200.0,
        premium=200.0,
        velocity_3s=3.2,
        velocity_9s=4.0,
        velocity_15s=3.5,
        volume_surge=3.5,
        explosion_score=70.0,
        tier=tier,
        reason="flat_then_vertical",
        daily_move_pct=18.0,
        peak_move_pct=18.0,
    )


def test_building_aligned_ict_alert_allows_put_on_bearish():
    alert = {
        "side": "PUT",
        "tier": "BUILDING",
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictScore": 40.0,
        "explosionScore": 70.0,
        "velocity3s": 3.0,
        "ictVolumeAwakening": True,
    }
    assert _building_aligned_ict_alert_ok(alert, _snap("BEARISH"), "BUILDING") is True
    assert _building_aligned_ict_alert_ok(alert, _snap("BULLISH"), "BUILDING") is False


def test_building_aligned_rejects_cold_aug7_style():
    """Aug7 BUILDING score 56 / v3 1.7 must not pass elite-build gate."""
    alert = {
        "side": "PUT",
        "tier": "BUILDING",
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictScore": 31.7,
        "explosionScore": 56.2,
        "velocity3s": 1.69,
        "ictVolumeAwakening": True,
    }
    assert _building_aligned_ict_alert_ok(alert, _snap("BEARISH"), "BUILDING") is False


def test_ict_flat_vertical_entry_requires_chart_align():
    with patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict"
    ) as mock_ict:
        ict = MagicMock()
        ict.active = True
        ict.flat_then_vertical = True
        ict.volume_awakening = True
        ict.displacement = False
        ict.premium_fvg = False
        ict.score = 40.0
        mock_ict.return_value = ict
        assert _ict_flat_vertical_entry_ok(_event(), _snap("BEARISH")) is True
        assert _ict_flat_vertical_entry_ok(_event(), _snap("BULLISH")) is False


@patch("app.engines.explosion_profit.get_settings")
def test_ict_flat_vertical_building_requires_elite_bars(mock_settings):
    s = MagicMock()
    s.explosion_building_aligned_ict_enabled = True
    s.explosion_building_elite_min_score = 62.0
    s.explosion_building_elite_min_velocity_3s = 2.5
    s.explosion_building_elite_min_ict_score = 35.0
    mock_settings.return_value = s
    with patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict"
    ) as mock_ict:
        ict = MagicMock()
        ict.active = True
        ict.flat_then_vertical = True
        ict.volume_awakening = True
        ict.displacement = False
        ict.premium_fvg = False
        ict.score = 40.0
        mock_ict.return_value = ict
        cold = _event(tier="BUILDING")
        cold.explosion_score = 56.2
        cold.velocity_3s = 1.69
        assert _ict_flat_vertical_entry_ok(cold, _snap("BEARISH")) is False
        hot = _event(tier="BUILDING")
        hot.explosion_score = 70.0
        hot.velocity_3s = 3.2
        assert _ict_flat_vertical_entry_ok(hot, _snap("BEARISH")) is True


@patch("app.engines.explosion_profit.get_settings")
def test_check_explosion_entry_requires_chart_align(mock_settings):
    s = MagicMock()
    s.explosion_require_chart_align_enabled = True
    s.open_premium_min_move_pct = 25.0
    mock_settings.return_value = s
    # Minimal stubs so we fail on align before deeper gates.
    trade = SuggestedTrade(
        id="t1", symbol="SENSEX", side=Side.PUT, strike=77200.0,
        lastPremium=200.0, tqs=55.0,
        strategyType=StrategyType.EXPLOSIVE, confidence=80.0,
    )
    ok, reason = check_explosion_entry(
        _event(tier="ELITE"), trade, Breadth(bias="BEARISH", score=60, aligned=True),
        False, chart=_snap("BULLISH").spotChart, snap=_snap("BULLISH"),
    )
    assert ok is False
    assert reason == "explosion_requires_chart_align"


@patch("app.engines.elite_never_block.get_settings")
def test_must_take_requires_chart_align(mock_settings):
    s = MagicMock()
    s.explosion_top_must_take_enabled = True
    s.explosion_top_must_take_tiers_csv = "ELITE,EXPLODING"
    s.explosion_top_must_take_min_score = 62.0
    s.explosion_top_must_take_require_atm_itm = True
    s.explosion_top_must_take_require_chart_align = True
    s.min_option_premium_inr = 18.0
    mock_settings.return_value = s
    snap_ok = _snap("BEARISH")
    snap_bad = _snap("BULLISH")
    event = _event(tier="ELITE")
    event.explosion_score = 80.0
    with patch("app.engines.elite_never_block._in_near_base_window", return_value=True):
        with patch("app.engines.elite_never_block._is_atm_or_itm", return_value=True):
            assert top_explosion_must_take_active(
                event=event, snap=snap_ok, tier="ELITE",
            ) is True
            assert top_explosion_must_take_active(
                event=event, snap=snap_bad, tier="ELITE",
            ) is False


def test_near_base_hold_wider_for_ict_max_profit():
    """ICT flat→vertical at 35% off base still holds for max TP (not soft-locked)."""
    trade = PaperTrade(
        id="t", symbol="SENSEX", side=Side.PUT, strike=77200.0,
        entryPremium=220.0, currentPremium=240.0, lots=10,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=90),
        bestPnlPoints=12.0,
        entryContext={
            "localBaseBaseRelPct": 35.0,
            "explosionTier": "ELITE",
            "ictFlatThenVertical": True,
            "maxProfitCapture": True,
        },
    )
    assert _near_base_top_runner(trade) is True
    # Without ICT flags, 35% is mid-leg — no hold.
    trade.entryContext = {"localBaseBaseRelPct": 35.0, "explosionTier": "ELITE"}
    assert _near_base_top_runner(trade) is False


def test_premium_band_allows_mid_rip_ict():
    assert premium_in_band(445.0, mode="explosion", peak_move_pct=120.0) is True
    assert premium_in_band(720.0, mode="explosion", peak_move_pct=150.0) is True
