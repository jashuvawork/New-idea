"""FTV/V index candlestick pattern confirmation."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.ftv_candlestick_confirm import (
    alert_has_ftv_v_structure,
    aligned_candlestick_patterns,
    ftv_candlestick_chart_bypass,
    ftv_candlestick_index_aligned,
    ftv_candlestick_rank_bonus,
)
from app.models.schemas import ChartAnalysis, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.ftv_candlestick_confirm_enabled = True
    s.ftv_candlestick_min_pattern_strength = 68.0
    s.ftv_candlestick_require_ftv_structure = True
    s.ftv_candlestick_min_flat_vertical_quality = 50.0
    s.ftv_candlestick_chart_bypass_enabled = True
    s.ftv_candlestick_chart_bypass_min_score = 25.0
    s.ftv_candlestick_max_adverse_mom5_pct = 0.08
    s.ftv_candlestick_rank_bonus_enabled = True
    s.ftv_candlestick_rank_bonus_max = 10.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, direction: str = "BULLISH", mom5: float = 0.05) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24500.0,
        atmStrike=24500.0,
        tradeQualityScore=55,
        spotChart=SpotChart(
            direction=direction,
            timeframe="5m",
            barCount=40,
            momentum5Pct=mom5,
            momentum15Pct=mom5 * 0.8,
            trendStrength=65.0,
            emaBias=direction,
            candleBias=direction,
            recommendedSide="PUT" if direction == "BEARISH" else "CALL",
        ),
        chartAnalysis=ChartAnalysis(
            patterns=[
                {
                    "name": "Bearish Engulfing",
                    "bias": "BEARISH",
                    "strength": 78.0,
                    "timeframe": "5m",
                }
            ]
        ),
    )


def _ftv_put_alert() -> dict:
    return {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24500.0,
        "tier": "EXPLODING",
        "explosionScore": 42.0,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictFirstLift": True,
        "flatVerticalQuality": 72.0,
        "flatVerticalGrade": "A",
    }


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_bearish_engulfing_aligns_put(mock_gs):
    mock_gs.return_value = _settings()
    patterns = aligned_candlestick_patterns(Side.PUT, _snap(direction="BULLISH"))
    assert len(patterns) == 1
    assert patterns[0]["name"] == "Bearish Engulfing"


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_bullish_pattern_does_not_align_put(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BULLISH")
    snap.chartAnalysis = ChartAnalysis(
        patterns=[
            {
                "name": "Bullish Engulfing",
                "bias": "BULLISH",
                "strength": 78.0,
                "timeframe": "5m",
            }
        ]
    )
    assert aligned_candlestick_patterns(Side.PUT, snap) == []


def test_alert_has_ftv_v_structure_flat_vertical():
    assert alert_has_ftv_v_structure(_ftv_put_alert()) is True


def test_alert_has_ftv_v_structure_v_rip():
    assert alert_has_ftv_v_structure({"ictVRipReady": True}) is True


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_chart_bypass_when_session_chart_lags(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BULLISH", mom5=0.02)
    alert = _ftv_put_alert()
    assert ftv_candlestick_chart_bypass(Side.PUT, snap, alert=alert) is True


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_chart_bypass_blocked_when_already_aligned(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.08)
    alert = _ftv_put_alert()
    assert ftv_candlestick_chart_bypass(Side.PUT, snap, alert=alert) is False


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_chart_bypass_blocked_without_ftv_structure(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BULLISH", mom5=0.02)
    alert = {"side": "PUT", "explosionScore": 40.0, "tier": "WATCH"}
    assert ftv_candlestick_chart_bypass(Side.PUT, snap, alert=alert) is False


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_index_aligned_for_grade_a_ftv(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BULLISH")
    assert ftv_candlestick_index_aligned(_ftv_put_alert(), snap) is True


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_rank_bonus_scales_with_pattern_strength(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BULLISH")
    bonus = ftv_candlestick_rank_bonus(snap, _ftv_put_alert(), Side.PUT)
    assert 5.0 <= bonus <= 10.0


@patch("app.engines.ftv_candlestick_confirm.get_settings")
def test_rank_bonus_zero_without_ftv(mock_gs):
    mock_gs.return_value = _settings()
    snap = _snap(direction="BULLISH")
    assert ftv_candlestick_rank_bonus(snap, {"side": "PUT"}, Side.PUT) == 0.0
