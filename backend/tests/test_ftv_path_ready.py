"""FTV path readiness — promoted buildingRip stays takeable end-to-end."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.building_ftv_gates import (
    alert_has_building_rip_signal,
    building_rip_bypasses_fake_trap,
)
from app.engines.building_ltp_monitor import (
    building_alerts_on_radar,
    reset_building_ltp_monitor_for_tests,
)
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import _ict_flat_vertical_entry_ok, check_explosion_entry
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SuggestedTrade,
    SymbolSnapshot,
    StrategyType,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=76900.0,
        atmStrike=76900.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.16,
            momentum10Pct=-0.12,
            momentum15Pct=-0.05,
        ),
        explosionAlerts=[],
    )


def test_promoted_building_rip_stays_on_ltp_watch():
    reset_building_ltp_monitor_for_tests()
    snap = _snap()
    snap.explosionAlerts = [
        {
            "tier": "EXPLODING",
            "side": "PUT",
            "strike": 76900.0,
            "premium": 131.0,
            "reason": "buildingRip+v3_2.1 volAwaken",
            "ictBuildingRipReady": True,
        }
    ]
    rows = building_alerts_on_radar({"SENSEX": snap})
    assert len(rows) == 1
    assert rows[0]["strike"] == 76900.0


def test_alert_has_building_rip_from_reason():
    assert alert_has_building_rip_signal(
        {"tier": "EXPLODING", "reason": "buildingRip+v3_2.1"}
    )
    assert not alert_has_building_rip_signal(
        {"tier": "EXPLODING", "reason": "volAwaken only"}
    )


def test_fake_trap_bypass_for_building_helpers():
    assert building_rip_bypasses_fake_trap(
        alert={
            "ictBuildingRipReady": True,
            "buildingLiftHelping": True,
            "ictBaseReadinessReason": "building_rip_bullish_ready",
        }
    )
    assert not building_rip_bypasses_fake_trap(alert={"tier": "ELITE"})


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.worst_day_itm_fade.worst_day_defensive_session_active", return_value=False)
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("NORMAL", {}))
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {}))
@patch("app.engines.smart_ichimoku.ichimoku_break_supports_side", return_value=(False, "no"))
def test_building_rip_short_circuits_entry_ok(
    _ichi, _mode, _policy, _worst, mock_ep, mock_ict,
):
    settings = Settings()
    mock_ep.return_value = settings
    mock_ict.return_value = settings
    snap = _snap()
    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76900.0,
        premium=131.0,
        velocity_3s=2.0,
        velocity_9s=1.2,
        velocity_15s=1.0,
        volume_surge=2.2,
        volume=80_000,
        explosion_score=52.0,
        tier="BUILDING",
        reason="volAwaken",
        daily_move_pct=8.0,
        peak_move_pct=8.0,
    )
    alert = {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": 76900.0,
        "premium": 131.0,
        "velocity3s": 2.0,
        "velocity9s": 1.2,
        "volumeSurge": 2.2,
        "volume": 80_000,
        "explosionScore": 52.0,
        "ictBaseRelativeMovePct": 6.0,
        "ictLocalSwingBase": True,
        "ictVolumeAwakening": True,
        "volumeAwaken": True,
        "cvdBuying": True,
        "ictDisplacement": True,
    }
    with patch(
        "app.engines.ict_breakout_monitor.first_lift_entry_readiness",
        return_value=(True, "building_local_base_lift_ready"),
    ):
        assert _ict_flat_vertical_entry_ok(event, snap, alert=alert) is True
        trade = SuggestedTrade(
            id="t1",
            symbol="SENSEX",
            side=Side.PUT,
            strike=76900.0,
            lastPremium=131.0,
            tqs=55.0,
            strategyType=StrategyType.EXPLOSIVE,
            confidence=52.0,
        )
        ok, reason = check_explosion_entry(
            event,
            trade,
            snap.breadth,
            False,
            snap=snap,
            alert=alert,
        )
        assert ok is True, reason
