"""Hard block for vertical premium chase at session high (CE + PE)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.live_entry_score import live_entry_score_blocks_entry
from app.engines.premium_vertical_chase_guard import premium_vertical_chase_blocks_entry
from app.models.schemas import PremiumChart, Side
from tests.mock_defaults import settings_mock


def _symmetric_settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.premium_vertical_chase_block_enabled = True
    s.premium_vertical_chase_legacy_profile_only = True
    s.live_entry_score_gate_enabled = True
    s.live_entry_score_replace_candidate_score = True
    s.live_entry_score_min_elite = 46.0
    s.live_entry_score_min_exploding = 42.0
    s.live_entry_score_min_default = 38.0
    return s


def _candidate(side=Side.PUT, *, alert=None, pretrade=None):
    return SimpleNamespace(
        symbol="SENSEX",
        side=side,
        strike=72500.0,
        score=260.0,
        tier="ELITE",
        mode="explosion",
        alert=alert or {},
        pretrade_meta=pretrade or {},
        explosion_event=None,
        liveEntryScoreMeta={},
    )


def test_blocks_sep30_style_put_chase_at_high():
    settings = _symmetric_settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=92.4,
        drawdownFromHighPct=0.0,
    )
    cand = _candidate(
        alert={
            "explosionScore": 100.0,
            "premium": 282.78,
            "sessionPeakPremium": 285.0,
            "sessionLowPremium": 200.0,
            "tier": "ELITE",
        },
    )
    with patch(
        "app.engines.premium_vertical_chase_guard.get_settings",
        return_value=settings,
    ):
        blocked, reason, meta = premium_vertical_chase_blocks_entry(
            cand, None, premium_chart=chart, settings=settings,
        )
    assert blocked is True
    assert reason == "premium_vertical_chase_at_high"
    assert meta["premiumChaseBlock"]["premiumMomentum5Pct"] == 92.4


def test_allows_call_chase_when_pullback_from_high():
    settings = _symmetric_settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=90.0,
        drawdownFromHighPct=-15.0,
    )
    cand = _candidate(side=Side.CALL)
    with patch(
        "app.engines.premium_vertical_chase_guard.get_settings",
        return_value=settings,
    ):
        blocked, reason, _ = premium_vertical_chase_blocks_entry(
            cand, None, premium_chart=chart, settings=settings,
        )
    assert blocked is False
    assert reason == "ok"


def test_allows_at_structural_base_despite_hot_mom():
    settings = _symmetric_settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=50.0,
        drawdownFromHighPct=0.0,
    )
    cand = _candidate(
        pretrade={
            "causalRanking": {
                "localBaseMovePct": 12.0,
                "ictBaseArmed": True,
                "firstLift": True,
            },
        },
    )
    with patch(
        "app.engines.premium_vertical_chase_guard.get_settings",
        return_value=settings,
    ):
        blocked, reason, meta = premium_vertical_chase_blocks_entry(
            cand, None, premium_chart=chart, settings=settings,
        )
    assert blocked is False
    assert meta.get("premiumChaseBypass") in (
        "structural_base",
        "new_base_moment",
        "first_lift_entry_ready",
    )


def test_live_entry_wire_blocks_chase():
    settings = _symmetric_settings()
    settings.live_execution_trade_score_enabled = True
    settings.live_execution_trade_score_dump_penalty = 45.0
    settings.live_execution_trade_score_mom_factor = 8.0
    settings.live_entry_score_negative_v3_penalty_per_point = 2.0
    settings.live_entry_score_negative_v3_deadband = 0.55
    settings.live_entry_score_high_radar_soft_penalty_min = 94.0
    settings.live_entry_score_high_radar_penalty_scale = 0.45
    settings.live_entry_score_dump_cap = 42.0
    settings.live_entry_score_chase_max_range_position = 0.58
    settings.live_entry_score_chase_max_velocity_3s = 0.0
    settings.live_entry_score_chase_range_penalty_scale = 90.0
    settings.live_entry_score_chase_hot_v3_extended_spike_enabled = True
    settings.premium_post_spike_dump_min_drawdown_pct = 12.0
    settings.premium_post_spike_dump_min_spike_run_pct = 35.0
    settings.premium_post_spike_dump_near_low_frac = 0.18
    settings.premium_post_spike_dump_min_velocity_3s = -0.15
    settings.premium_post_spike_dump_min_velocity_9s = -0.25

    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=92.0,
        drawdownFromHighPct=0.0,
    )
    cand = _candidate(
        alert={
            "explosionScore": 100.0,
            "premium": 280.0,
            "sessionPeakPremium": 282.0,
            "sessionLowPremium": 190.0,
            "tier": "ELITE",
        },
    )
    with patch("app.engines.live_entry_score.get_settings", return_value=settings):
        blocked, reason, _ = live_entry_score_blocks_entry(
            cand, None, premium_chart=chart,
        )
    assert blocked is True
    assert reason == "premium_vertical_chase_at_high"
