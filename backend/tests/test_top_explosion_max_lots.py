"""Jul29 SENSEX 77500 CE — ELITE/EXPLODING take capital max lots on first take."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_confidence import is_top_explosion_max_lots_entry
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.top_explosion_force_max_lots_enabled = True
    s.top_explosion_force_max_tiers_csv = "ELITE,EXPLODING"
    s.top_explosion_force_max_min_chart_confidence = 55.0
    s.top_explosion_force_max_require_aligned = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(direction="BULLISH", breadth="BULLISH", regime=Regime.RANGE_BOUND):
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=regime,
        spot=77600.0,
        atmStrike=77600.0,
        tradeQualityScore=57,
        breadth=Breadth(bias=breadth, score=82, aligned=True),
        spotChart=SpotChart(
            direction=direction, momentum5Pct=0.15, momentum15Pct=0.2,
            trendStrength=70, orPosition="ABOVE", emaBias=direction,
            candleBias=direction, macdBias=direction, rsi=62, spot=77600.0,
        ),
    )


@patch("app.engines.explosion_confidence.get_settings")
def test_jul29_elite_low_score_still_max_lots(mock_s):
    """Trade #8 profile: ELITE 47.8 / move 25% — missed HC & elevated, must still qualify."""
    mock_s.return_value = _settings()
    assert is_top_explosion_max_lots_entry(
        side=Side.CALL,
        snap=_snap(),
        tier="ELITE",
        chart_confidence=91.4,
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_exploding_tier_qualifies(mock_s):
    mock_s.return_value = _settings()
    assert is_top_explosion_max_lots_entry(
        side=Side.CALL,
        snap=_snap(),
        tier="EXPLODING",
        chart_confidence=70.0,
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_building_does_not_qualify(mock_s):
    mock_s.return_value = _settings()
    assert is_top_explosion_max_lots_entry(
        side=Side.CALL,
        snap=_snap(),
        tier="BUILDING",
        chart_confidence=91.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_low_chart_conf(mock_s):
    mock_s.return_value = _settings()
    assert is_top_explosion_max_lots_entry(
        side=Side.CALL,
        snap=_snap(),
        tier="ELITE",
        chart_confidence=40.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_misaligned(mock_s):
    mock_s.return_value = _settings()
    assert is_top_explosion_max_lots_entry(
        side=Side.CALL,
        snap=_snap(direction="BEARISH", breadth="BEARISH"),
        tier="ELITE",
        chart_confidence=91.0,
    ) is False
