"""Sep 9–17 near-base shape alignment (15% pad + top-moment gate)."""

from types import SimpleNamespace

from app.engines.best_trade_policy import (
    effective_near_base_max_local_pct,
    sep917_near_base_capture_ok,
    symmetric_best_trade_at_base_capture,
)
from tests.mock_defaults import settings_mock


def _settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.best_trade_base_first_enabled = True
    s.best_trade_sep917_base_shape_align_enabled = True
    s.best_trade_sep917_near_base_max_local_pct = 15.0
    return s


def test_effective_near_base_uses_15_under_legacy_align():
    s = _settings()
    assert effective_near_base_max_local_pct(s) == 15.0


def test_sep917_near_base_matches_checklist_fixture():
    s = _settings()
    evidence = {
        "symbol": "NIFTY",
        "side": "CALL",
        "tier": "ELITE",
        "explosionScore": 92.0,
        "localBaseMovePct": 12.0,
        "ictBaseArmed": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "eliteBaseReady": True,
    }
    ok, reason = sep917_near_base_capture_ok(
        evidence, {"grade": "A", "score": 95.0}, settings=s,
    )
    assert ok is True
    assert "near_base" in reason or reason == "new_base_moment"


def test_extended_local_without_moment_rejected():
    s = _settings()
    evidence = {
        "tier": "ELITE",
        "localBaseMovePct": 18.0,
        "ictBaseArmed": True,
    }
    ok, reason = symmetric_best_trade_at_base_capture(evidence, settings=s)
    assert ok is False
    assert "not_sep917" in reason or reason


def test_rank_bonus_tier_a_at_12pct():
    s = _settings()
    from app.engines.best_trade_policy import best_trade_base_rank_adjustment

    cand = SimpleNamespace(
        alert={
            "tier": "ELITE",
            "localBaseMovePct": 12.0,
            "flatThenVertical": True,
            "activeBreakout": True,
            "armedBaseLaunch": True,
        },
        pretrade_meta={
            "causalRanking": {
                "grade": "A",
                "eliteScore": 95.0,
                "evidence": {"localBaseMovePct": 12.0},
            },
        },
        snap=None,
        mode="explosion",
    )
    assert best_trade_base_rank_adjustment(cand, settings=s) > 10
