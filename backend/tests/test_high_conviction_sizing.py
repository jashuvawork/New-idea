"""High-conviction base rip → max lots + hold longer (Jul22 SENSEX 77200 PE)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_confidence import is_high_conviction_entry, trade_is_high_conviction
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.high_conviction_sizing_enabled = True
    s.high_conviction_min_score = 90.0
    s.high_conviction_min_chart_confidence = 85.0
    s.missed_explosion_promote_min_move_pct = 28.0
    s.missed_explosion_promote_max_move_pct = 55.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(direction="BEARISH", breadth="BEARISH"):
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.TREND_EXPANSION,
        spot=77200.0,
        atmStrike=77200.0,
        tradeQualityScore=60,
        breadth=Breadth(bias=breadth, score=40, aligned=True),
        spotChart=SpotChart(
            direction=direction, momentum5Pct=-0.25, momentum15Pct=-0.4,
            trendStrength=72, orPosition="BELOW", emaBias=direction,
            candleBias=direction, macdBias=direction, rsi=38, spot=77200.0,
        ),
    )


@patch("app.engines.explosion_confidence.get_settings")
def test_accepts_jul22_sensex_pe(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=32.0, chart_confidence=95.0,
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_low_score(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=80.0,
        move_pct=32.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_low_chart_conf(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=32.0, chart_confidence=70.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_extended_chase(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=90.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_wrong_side(mock_s):
    mock_s.return_value = _settings()
    # CALL on a bearish chart+breadth → not high conviction
    assert is_high_conviction_entry(
        side=Side.CALL, snap=_snap(direction="BEARISH", breadth="BEARISH"),
        tier="ELITE", score=100.0, move_pct=32.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_non_elite(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=100.0,
        move_pct=32.0, chart_confidence=95.0,
    ) is False


def test_trade_is_high_conviction_flag():
    t = MagicMock()
    t.entryContext = {"highConviction": True}
    assert trade_is_high_conviction(t) is True
    t.entryContext = {"highConviction": False}
    assert trade_is_high_conviction(t) is False
    t.entryContext = None
    assert trade_is_high_conviction(t) is False
