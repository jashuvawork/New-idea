"""Oct 1 stack — post-Oct funnel blockers relaxed under replica / paper parity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.engines.explosion_entry_guards import (
    explosion_entry_window_blocked,
    live_explosion_confirmation_blocked,
)
from app.engines.morning_premium_capture import counter_trend_entry_allowed
from app.engines.rally_capture import explosion_near_miss_waive, index_pin_blocks_put_explosion
from app.engines.smart_ichimoku import ichimoku_break_supports_side
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import Side
from tests.mock_defaults import settings_mock


def _replica(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        live_paper_parity_enabled=True,
        oct_paper_replica_enabled=True,
        aggressive_min_explosion_score=45.0,
        **kwargs,
    )


def test_replica_skips_smart_ichimoku_cloud_gate():
    s = _replica()
    snap = MagicMock()
    snap.chartAnalysis = MagicMock(
        ichimoku={
            "priceVsCloud": "BELOW",
            "breakSide": "BEARISH",
            "breakConfirmed": False,
            "breakProbability": 0.2,
            "smartBias": "BEARISH",
        }
    )
    ok, reason = ichimoku_break_supports_side(
        Side.CALL, snap, require_confirmed=True, alert={"tier": "ELITE"},
    )
    with patch("app.engines.smart_ichimoku.get_settings", return_value=s):
        ok, reason = ichimoku_break_supports_side(
            Side.CALL, snap, require_confirmed=True, alert={"tier": "ELITE"},
        )
    assert ok is True
    assert "oct_paper_replica_skips_smart_ichimoku" in reason


def test_replica_skips_entry_window_for_elite():
    s = _replica()
    event = MagicMock(tier="ELITE", side=Side.CALL, symbol="NIFTY")
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=s):
        blocked, reason = explosion_entry_window_blocked(
            event,
            ict=MagicMock(base_relative_move_pct=4.0),
            alert={"tier": "ELITE", "localBaseMovePct": 4.0},
        )
    assert blocked is False
    assert reason == ""


def test_replica_waives_mid_rip_near_miss_for_structural_pad():
    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "side": "PUT",
        "firstLift": True,
        "armedBaseLaunch": True,
        "localBaseMovePct": 8.0,
        "ictArmedBaseLaunch": True,
    }
    with patch(
        "app.engines.live_paper_parity.oct_paper_structural_pad_context",
        return_value=True,
    ):
        assert explosion_near_miss_waive(
            alert,
            readiness_reason="mid_rip_armed_coil_rejected",
            settings=s,
        )


def test_replica_ranking_does_not_reject_mid_rip_coil_for_structural_pad():
    s = _replica()
    evidence = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "midRipCoil": True,
        "firstLift": True,
        "armedBaseLaunch": True,
        "localBaseMovePct": 8.0,
        "ictArmedBaseLaunch": True,
        "velocity3s": 2.0,
        "velocity9s": 2.0,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    with patch(
        "app.engines.live_paper_parity.oct_paper_funnel_readiness_waived",
        return_value=True,
    ):
        ranking = rank_trade_evidence(evidence)
    codes = [p.get("code") for p in ranking.get("penalties") or []]
    assert "mid_rip_armed_coil" not in codes


def test_replica_waives_premium_out_of_band_near_miss_oct1_style():
    s = _replica()
    alert = {"tier": "ELITE", "explosionScore": 88.0, "side": "CALL", "strike": 72500.0}
    from app.engines.rally_capture import explosion_near_miss_waive

    assert explosion_near_miss_waive(
        alert,
        readiness_reason="premium_out_of_band",
        settings=s,
    )


def test_replica_elite_funnel_waives_without_pad_flags():
    from app.engines.live_paper_parity import oct_paper_funnel_readiness_waived

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 92.0,
        "side": "CALL",
        "localBaseMovePct": 12.0,
        "sessionRangePosition": 0.35,
    }
    assert oct_paper_funnel_readiness_waived(alert, settings=s) is True


def test_replica_waives_midday_no_ict_for_elite_funnel():
    s = _replica()
    event = MagicMock(
        tier="ELITE",
        velocity_3s=3.0,
        velocity_9s=3.0,
        explosion_score=90.0,
        volume_surge=1.0,
    )
    ict = MagicMock(
        flat_then_vertical=False,
        displacement=True,
        session_move_pct=20.0,
    )
    alert = {
        "tier": "ELITE",
        "explosionScore": 90.0,
        "side": "CALL",
        "sessionRangePosition": 0.4,
    }
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=s):
        blocked, reason = live_explosion_confirmation_blocked(
            event,
            ict=ict,
            alert=alert,
            midday_chop=True,
        )
    assert blocked is False
    assert reason == ""


def test_replica_counter_trend_allowed_for_elite_funnel():
    s = _replica()
    snap = MagicMock()
    snap.breadth = MagicMock(bias="BULLISH")
    event = MagicMock(side=Side.PUT, tier="ELITE", explosion_score=88.0)
    alert = {
        "tier": "ELITE",
        "explosionScore": 88.0,
        "side": "PUT",
        "sessionRangePosition": 0.42,
    }
    with patch("app.engines.morning_premium_capture.get_settings", return_value=s):
        assert counter_trend_entry_allowed(
            Side.PUT, snap, explosion_event=event, alert=alert,
        ) is True


def test_replica_skips_put_index_pin_block():
    s = _replica(index_pin_put_block_enabled=True)
    event = MagicMock(side=Side.PUT)
    snap = MagicMock()
    snap.constituentHeatmap = MagicMock(dataAvailable=True, breadthPct=80.0)
    snap.breadth = MagicMock(stockScore=80.0)
    snap.spotChart = MagicMock(spot=100.0)
    snap.marketProfile = MagicMock(openingRangeHigh=100.0, vah=0)
    with patch("app.engines.rally_capture.get_settings", return_value=s):
        blocked, _ = index_pin_blocks_put_explosion(event, snap)
    assert blocked is False
