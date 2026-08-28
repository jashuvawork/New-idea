"""Grade-A BUILDING armed_base_option_led_ready live selector bypass."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.building_ftv_gates import (
    building_armed_base_grade_a_live_ok,
    building_armed_base_grade_a_top_moment_ok,
)
from app.engines.top_moment_gate import (
    explosion_alert_is_top_moment,
    top_moment_entry_allowed,
)
from app.engines.trade_selector import find_best_entry
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


def _snap(side: Side = Side.PUT) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=70.0,
        spot=24200.0,
        atmStrike=24200.0,
        regime=Regime.TREND_EXPANSION,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH" if side == Side.PUT else "BULLISH",
            momentum5Pct=-0.05,
            momentum10Pct=-0.03,
            momentum15Pct=-0.01,
        ),
    )


def _building_armed_alert(**overrides) -> dict:
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24200.0,
        "premium": 81.0,
        "tier": "BUILDING",
        "tradeable": True,
        "explosionScore": 59.5,
        "velocity3s": 2.5,
        "velocity9s": 2.0,
        "volumeSurge": 3.0,
        "volumeAwaken": True,
        "ictBaseArmed": True,
        "ictArmedBaseLaunch": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 12.0,
        "ictBasePremium": 72.0,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseSpanSeconds": 24.0,
        "volume": 30000.0,
        "dailyMovePct": 18.0,
        "peakMovePct": 20.0,
    }
    alert.update(overrides)
    return alert


def test_building_armed_base_grade_a_live_ok_requires_readiness_reason():
    settings = Settings(building_armed_base_grade_a_live_enabled=True)
    alert = _building_armed_alert()
    snap = _snap()
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        assert building_armed_base_grade_a_live_ok(
            alert, snap, readiness_reason="armed_base_option_led_ready",
        ) is True
        assert building_armed_base_grade_a_live_ok(
            alert, snap, readiness_reason="slow_grind_armed_trough_ready",
        ) is False


def test_building_armed_base_grade_a_live_ok_blocks_extended_base_rel():
    settings = Settings(building_armed_base_grade_a_live_enabled=True)
    alert = _building_armed_alert(ictBaseRelativeMovePct=55.0)
    snap = _snap()
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        assert building_armed_base_grade_a_live_ok(
            alert, snap, readiness_reason="armed_base_option_led_ready",
        ) is False


def test_building_armed_base_grade_a_live_ok_blocks_grade_b():
    settings = Settings(building_armed_base_grade_a_live_enabled=True)
    alert = _building_armed_alert(explosionScore=20.0, velocity3s=0.1, velocity9s=0.1)
    snap = _snap()
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        assert building_armed_base_grade_a_live_ok(
            alert, snap, readiness_reason="armed_base_option_led_ready",
        ) is False


def test_top_moment_allows_building_armed_base_grade_a():
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "localBaseMovePct": 12.0,
        "velocity3s": 2.5,
        "velocity9s": 2.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "orderflowPositive": True,
    }
    ranking = {"grade": "A", "gradePriority": 3}
    settings = Settings(building_armed_base_grade_a_live_enabled=True)
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        ok, reason, moment = top_moment_entry_allowed(
            evidence,
            ranking,
            readiness_reason="armed_base_option_led_ready",
        )
    assert ok is True
    assert reason == "ok"
    assert moment == "FTV"


def test_top_moment_building_armed_base_helper():
    evidence = {
        "tier": "BUILDING",
        "localBaseMovePct": 12.0,
        "volumeSurge": 3.0,
    }
    ranking = {"grade": "A"}
    settings = Settings(building_armed_base_grade_a_live_enabled=True)
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        assert building_armed_base_grade_a_top_moment_ok(
            evidence, ranking, readiness_reason="armed_base_option_led_ready",
        ) is True


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_selector_admits_building_armed_base_without_elite_tier(
    mock_ready, _open,
):
    settings = Settings(
        best_trades_only_enabled=False,
        edge_engine_enabled=False,
        top_moments_only_enabled=True,
        explosion_elite_exploding_only=True,
        building_armed_base_grade_a_live_enabled=True,
    )
    alert = _building_armed_alert()
    snap = _snap()
    snap.explosionAlerts = [alert]
    mock_ready.return_value = (True, "armed_base_option_led_ready")

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.trade_selector.get_settings", return_value=settings),
        patch("app.engines.building_ftv_gates.get_settings", return_value=settings),
        patch(
            "app.engines.top_moment_gate.explosion_alert_is_top_moment",
            return_value=False,
        ),
    ):
        selected = find_best_entry({"NIFTY": snap}, AutoTraderState())

    assert selected is not None
    assert selected.tier == "BUILDING"
    assert selected.side == Side.PUT
    assert selected.strike == 24200.0


def test_explosion_alert_is_top_moment_still_false_without_bypass():
    alert = _building_armed_alert(
        ictFlatThenVertical=False,
        ictArmedBaseLaunch=False,
        ictBaseArmed=False,
    )
    assert explosion_alert_is_top_moment(alert) is False
