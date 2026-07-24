"""Gap-down bearish session chart vs bullish Ichimoku + local premium base."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.local_base_chart_bypass import (
    ichimoku_supports_side,
    local_base_ichimoku_chart_bypass,
)
from app.engines.rally_capture import chart_blocks_explosion_side
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.local_base_ichimoku_chart_bypass_enabled = True
    s.local_base_ichimoku_require_cloud = True
    s.local_base_ichimoku_max_adverse_mom5_pct = 0.08
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _bearish_gap_chart():
    return SpotChart(
        direction="BEARISH",
        momentum5Pct=0.01,
        momentum15Pct=-0.35,
        momentum30Pct=-0.55,
        trendStrength=70,
        emaBias="BEARISH",
        candleBias="NEUTRAL",
        orPosition="BELOW",
        macdBias="BEARISH",
        rsi=42,
        spot=23680.0,
    )


def _snap(*, ichimoku_cloud="BULLISH", tk="BULLISH", price_vs="ABOVE"):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.TREND_EXPANSION,
        spot=23680.0,
        atmStrike=23650.0,
        tradeQualityScore=55,
        breadth=Breadth(bias="BEARISH", score=40, aligned=False),
        spotChart=_bearish_gap_chart(),
        chartAnalysis=ChartAnalysis(
            consensus="BEARISH",
            ichimoku={
                "cloudBias": ichimoku_cloud,
                "tkCross": tk,
                "priceVsCloud": price_vs,
                "tenkan": 23690.0,
                "kijun": 23670.0,
                "cloudTop": 23660.0,
                "cloudBottom": 23640.0,
            },
        ),
        explosionAlerts=[{
            "side": "CALL",
            "strike": 23650.0,
            "tier": "BUILDING",
            "explosionScore": 42.0,
            "dailyMovePct": 17.0,
            "ictFlatThenVertical": True,
            "ictBreakout": True,
            "ictBaseRelativeMovePct": 30.0,
            "ictPattern": "flat_then_vertical",
            "premium": 148.0,
        }],
    )


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_ichimoku_supports_call_when_cloud_bullish(mock_s):
    mock_s.return_value = _settings()
    assert ichimoku_supports_side(Side.CALL, _snap()) is True
    assert ichimoku_supports_side(Side.CALL, _snap(ichimoku_cloud="BEARISH", tk="BEARISH", price_vs="BELOW")) is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_bypass_allows_call_on_gap_down_with_bullish_ichi(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    alert = snap.explosionAlerts[0]
    assert local_base_ichimoku_chart_bypass(Side.CALL, snap, alert=alert) is True


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_bypass_rejects_without_local_base(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    alert = {
        "side": "CALL",
        "tier": "BUILDING",
        "ictFlatThenVertical": False,
        "ictBreakout": False,
        "ictBaseRelativeMovePct": 0,
        "ictPattern": "watch",
    }
    assert local_base_ichimoku_chart_bypass(Side.CALL, snap, alert=alert) is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_bypass_rejects_hard_live_dump(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    snap.spotChart.momentum5Pct = -0.20  # still dumping
    assert local_base_ichimoku_chart_bypass(Side.CALL, snap, alert=snap.explosionAlerts[0]) is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_chart_blocks_explosion_lifted_with_snap(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    event = SimpleNamespace(
        side=Side.CALL,
        tier="BUILDING",
        daily_move_pct=17.0,
        peak_move_pct=17.0,
        velocity_3s=2.5,
        velocity_9s=2.0,
        volume_surge=2.0,
        explosion_score=42.0,
        symbol="NIFTY",
        strike=23650.0,
        premium=148.0,
        reason="",
        volume=0,
    )
    with patch(
        "app.engines.vertical_rip_bypass.qualifies_for_vertical_rip_bypass",
        return_value=False,
    ), patch(
        "app.engines.morning_premium_capture.premium_led_explosion_bypass",
        return_value=False,
    ):
        blocked, reason = chart_blocks_explosion_side(
            Side.CALL,
            snap.spotChart,
            "BUILDING",
            event=event,
            breadth_bias="BEARISH",
            snap=snap,
        )
    assert blocked is False
