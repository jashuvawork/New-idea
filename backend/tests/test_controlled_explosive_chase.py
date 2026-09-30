"""Tier A/B/C controlled explosive chase (symmetric CE + PE)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.best_trade_policy import (
    _mid_rip_best_trade_signals,
    best_trade_base_rank_adjustment,
)
from app.engines.controlled_explosive_chase import (
    classify_best_trade_chase_tier,
    controlled_explosive_chase_allowed,
)
from app.engines.premium_vertical_chase_guard import premium_vertical_chase_blocks_entry
from app.models.schemas import PremiumChart, Side
from tests.mock_defaults import settings_mock


def _settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.best_trade_base_first_enabled = True
    s.best_trade_new_base_moment_enabled = True
    s.best_trade_controlled_chase_enabled = True
    s.best_trade_controlled_mid_rip_enabled = True
    s.best_trade_disable_mid_rip_when_base_first = True
    s.premium_vertical_chase_block_enabled = True
    s.premium_vertical_chase_legacy_profile_only = True
    s.premium_vertical_chase_allow_controlled_waiver = True
    s.best_trade_near_base_max_local_pct = 20.0
    s.best_trade_controlled_chase_max_local_pct = 32.0
    return s


def _candidate(
    side=Side.PUT,
    *,
    alert=None,
    pretrade=None,
    live_meta=None,
):
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
        liveEntryScoreMeta=live_meta or {},
        snap=None,
        state=None,
    )


def test_tier_a_elite_base_ready_low_local():
    s = _settings()
    cand = _candidate(
        alert={"momentType": "ELITE_BASE_READY", "localBaseMovePct": 12.0, "tier": "ELITE"},
        pretrade={"causalRanking": {"evidence": {"localBaseMovePct": 12.0}}},
    )
    tier, meta = classify_best_trade_chase_tier(cand, settings=s)
    assert tier == "A"
    assert meta["localMovePct"] == 12.0
    assert best_trade_base_rank_adjustment(cand, settings=s) > 10


def test_tier_b_controlled_rip_call_and_put():
    s = _settings()
    for side in (Side.CALL, Side.PUT):
        cand = _candidate(
            side=side,
            alert={
                "localBaseMovePct": 28.0,
                "buildingRipReady": True,
                "tier": "ELITE",
                "velocity3s": 4.0,
            },
            pretrade={
                "causalRanking": {
                    "eliteScore": 95.0,
                    "evidence": {"localBaseMovePct": 28.0, "buildingRipReady": True},
                },
            },
        )
        ok, reason, meta = controlled_explosive_chase_allowed(cand, settings=s)
        assert ok is True, (side, reason, meta)
        assert meta["controlledChaseTier"] == "B"
        assert best_trade_base_rank_adjustment(cand, settings=s) > 0


def test_tier_c_sep30_style_late_chase():
    s = _settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=92.4,
        drawdownFromHighPct=0.0,
    )
    cand = _candidate(
        alert={
            "explosionScore": 100.0,
            "localBaseMovePct": 55.0,
            "premium": 282.78,
            "sessionPeakPremium": 285.0,
            "sessionLowPremium": 200.0,
            "tier": "ELITE",
        },
        pretrade={
            "causalRanking": {
                "eliteScore": 100.0,
                "evidence": {"localBaseMovePct": 55.0},
            },
        },
    )
    tier, _ = classify_best_trade_chase_tier(cand, settings=s)
    assert tier == "C"
    with patch(
        "app.engines.premium_vertical_chase_guard.get_settings",
        return_value=s,
    ):
        blocked, reason, meta = premium_vertical_chase_blocks_entry(
            cand, None, premium_chart=chart, settings=s,
        )
    assert blocked is True
    assert reason == "premium_vertical_chase_at_high"
    assert meta.get("controlledChaseTier") == "C"


def test_tier_b_waiver_at_high_when_not_extended_local():
    s = _settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=90.0,
        drawdownFromHighPct=0.0,
    )
    cand = _candidate(
        side=Side.CALL,
        alert={
            "localBaseMovePct": 28.0,
            "buildingRipReady": True,
            "tier": "ELITE",
            "velocity3s": 5.0,
        },
        pretrade={
            "causalRanking": {
                "eliteScore": 95.0,
                "evidence": {"localBaseMovePct": 28.0, "buildingRipReady": True},
            },
        },
    )
    with patch(
        "app.engines.premium_vertical_chase_guard.get_settings",
        return_value=s,
    ):
        blocked, reason, meta = premium_vertical_chase_blocks_entry(
            cand, None, premium_chart=chart, settings=s,
        )
    assert blocked is False
    assert meta.get("premiumChaseBypass") == "premium_vertical_chase_controlled_rip_waiver"


def test_new_base_moment_tier_a_after_extension():
    s = _settings()
    cand = _candidate(
        alert={
            "momentType": "ict_base_armed",
            "localBaseMovePct": 18.0,
            "ictBaseArmed": True,
        },
        pretrade={
            "causalRanking": {
                "evidence": {
                    "localBaseMovePct": 18.0,
                    "ictBaseArmed": True,
                    "momentType": "ict_base_armed",
                },
            },
        },
    )
    tier, _ = classify_best_trade_chase_tier(cand, settings=s)
    assert tier == "A"


def test_mid_rip_only_when_tier_b_under_base_first():
    s = _settings()
    off_base = {
        "fastVerticalBurst": True,
        "velocity3s": 5.0,
        "tier": "ELITE",
        "localBaseMovePct": 55.0,
    }
    assert _mid_rip_best_trade_signals(
        off_base, {"eliteScore": 95}, tier="ELITE", settings=s,
    ) is False

    tier_b_alert = {
        "buildingRipReady": True,
        "velocity3s": 5.0,
        "tier": "ELITE",
        "localBaseMovePct": 28.0,
    }
    assert _mid_rip_best_trade_signals(
        tier_b_alert,
        {"eliteScore": 95, "evidence": {"localBaseMovePct": 28.0, "buildingRipReady": True}},
        tier="ELITE",
        settings=s,
    ) is True
