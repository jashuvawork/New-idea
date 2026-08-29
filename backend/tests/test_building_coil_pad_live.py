"""BUILDING coil pad live entry — Aug28 NIFTY PUT 24050 @ 11:12 hindsight path."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.building_ftv_gates import (
    building_coil_pad_grade_a_live_ok,
    building_coil_pad_grade_a_top_moment_ok,
)
from app.engines.early_radar_pad_capture import (
    BUILDING_COIL_PAD_READY,
    BUILDING_COIL_PAD_UNCONFIRMED,
    alert_has_building_coil_pad,
    alert_has_building_coil_pad_armed,
    building_coil_pad_entry_readiness,
    building_coil_pad_lane_active,
    building_coil_pad_lift_confirmed,
    building_coil_pad_lift_signal,
    building_coil_pad_live_blocked,
    stamp_building_coil_pad,
)
from app.engines.explosion_profit import check_explosion_entry
from app.engines.explosion_detector import ExplosionEvent
from app.engines.top_moment_gate import (
    explosion_alert_is_top_moment,
    top_moment_entry_allowed,
)
from app.engines.trade_ranking import ftv_authorization_policy
from app.engines.trade_selector import find_best_entry
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SuggestedTrade,
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
        spot=24150.0,
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


def _aug28_24050_alert(**overrides) -> dict:
    """Aug28 hindsight #1: BUILDING PUT 24050 @ 11:12, baseRel 20.7%, v3=0."""
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24050.0,
        "premium": 95.0,
        "tier": "BUILDING",
        "tradeable": False,
        "explosionScore": 36.3,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "volumeSurge": 2.5,
        "volumeAwaken": True,
        "ictBaseArmed": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 20.7,
        "localBaseMovePct": 20.7,
        "ictBasePremium": 78.0,
        "volume": 25000.0,
        "dailyMovePct": 22.0,
        "peakMovePct": 24.0,
        "offLowMovePct": 12.0,
    }
    alert.update(overrides)
    return alert


def test_building_coil_pad_lift_signal_aug28_window():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert()
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        assert building_coil_pad_lift_signal(alert, settings) is True


def test_building_coil_pad_stamps_readiness():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert()
    snap = _snap()
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        ok, reason = building_coil_pad_entry_readiness(snap=snap, alert=alert, settings=settings)
    assert ok is True
    assert reason == BUILDING_COIL_PAD_READY
    assert alert_has_building_coil_pad(alert)


def test_building_coil_pad_grade_a_live_ok():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert()
    stamp_building_coil_pad(alert, settings)
    snap = _snap()
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        assert building_coil_pad_grade_a_live_ok(
            alert, snap, readiness_reason=BUILDING_COIL_PAD_READY,
        ) is True


def test_top_moment_allows_building_coil_pad():
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "localBaseMovePct": 20.7,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "buildingCoilPad": True,
        "volumeAwaken": True,
        "explosionScore": 36.3,
    }
    ranking = {"grade": "A", "gradePriority": 3}
    settings = Settings(building_coil_pad_entry_enabled=True)
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        ok, reason, moment = top_moment_entry_allowed(
            evidence,
            ranking,
            readiness_reason=BUILDING_COIL_PAD_READY,
        )
    assert ok is True
    assert moment == "FTV"


def test_ftv_authorization_building_coil_pad_max_capital():
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "localBaseMovePct": 20.7,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "buildingCoilPad": True,
        "volumeAwaken": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "explosionScore": 36.3,
        "firstLiftReadinessReason": BUILDING_COIL_PAD_READY,
    }
    ranking = {"grade": "A"}
    settings = Settings(
        building_coil_pad_ftv_enabled=True,
        building_coil_pad_entry_enabled=True,
        pad_lane_ftv_waives_allocation_rank_one=True,
    )
    with patch("app.config.get_settings", return_value=settings):
        auth = ftv_authorization_policy(
            evidence,
            ranking,
            snapshot_available=True,
            atm_itm_allowed=True,
            require_allocation_rank_one=False,
            **{k: getattr(settings, k) for k in (
                "building_coil_pad_ftv_enabled",
                "building_coil_pad_ftv_max_capital_pct",
                "building_coil_pad_min_local_move_pct",
                "building_coil_pad_max_local_move_pct",
            )},
        )
    assert auth.allowed is True
    assert auth.mode == "BUILDING_COIL_PAD_FTV"
    assert auth.max_capital_pct == pytest.approx(0.90)


def test_explosion_alert_is_top_moment_with_coil_pad():
    alert = _aug28_24050_alert()
    stamp_building_coil_pad(alert, Settings(building_coil_pad_entry_enabled=True))
    assert explosion_alert_is_top_moment(alert) is True


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_selector_admits_building_coil_pad_without_elite_tier(mock_ready, _open):
    settings = Settings(
        best_trades_only_enabled=False,
        edge_engine_enabled=False,
        top_moments_only_enabled=True,
        explosion_elite_exploding_only=True,
        building_coil_pad_entry_enabled=True,
        explosion_capture_mode=True,
    )
    alert = _aug28_24050_alert()
    stamp_building_coil_pad(alert, settings)
    snap = _snap()
    snap.explosionAlerts = [alert]
    mock_ready.return_value = (True, BUILDING_COIL_PAD_READY)

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
    assert selected.strike == 24050.0


def test_building_coil_pad_armed_without_confirmation_blocks_entry():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    snap = _snap()
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        assert building_coil_pad_lift_signal(alert, settings) is True
        assert building_coil_pad_lift_confirmed(alert, settings) is False
        ok, reason = building_coil_pad_entry_readiness(snap=snap, alert=alert, settings=settings)
    assert ok is False
    assert reason == BUILDING_COIL_PAD_UNCONFIRMED
    assert alert_has_building_coil_pad_armed(alert)
    assert not alert_has_building_coil_pad(alert)


def test_building_coil_pad_confirmed_via_velocity():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.55,
        velocity9s=0.0,
    )
    snap = _snap()
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        ok, reason = building_coil_pad_entry_readiness(snap=snap, alert=alert, settings=settings)
    assert ok is True
    assert reason == BUILDING_COIL_PAD_READY
    assert alert_has_building_coil_pad(alert)


def test_building_coil_pad_confirmed_via_flat_vertical_volume():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        velocity3s=0.0,
        velocity9s=0.0,
    )
    snap = _snap()
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        ok, reason = building_coil_pad_entry_readiness(snap=snap, alert=alert, settings=settings)
    assert ok is True
    assert reason == BUILDING_COIL_PAD_READY


def test_grade_a_live_ok_requires_confirmed_coil_pad():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    snap = _snap()
    with patch("app.engines.building_ftv_gates.get_settings", return_value=settings):
        assert building_coil_pad_grade_a_live_ok(alert, snap) is False


def test_explosion_alert_armed_only_not_top_moment():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        stamp_building_coil_pad(alert, settings)
    assert alert_has_building_coil_pad_armed(alert)
    assert not alert_has_building_coil_pad(alert)
    assert explosion_alert_is_top_moment(alert) is False


def test_fresh_elite_in_coil_window_requires_confirmation_without_prior_stamp():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        tier="ELITE",
        explosionScore=72.0,
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        assert building_coil_pad_lane_active(alert, settings) is True
        assert building_coil_pad_lift_confirmed(alert, settings) is False
        blocked, reason = building_coil_pad_live_blocked(alert, settings)
    assert blocked is True
    assert reason == BUILDING_COIL_PAD_UNCONFIRMED


def test_promoted_elite_in_coil_window_requires_confirmation():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        tier="ELITE",
        explosionScore=72.0,
        buildingCoilPadArmed=True,
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        assert building_coil_pad_lane_active(alert, settings) is True
        assert building_coil_pad_lift_confirmed(alert, settings) is False
        blocked, reason = building_coil_pad_live_blocked(alert, settings)
    assert blocked is True
    assert reason == BUILDING_COIL_PAD_UNCONFIRMED


def test_promoted_exploding_confirmed_via_flat_vertical_volume():
    settings = Settings(building_coil_pad_entry_enabled=True)
    alert = _aug28_24050_alert(
        tier="EXPLODING",
        explosionScore=58.0,
        buildingCoilPadArmed=True,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    snap = _snap()
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=settings):
        ok, reason = building_coil_pad_entry_readiness(snap=snap, alert=alert, settings=settings)
        blocked, _ = building_coil_pad_live_blocked(alert, settings)
    assert ok is True
    assert reason == BUILDING_COIL_PAD_READY
    assert blocked is False
    assert alert_has_building_coil_pad(alert)


@patch("app.engines.explosion_entry_guards.get_settings")
def test_explosion_entry_blocks_promoted_elite_unconfirmed_coil(mock_settings):
    settings = Settings(
        building_coil_pad_entry_enabled=True,
        tier_promotion_pad_chase_block_enabled=False,
    )
    mock_settings.return_value = settings
    alert = _aug28_24050_alert(
        tier="ELITE",
        explosionScore=72.0,
        buildingCoilPadArmed=True,
        ictFlatThenVertical=False,
        flatThenVertical=False,
        ictBreakout=False,
        volumeAwaken=False,
        volumeSurge=0.5,
        velocity3s=0.0,
        velocity9s=0.0,
    )
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        premium=95.0,
        velocity_3s=0.0,
        velocity_9s=0.0,
        velocity_15s=0.0,
        volume_surge=0.5,
        explosion_score=72.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=22.0,
        peak_move_pct=24.0,
    )
    trade = SuggestedTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        lastPremium=95.0,
        tqs=70,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=72,
    )
    with patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
        return_value=type(
            "ICT",
            (),
            {
                "active": False,
                "flat_then_vertical": False,
                "base_relative_move_pct": 20.7,
                "session_move_pct": 20.7,
                "volume_awakening": False,
            },
        )(),
    ):
        ok, reason = check_explosion_entry(
            event,
            trade,
            Breadth(score=70, bias="BEARISH", aligned=True),
            False,
            alert=alert,
        )
    assert ok is False
    assert reason == BUILDING_COIL_PAD_UNCONFIRMED
