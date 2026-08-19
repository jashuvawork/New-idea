"""BUILDING bullish-rip take — mid-rip OK while expanding; cold BUILDING blocked."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.ict_breakout_monitor import (
    analyze_ict_breakout,
    building_rip_bullish_readiness,
    first_lift_entry_readiness,
)
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(side: Side = Side.PUT) -> SymbolSnapshot:
    adverse = 0.08 if side == Side.PUT else -0.08
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=76900.0,
        atmStrike=76900.0,
        breadth=Breadth(
            bias="BEARISH" if side == Side.PUT else "BULLISH",
            score=70.0,
            aligned=True,
        ),
        spotChart=SpotChart(
            direction="BEARISH" if side == Side.PUT else "BULLISH",
            momentum5Pct=adverse,
            momentum10Pct=adverse * 0.5,
            momentum15Pct=adverse * 0.2,
        ),
    )


def _ripping_alert(**overrides):
    alert = {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": 76900.0,
        "premium": 168.0,
        "velocity3s": 2.1,
        "velocity9s": 1.4,
        "volumeSurge": 2.2,
        "volume": 1_500_000,
        "explosionScore": 52.0,
        "score": 52.0,
        "dailyMovePct": 28.0,
        "peakMovePct": 30.0,
        "offLowMovePct": 28.0,
        "localBaseMovePct": 22.0,
        "ictBaseRelativeMovePct": 22.0,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "reason": "volAwaken×1500k",
    }
    alert.update(overrides)
    return alert


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.worst_day_itm_fade.worst_day_defensive_session_active", return_value=False)
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("NORMAL", {}))
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {}))
def test_building_rip_authorizes_mid_rip_while_expanding(
    _mode, _policy, _worst, mock_settings,
):
    """Mid-rip BUILDING with positive live heat must authorize (not stuck forever)."""
    mock_settings.return_value = Settings()
    snap = _snap(Side.PUT)
    ok, reason = building_rip_bullish_readiness(
        snap=snap,
        alert=_ripping_alert(),
    )
    assert ok is True
    assert reason == "building_rip_bullish_ready"

    ready, ready_reason = first_lift_entry_readiness(
        snap=snap,
        alert=_ripping_alert(),
    )
    assert ready is True
    assert ready_reason == "building_rip_bullish_ready"


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.worst_day_itm_fade.worst_day_defensive_session_active", return_value=False)
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("NORMAL", {}))
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {}))
def test_building_rip_rejects_cold_negative_velocity(
    _mode, _policy, _worst, mock_settings,
):
    """Aug19 11:45 cold BUILDING (v3 negative) must stay blocked."""
    mock_settings.return_value = Settings()
    snap = _snap(Side.PUT)
    ok, reason = building_rip_bullish_readiness(
        snap=snap,
        alert=_ripping_alert(
            velocity3s=-0.27,
            velocity9s=0.1,
            explosionScore=52.5,
            dailyMovePct=6.2,
            offLowMovePct=6.2,
            localBaseMovePct=6.2,
            ictBaseRelativeMovePct=6.2,
            peakMovePct=6.2,
        ),
    )
    assert ok is False
    assert "velocity3s" in reason


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_analyze_sets_building_rip_ready_flag(mock_settings):
    mock_settings.return_value = Settings()
    ict = analyze_ict_breakout(
        symbol="SENSEX",
        strike=76900.0,
        side=Side.PUT,
        premium=168.0,
        session_move_pct=28.0,
        peak_move_pct=30.0,
        velocity_3s=2.1,
        velocity_9s=1.4,
        volume=1_500_000,
        volume_surge=2.2,
        tier="BUILDING",
        reason="volAwaken",
    )
    assert ict.building_rip_ready is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ranking_treats_building_rip_as_fresh_positive(mock_settings):
    mock_settings.return_value = Settings()
    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "BUILDING",
            "explosionScore": 55.0,
            "tqs": 55.0,
            "chartConfidence": 60.0,
            "velocity3s": 2.1,
            "velocity9s": 1.4,
            "localBaseMovePct": 28.0,
            "buildingRipReady": True,
            "orderflowPositive": True,
            "volumeAwaken": True,
        }
    )
    assert ranking["grade"] != "REJECT"
    assert "building_rip_bullish" in ranking["reasons"]
    assert ranking["evidence"]["buildingRipReady"] is True
