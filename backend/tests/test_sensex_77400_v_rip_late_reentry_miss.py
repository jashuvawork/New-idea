"""Aug27 SENSEX PUT 77400 — v_rip at local base blocked by late reentry + rip score floor."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.explosion_detector import ExplosionEvent, _open_key, _session_low, _session_peak
from app.engines.session_mode_feedback import session_peak_late_reentry_blocked
from app.engines.worst_day_guard import worst_day_allows_candidate
from app.models.schemas import AutoTraderState, MarketPhase, Side, SymbolSnapshot


def _sensex_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-08-27T09:58:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=47.0,
        spot=77400.0,
        atmStrike=77400.0,
    )


def _aug27_alert(*, score: float = 29.0):
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77400.0,
        "tier": "EXPLODING",
        "explosionScore": score,
        "dailyMovePct": 23.52,
        "peakMovePct": 25.69,
        "localBaseMovePct": 23.5,
        "ictBaseRelativeMovePct": 23.5,
        "ictVRipReady": True,
        "volumeAwaken": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictFirstLift": True,
        "momentType": "v_rip_session_low",
        "velocity3s": 0.0,
        "velocity9s": 0.0,
    }


def _seed_peak(*, low: float = 93.0, peak: float = 118.7) -> None:
    key = _open_key("SENSEX", 77400.0, Side.PUT)
    _session_low[key] = low
    _session_peak[key] = peak


@patch("app.engines.session_mode_feedback.get_settings")
def test_late_reentry_allows_v_rip_flat_v3_at_local_base_pad(mock_settings):
    _seed_peak()
    mock_settings.return_value = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    blocked, reason = session_peak_late_reentry_blocked(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77400.0,
        premium=116.6,
        velocity_3s=0.0,
        alert=_aug27_alert(),
    )
    assert blocked is False, reason


@patch("app.engines.session_mode_feedback.get_settings")
def test_late_reentry_still_blocks_extended_chase_without_pad_lane(mock_settings):
    _seed_peak()
    mock_settings.return_value = Settings(
        explosion_late_reentry_block_enabled=True,
        explosion_late_reentry_min_peak_points=15.0,
        explosion_late_reentry_near_peak_pct=12.0,
        explosion_late_reentry_pullback_ok_pct=22.0,
        explosion_late_reentry_min_velocity_3s=1.2,
    )
    alert = _aug27_alert()
    alert.update(
        {
            "localBaseMovePct": 3.0,
            "ictBaseRelativeMovePct": 3.0,
            "peakMovePct": 24.0,
            "dailyMovePct": 24.0,
            "ictFirstLift": False,
            "ictVRipReady": False,
        }
    )
    blocked, reason = session_peak_late_reentry_blocked(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77400.0,
        premium=116.6,
        velocity_3s=0.0,
        alert=alert,
    )
    assert blocked is True
    assert "late_reentry_near_session_peak" in reason


@patch("app.engines.worst_day_guard.get_settings")
@patch("app.engines.worst_day_guard.session_entry_policy")
def test_defensive_rip_admits_score_29_on_pad_capture_lane(mock_policy, mock_settings):
    mock_settings.return_value = Settings()
    mock_policy.return_value = ("BREAKOUT_ONLY", {})
    snap = _sensex_snap()
    alert = _aug27_alert()
    cand = SimpleNamespace(
        symbol="SENSEX",
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        score=29.0,
        side=Side.PUT,
        strike=77400.0,
        premium=116.6,
        alert=alert,
        explosion_event=ExplosionEvent(
            symbol="SENSEX",
            side=Side.PUT,
            strike=77400.0,
            premium=116.6,
            velocity_3s=0.0,
            velocity_9s=0.0,
            velocity_15s=0.0,
            volume_surge=2.0,
            explosion_score=29.0,
            tier="EXPLODING",
            reason="v_rip_session_low",
            daily_move_pct=23.52,
            peak_move_pct=25.69,
        ),
    )
    with patch(
        "app.engines.ict_breakout_monitor._defensive_base_rip_top_allowed",
        return_value=(True, "ok"),
    ), patch(
        "app.engines.ict_breakout_monitor._expiry_worst_session",
        return_value=True,
    ), patch(
        "app.engines.ict_breakout_monitor._expiry_worst_defensive_rip_allowed",
        return_value=(True, "pad_lane_expiry_worst_waive"),
    ):
        ok, reason, meta = worst_day_allows_candidate(
            cand,
            AutoTraderState(),
            {snap.symbol: snap},
            policy="BREAKOUT_ONLY",
        )
    assert ok is True, reason
    assert meta.get("defensiveBaseRip") is True
