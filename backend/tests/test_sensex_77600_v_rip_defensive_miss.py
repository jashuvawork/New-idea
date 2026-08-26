"""Aug26 SENSEX PUT 77600/77700 — v_rip at local base blocked by defensive score floor."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import immature_explosion_blocked
from app.engines.ict_breakout_monitor import (
    ICTBreakoutSignal,
    _defensive_base_rip_top_allowed,
    merge_alert_ict_stamps,
)
from app.engines.morning_premium_capture import is_v_rip_local_base_capture_alert
from app.engines.whipsaw_guards import check_bearish_sideways_entry
from app.models.schemas import MarketPhase, Side, SymbolSnapshot


def _sensex_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-08-26T11:40:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=48.0,
        spot=77740.0,
        atmStrike=77700.0,
    )


def _aug26_alert(*, strike: float = 77600.0, score: float = 42.2, lb: float = 9.3):
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": strike,
        "tier": "EXPLODING",
        "explosionScore": score,
        "dailyMovePct": 34.91,
        "localBaseMovePct": lb,
        "ictBaseRelativeMovePct": lb,
        "ictVRipReady": True,
        "volumeAwaken": True,
        "ictFlatThenVertical": True,
        "ictLocalSwingBase": True,
        "momentType": "v_rip_session_low",
        "velocity3s": 0.0,
    }


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
def test_v_rip_alert_is_premium_capture_at_42_score(_window):
    assert is_v_rip_local_base_capture_alert(_aug26_alert()) is True


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=True)
@patch("app.engines.whipsaw_guards.is_bearish_sideways", return_value=True)
@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.whipsaw_guards.get_settings")
def test_bearish_sideways_allows_v_rip_local_base_at_42(mock_ws, _win, _bs, _bss):
    settings = Settings()
    mock_ws.return_value = settings
    snap = _sensex_snap()
    alert = _aug26_alert()
    cand = SimpleNamespace(
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        score=42.2,
        side=Side.PUT,
        strike=77600.0,
        alert=alert,
        explosion_event=ExplosionEvent(
            symbol="SENSEX",
            side=Side.PUT,
            strike=77600.0,
            premium=102.55,
            velocity_3s=0.0,
            velocity_9s=0.0,
            velocity_15s=0.0,
            volume_surge=2.0,
            explosion_score=42.2,
            tier="EXPLODING",
            reason="v_rip_session_low",
            daily_move_pct=34.91,
        ),
    )
    blocked, reason = check_bearish_sideways_entry(cand, {snap.symbol: snap})
    assert blocked is False, reason


def test_defensive_rip_top_softens_score_for_v_rip_pad():
    settings = MagicMock()
    settings.ict_defensive_base_rip_require_top_quality = True
    settings.ict_defensive_base_rip_min_quality = 70.0
    settings.ict_defensive_base_rip_min_score = 75.0
    settings.ict_defensive_base_rip_min_velocity_3s = 2.5
    settings.ict_v_rip_pad_min_move_pct = 2.0
    settings.ict_v_rip_max_move_pct = 25.0
    settings.ict_v_rip_min_score = 40.0
    settings.ict_v_rip_min_quality = 50.0
    settings.top_ftv_a_pad_velocity_min_move_pct = 8.0
    settings.top_ftv_a_pad_velocity_max_move_pct = 25.0
    settings.ict_v_rip_volume_awake_min_velocity_3s = 0.85
    settings.ict_v_rip_cold_velocity_3s = -1.5
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=72.0,
        score=42.2,
        velocity_3s=0.0,
        settings=settings,
        base_move_pct=9.3,
        volume_awake=True,
        v_rip_ready=True,
    )
    assert ok is True, reason


def test_merge_alert_stamps_v_rip_on_recomputed_ict():
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=40.0,
        reasons=["flat_then_vertical"],
        flat_then_vertical=True,
        local_swing_base=True,
        volume_awakening=False,
        v_rip_ready=False,
        base_relative_move_pct=0.0,
    )
    merged = merge_alert_ict_stamps(ict, _aug26_alert())
    assert merged.v_rip_ready is True
    assert merged.volume_awakening is True
    assert merged.base_relative_move_pct == 9.3


@patch("app.engines.elite_never_block.elite_never_block_active", return_value=False)
@patch("app.engines.explosion_entry_guards.get_settings")
def test_immature_admits_v_rip_after_alert_merge(mock_settings, _enb):
    mock_settings.return_value = Settings()
    event = SimpleNamespace(daily_move_pct=34.91, peak_move_pct=34.91)
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=40.0,
        reasons=[],
        flat_then_vertical=True,
        local_swing_base=True,
        volume_awakening=False,
        v_rip_ready=False,
        base_relative_move_pct=9.3,
    )
    ict = merge_alert_ict_stamps(ict, _aug26_alert())
    blocked, reason = immature_explosion_blocked(event, ict=ict)
    assert blocked is False, reason
