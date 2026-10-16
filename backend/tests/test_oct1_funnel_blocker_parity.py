"""Oct 1 stack — post-Oct funnel blockers relaxed under replica / paper parity."""

from __future__ import annotations

import pytest
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
    from app.engines.live_paper_parity import (
        oct_paper_base_first_lift_take_allowed,
        oct_paper_exec_strict_bypass,
        oct_paper_funnel_readiness_waived,
    )

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 92.0,
        "side": "CALL",
        "localBaseMovePct": 12.0,
        "sessionRangePosition": 0.35,
    }
    assert oct_paper_funnel_readiness_waived(alert, settings=s) is True
    assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True
    assert oct_paper_exec_strict_bypass(alert, settings=s) is True


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
        "localBaseMovePct": 14.0,
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
        "localBaseMovePct": 10.0,
        "sessionRangePosition": 0.42,
    }
    with patch("app.engines.morning_premium_capture.get_settings", return_value=s):
        assert counter_trend_entry_allowed(
            Side.PUT, snap, explosion_event=event, alert=alert,
        ) is True


@pytest.mark.parametrize(
    "side,local,session_pos",
    [
        ("CALL", 12.0, 0.35),
        ("PUT", 10.0, 0.42),
    ],
)
def test_base_lift_funnel_and_exec_bypass_parity_ce_pe(side, local, session_pos):
    from app.engines.live_paper_parity import (
        oct_paper_exec_strict_bypass,
        oct_paper_funnel_readiness_waived,
    )

    s = _replica()
    alert = {
        "tier": "EXPLODING",
        "explosionScore": 88.0,
        "side": side,
        "localBaseMovePct": local,
        "sessionRangePosition": session_pos,
        "armedBaseLaunch": True,
    }
    if side == "PUT":
        with patch(
            "app.engines.put_slide_ce_mirror.put_slide_pad_context", return_value=True
        ):
            assert oct_paper_funnel_readiness_waived(alert, settings=s) is True
            assert oct_paper_exec_strict_bypass(alert, settings=s) is True
    else:
        assert oct_paper_funnel_readiness_waived(alert, settings=s) is True
        assert oct_paper_exec_strict_bypass(alert, settings=s) is True


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_extended_chase_blocks_base_lift_take_ce_pe(side):
    from app.engines.live_paper_parity import oct_paper_base_first_lift_take_allowed

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 95.0,
        "side": side,
        "localBaseMovePct": 12.0,
        "sessionRangePosition": 0.92,
        "drawdownFromHighPct": 1.0,
    }
    with patch(
        "app.engines.oct1_pad_location.oct1_premium_location_chase_core",
        return_value=(True, "oct1_chase"),
    ):
        assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is False


@patch("app.config.get_settings")
@patch("app.engines.pad_lane_capture.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_resolve_strict_pad_lane_oct_paper_exec_bypass_at_base(
    mock_ict,
    mock_pad,
    mock_cfg,
):
    from app.engines.pad_lane_capture import resolve_strict_pad_lane_for_entry
    from app.models.schemas import SymbolSnapshot

    s = _replica()
    mock_pad.return_value = s
    mock_ict.return_value = s
    mock_cfg.return_value = s
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-10-15T09:25:00+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=80.0,
        spot=22500.0,
        atmStrike=22500.0,
    )
    alert = {
        "tier": "ELITE",
        "explosionScore": 92.0,
        "side": "CALL",
        "localBaseMovePct": 12.0,
        "sessionRangePosition": 0.35,
        "firstLift": True,
        "armedBaseLaunch": True,
    }
    event = MagicMock(tier="ELITE", explosion_score=92.0)
    with patch(
        "app.engines.ict_breakout_monitor.first_lift_entry_readiness",
        return_value=(False, ""),
    ):
        _pad_lane, strict = resolve_strict_pad_lane_for_entry(
            Side.CALL,
            snap,
            mode="explosion",
            explosion_event=event,
            alert=alert,
        )
    assert strict is True


def test_tier_only_without_base_lift_not_waived():
    from app.engines.live_paper_parity import oct_paper_base_first_lift_take_allowed

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 95.0,
        "side": "CALL",
        "sessionRangePosition": 0.4,
    }
    assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is False


@pytest.mark.parametrize("side,off_low_key,off_val", [("CALL", "offLowMovePct", 8.0), ("PUT", "drawdownFromHighPct", 8.0)])
def test_open_session_first_lift_lane_funnel_exec_parity_ce_pe(side, off_low_key, off_val):
    from app.engines.early_radar_pad_capture import building_coil_pad_live_blocked
    from app.engines.live_paper_parity import (
        oct_open_session_first_lift_lane_active,
        oct_paper_base_first_lift_take_allowed,
        oct_paper_exec_strict_bypass,
        oct_paper_funnel_readiness_waived,
    )

    s = _replica(oct_paper_open_first_lift_min_score=84.0)
    alert = {
        "tier": "ELITE",
        "explosionScore": 90.0,
        "side": side,
        "sessionRangePosition": 0.38,
        "velocity3s": 5.0,
        off_low_key: off_val,
        "buildingCoilPadArmed": True,
        "localBaseMovePct": 18.0,
    }
    with patch("app.engines.session_timing.in_open_premium_window", return_value=True):
        if side == "PUT":
            with patch(
                "app.engines.put_slide_ce_mirror.put_slide_pad_context", return_value=True
            ):
                assert oct_open_session_first_lift_lane_active(alert, settings=s) is True
                assert oct_paper_funnel_readiness_waived(alert, settings=s) is True
                assert oct_paper_exec_strict_bypass(alert, settings=s) is True
                assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True
                blocked, reason = building_coil_pad_live_blocked(alert, settings=s)
                assert blocked is False
                assert reason == ""
        else:
            assert oct_open_session_first_lift_lane_active(alert, settings=s) is True
            assert oct_paper_funnel_readiness_waived(alert, settings=s) is True
            assert oct_paper_exec_strict_bypass(alert, settings=s) is True
            blocked, reason = building_coil_pad_live_blocked(alert, settings=s)
            assert blocked is False


def test_open_session_off_low_allows_moderate_session_position_not_extended_chase():
    from app.engines.live_paper_parity import oct_paper_base_first_lift_take_allowed

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 92.0,
        "side": "CALL",
        "offLowMovePct": 10.0,
        "localBaseMovePct": 13.5,
        "sessionRangePosition": 0.72,
    }
    with patch(
        "app.engines.oct1_pad_location.oct1_premium_location_chase_core",
        return_value=(True, "oct1_chase"),
    ):
        assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True


@pytest.mark.parametrize(
    "entry_clock,side,local,off_low",
    [
        ("10:31", "CALL", 13.5, 8.0),
        ("11:40", "PUT", 11.0, 0.0),
        ("09:50", "CALL", 13.5, 7.0),
    ],
)
def test_oct1_all_session_first_lift_lane_matches_eod_trades(
    entry_clock, side, local, off_low
):
    """Oct 1 paper took ELITE base lifts outside 09:45 open window (e.g. 09:50, 10:31, 11:40)."""
    from app.engines.live_paper_parity import (
        oct_paper_base_first_lift_take_allowed,
        oct_paper_session_first_lift_lane_active,
    )

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 90.0,
        "side": side,
        "localBaseMovePct": local,
        "sessionRangePosition": 0.42,
        "velocity3s": 4.0,
    }
    if side == "CALL":
        alert["offLowMovePct"] = off_low
    else:
        alert["drawdownFromHighPct"] = 8.0
    with patch("app.engines.session_timing.in_open_premium_window", return_value=False):
        if side == "PUT":
            with patch(
                "app.engines.put_slide_ce_mirror.put_slide_pad_context", return_value=True
            ):
                assert oct_paper_session_first_lift_lane_active(alert, settings=s) is True
                assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True
        else:
            assert oct_paper_session_first_lift_lane_active(alert, settings=s) is True
            assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_post_open_window_first_lift_not_late_chase(side):
    """After 09:45, pad lift with high session range position is not auto-rejected."""
    from app.engines.live_paper_parity import (
        oct_paper_base_first_lift_take_allowed,
        oct_paper_elite_rip_context,
        oct_paper_session_first_lift_lane_active,
    )

    s = _replica()
    alert = {
        "tier": "ELITE",
        "explosionScore": 92.0,
        "side": side,
        "localBaseMovePct": 12.0,
        "sessionRangePosition": 0.62,
        "armedBaseLaunch": True,
        "velocity3s": 5.0,
        "drawdownFromHighPct": 18.0,
    }
    if side == "CALL":
        alert["offLowMovePct"] = 3.0
        alert["drawdownFromHighPct"] = -12.0
    with patch("app.engines.session_timing.in_open_premium_window", return_value=False):
        if side == "PUT":
            with patch(
                "app.engines.put_slide_ce_mirror.put_slide_pad_context", return_value=True
            ):
                assert oct_paper_session_first_lift_lane_active(alert, settings=s) is True
                assert oct_paper_elite_rip_context(alert, settings=s) is True
                assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True
        else:
            assert oct_paper_session_first_lift_lane_active(alert, settings=s) is True
            assert oct_paper_elite_rip_context(alert, settings=s) is True
            assert oct_paper_base_first_lift_take_allowed(alert, settings=s) is True


def test_session_timing_oct_paper_first_lift_open_minute():
    from app.engines.session_timing import oct_paper_first_lift_entry_allowed_for_candidate

    s = _replica(entry_earliest_hour=9, entry_earliest_minute=16)
    alert = {
        "tier": "ELITE",
        "explosionScore": 90.0,
        "side": "CALL",
        "localBaseMovePct": 13.0,
        "offLowMovePct": 8.0,
        "sessionRangePosition": 0.4,
        "velocity3s": 5.0,
    }
    with patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        with patch("app.engines.session_timing._minutes_now", return_value=9 * 60 + 15):
            ok, reason = oct_paper_first_lift_entry_allowed_for_candidate(
                alert, settings=s,
            )
            assert ok is True, reason
            assert reason == "oct_paper_first_lift_open_minute"


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
