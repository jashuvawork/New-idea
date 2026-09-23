"""SENSEX / large-LTP symbol premium scaling and CHOP+RALLY structure bypass."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    cheap_base_strike_eligible,
    deep_itm_chase_strike,
)
from app.engines.ict_breakout_monitor import ICTBreakoutSignal, first_lift_entry_readiness
from app.engines.symbol_premium_bands import (
    best_trade_cheap_base_premium_band,
    best_trade_cheap_entry_max_premium,
    large_ltp_base_cold_velocity_waiver,
)
from app.engines.top_ftv_v_expiry_bypass import chop_rally_aligned_structure_bypass_allowed
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def test_sensex_premium_band_scales_3x():
    s = settings_mock()
    assert best_trade_cheap_entry_max_premium("SENSEX", s) == 255.0
    lo, hi = best_trade_cheap_base_premium_band("SENSEX", s)
    assert lo == 54.0
    assert hi == 240.0
    assert best_trade_cheap_entry_max_premium("NIFTY", s) == 85.0


def test_sensex_170_counts_as_cheap_base_not_deep_itm():
    s = settings_mock()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-09-23T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=74800.0,
        atmStrike=74800.0,
        dataAvailable=True,
    )
    alert = {
        "premium": 170.0,
        "localBaseMovePct": 8.0,
        "ictBaseRelativeMovePct": 8.0,
        "offLowMovePct": 6.0,
    }
    cand = MagicMock(
        mode="explosion",
        symbol="SENSEX",
        side=Side.CALL,
        strike=74800.0,
        premium=170.0,
        snap=snap,
        alert=alert,
    )
    assert cheap_base_strike_eligible(cand, alert, snap, settings=s) is True
    assert deep_itm_chase_strike(cand, alert, snap, settings=s) is False


@patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=False)
def test_sensex_near_base_not_blocked_as_chop_deep_chase(_exp):
    s = settings_mock()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-09-23T10:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=74800.0,
        atmStrike=74800.0,
        dataAvailable=True,
    )
    cand = MagicMock(
        mode="explosion",
        symbol="SENSEX",
        side=Side.CALL,
        strike=74800.0,
        premium=170.0,
        snap=snap,
        alert={},
    )
    assessment = {
        "dayMode": "CHOP + RALLY",
        "setup": "FTV",
        "localBasePct": 10.0,
        "eliteScore": 92.0,
    }
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        None,
        assessment,
        day_mode="CHOP + RALLY",
        settings=s,
    )
    assert blocked is False
    assert reason == ""


def _sensex_bullish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 9, 23, 10, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=74850.0,
        atmStrike=74800.0,
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.25,
            trendStrength=35.0,
            spot=74850.0,
        ),
    )


def _sensex_bearish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 9, 23, 10, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=74750.0,
        atmStrike=74800.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.25,
            trendStrength=35.0,
            spot=74750.0,
        ),
    )


@patch(
    "app.engines.top_ftv_v_expiry_bypass.get_settings",
    return_value=Settings(chop_rally_structure_bypass_enabled=True),
)
def test_chop_rally_structure_bypass_ce_and_pe(_mock):
    s = Settings(chop_rally_structure_bypass_enabled=True)
    ce_alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "ictFlatThenVertical": True,
        "ictBreakout": False,
        "localBaseMovePct": 12.0,
        "flatVerticalQuality": 70.0,
        "ictVolumeAwakening": True,
    }
    assert chop_rally_aligned_structure_bypass_allowed(
        tier="ELITE",
        score=60.0,
        base_move_pct=12.0,
        volume_awakening=True,
        side="CALL",
        day_mode="CHOP + RALLY",
        snap=_sensex_bullish_snap(),
        row=ce_alert,
        symbol="SENSEX",
    ) is True

    pe_alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "ictFirstLift": True,
        "localBaseMovePct": 9.0,
        "flatVerticalQuality": 68.0,
        "volumeAwaken": True,
    }
    assert chop_rally_aligned_structure_bypass_allowed(
        tier="EXPLODING",
        score=58.0,
        base_move_pct=9.0,
        volume_awakening=True,
        side="PUT",
        day_mode="CHOP + RALLY",
        snap=_sensex_bearish_snap(),
        row=pe_alert,
        symbol="SENSEX",
    ) is True


def test_large_ltp_cold_velocity_waiver_sensex_at_base():
    s = settings_mock()
    evidence = {
        "symbol": "SENSEX",
        "localBaseMovePct": 10.0,
        "ictFlatThenVertical": True,
        "ictVolumeAwakening": True,
        "flatVerticalQuality": 72.0,
    }
    assert large_ltp_base_cold_velocity_waiver(
        premium=170.0,
        symbol="SENSEX",
        evidence=evidence,
        volume_awakening=True,
        settings=s,
    ) is True


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.session_timing.in_midday_chop_window", return_value=False)
def test_sensex_chop_rally_first_lift_cold_v3_at_base(_midday, mock_ict_settings, mock_bypass_settings):
    s = settings_mock(
        chop_rally_structure_bypass_enabled=True,
        large_ltp_base_cold_velocity_waiver_enabled=True,
    )
    mock_ict_settings.return_value = s
    mock_bypass_settings.return_value = s
    snap = _sensex_bullish_snap()
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "premium": 170.0,
        "tier": "ELITE",
        "explosionScore": 62.0,
        "ictFirstLift": True,
        "ictFlatThenVertical": False,
        "ictBreakout": False,
        "ictBaseRelativeMovePct": 18.0,
        "localBaseMovePct": 18.0,
        "flatVerticalQuality": 70.0,
        "velocity3s": 0.4,
        "velocity9s": 0.3,
        "volumeSurge": 2.2,
        "ictVolumeAwakening": True,
    }
    event = SimpleNamespace(
        tier="ELITE",
        explosion_score=62.0,
        velocity_3s=0.4,
        velocity_9s=0.3,
        volume_surge=2.2,
        premium=170.0,
    )
    ict = ICTBreakoutSignal(
        active=False,
        pattern="first_lift",
        score=62.0,
        reasons=[],
        first_lift=True,
        flat_then_vertical=False,
        base_relative_move_pct=18.0,
        volume_awakening=True,
        flat_vertical_quality=70.0,
    )
    ok, reason = first_lift_entry_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        day_mode="CHOP + RALLY",
    )
    assert ok is True
    assert "first_lift_structure_not_confirmed" not in reason
    assert "first_lift_velocity3s" not in reason
