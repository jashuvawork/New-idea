"""Replica must keep structural pad lane without post-Oct5 generic waivers or bare index flip."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.live_entry_score import live_entry_score_blocks_entry
from app.engines.live_paper_parity import structural_pad_entry_lane_active
from app.engines.premium_filter import explosion_alert_premium_tradeable
from app.engines.rally_capture import explosion_near_miss_waive
from app.models.schemas import AutoTraderState, MarketPhase, PremiumChart, SymbolSnapshot
from tests.mock_defaults import settings_mock


def _replica(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        live_paper_parity_enabled=True,
        oct_paper_replica_enabled=True,
        live_paper_parity_pad_entry_guard_enabled=False,
        aggressive_min_explosion_score=45.0,
        oct_paper_slide_premium_waiver_enabled=True,
        **kwargs,
    )


def _frozen_loosening(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        live_paper_parity_enabled=True,
        oct_paper_replica_enabled=False,
        aggressive_min_explosion_score=45.0,
        **kwargs,
    )


def test_replica_does_not_waive_generic_near_miss_prefixes():
    s = _replica()
    alert = {"tier": "ELITE", "explosionScore": 88.0, "side": "PUT", "strike": 72200.0}
    assert not explosion_near_miss_waive(
        alert,
        readiness_reason="premium_out_of_band",
        settings=s,
    )
    assert not explosion_near_miss_waive(
        alert,
        readiness_reason="explosion_score_below_min",
        settings=s,
    )


def test_loosening_still_waives_generic_near_miss_prefixes():
    s = _frozen_loosening()
    alert = {"tier": "ELITE", "explosionScore": 88.0, "side": "PUT", "strike": 72200.0}
    assert explosion_near_miss_waive(
        alert,
        readiness_reason="premium_out_of_band",
        settings=s,
    )


@patch(
    "app.engines.premium_filter.oct_paper_slide_explosion_context_armed",
    return_value=True,
)
def test_replica_call_premium_oob_not_waived_on_index_flip_only(_slide_ctx):
    s = _replica()
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22800.0,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "peakMovePct": 45.0,
        "premium": 420.0,
        "localBaseMovePct": 50.0,
        "offLowMovePct": 1.0,
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 10, 15, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22850.0,
        atmStrike=22850.0,
    )
    assert not explosion_alert_premium_tradeable(
        420.0,
        peak_move_pct=45.0,
        snap=snap,
        alert=alert,
        state=AutoTraderState(),
        settings=s,
    )


@patch(
    "app.engines.live_paper_parity.oct_paper_structural_pad_context",
    return_value=False,
)
def test_replica_flip_call_pad_lane_fails_closed_without_session_range_position(
    _pad_ctx,
):
    s = _replica()
    evidence = {
        "side": "CALL",
        "tier": "ELITE",
        "explosionScore": 100.0,
        "momentType": "flip_v_rip",
        "offLowMovePct": 12.0,
        "localBaseMovePct": 8.0,
    }
    with patch(
        "app.engines.chop_worst_flip_capture.flip_structural_evidence",
        return_value=True,
    ):
        assert not structural_pad_entry_lane_active(evidence, settings=s)


@patch(
    "app.engines.live_paper_parity.oct_paper_structural_pad_context",
    return_value=False,
)
def test_replica_flip_call_pad_lane_blocks_at_session_high(_pad_ctx):
    s = _replica()
    evidence = {
        "side": "CALL",
        "tier": "ELITE",
        "explosionScore": 100.0,
        "momentType": "flip_v_rip",
        "offLowMovePct": 12.0,
        "localBaseMovePct": 8.0,
        "sessionRangePosition": 0.92,
        "drawdownFromHighPct": -2.0,
    }
    with patch(
        "app.engines.chop_worst_flip_capture.flip_structural_evidence",
        return_value=True,
    ):
        assert not structural_pad_entry_lane_active(evidence, settings=s)


@patch("app.engines.live_entry_score.compute_live_entry_score")
def test_replica_still_runs_vertical_chase_guard(mock_compute):
    from types import SimpleNamespace

    s = _replica(
        live_entry_score_gate_enabled=True,
        premium_vertical_chase_block_enabled=True,
        live_entry_score_min_elite=52.0,
    )
    mock_compute.return_value = (40.0, {"liveEntryScore": 40.0})
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=92.0,
        drawdownFromHighPct=0.0,
    )
    candidate = SimpleNamespace(
        tier="ELITE",
        liveEntryScore=40.0,
        alert={
            "tier": "ELITE",
            "explosionScore": 100.0,
            "premium": 280.0,
            "sessionPeakPremium": 282.0,
            "sessionLowPremium": 190.0,
        },
        explosion_event=None,
    )
    with patch("app.engines.live_entry_score.get_settings", return_value=s):
        blocked, reason, meta = live_entry_score_blocks_entry(
            candidate, None, premium_chart=chart,
        )
    assert blocked is True
    assert reason == "premium_vertical_chase_at_high"
    assert meta.get("octPaperLiveEntryScoreGateSkipped") is not True
