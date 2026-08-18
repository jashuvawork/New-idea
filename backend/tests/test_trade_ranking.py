"""Deterministic causal ranking regressions for the 2026-08-17 trade patterns."""

from types import SimpleNamespace

import pytest

from app.engines.trade_ranking import rank_trade_evidence, ranking_sort_key
from app.engines.trade_selector import EntryCandidate, rank_candidates_for_selection
from app.models.schemas import Side, StrategyType


AUG17_PATTERNS = [
    (
        "24250 CE peak capture",
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 89.8,
            "tqs": 49.6,
            "chartConfidence": 77.1,
        },
        "B",
    ),
    (
        "24300 CE positive local-base move",
        {
            "mode": "explosion",
            "tier": "EXPLODING",
            "explosionScore": 66.1,
            "tqs": 49.6,
            "chartConfidence": 74.9,
            "velocity3s": 2.08,
            "localBaseMovePct": 27.91,
        },
        "B",
    ),
    (
        "24400 CE negative-v3 extension",
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 100.0,
            "tqs": 51.6,
            "chartConfidence": 75.3,
            "velocity3s": -1.0,
            "localBaseMovePct": 64.4,
            "flatThenVertical": True,
            "timingAssessment": "FAILED_LAUNCH",
            "timingAction": "block",
        },
        "REJECT",
    ),
    (
        "24300 CE exhausted re-entry",
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 76.4,
            "tqs": 50.5,
            "chartConfidence": 74.4,
            "exhaustedReentry": True,
        },
        "REJECT",
    ),
    (
        "24350 CE positive local-base move",
        {
            "mode": "explosion",
            "tier": "EXPLODING",
            "explosionScore": 79.8,
            "tqs": 53.4,
            "chartConfidence": 66.5,
            "velocity3s": 2.46,
            "localBaseMovePct": 21.04,
        },
        "B",
    ),
]


@pytest.mark.parametrize(("name", "evidence", "expected_grade"), AUG17_PATTERNS)
def test_aug17_historical_patterns_receive_honest_causal_grades(
    name, evidence, expected_grade,
):
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == expected_grade, name
    assert ranking["causalOnly"] is True
    assert "pnl" not in ranking["evidence"]


def test_negative_velocity_extended_trade_cannot_beat_clean_fresh_launch():
    failed = rank_trade_evidence(AUG17_PATTERNS[2][1])
    fresh = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 82.0,
            "tqs": 52.0,
            "chartConfidence": 74.0,
            "velocity3s": 2.4,
            "velocity9s": 2.0,
            "localBaseMovePct": 19.0,
            "firstLift": True,
            "armedBaseLaunch": True,
            "flatThenVertical": True,
            "orderflowPositive": True,
            "timingAssessment": "GOOD",
        }
    )
    assert failed["grade"] == "REJECT"
    assert failed["topRankEligible"] is False
    assert failed["fullSleeveEligible"] is False
    assert fresh["grade"] == "S"
    assert fresh["topRankEligible"] is True
    assert fresh["fullSleeveEligible"] is True
    assert fresh["rankScore"] > failed["rankScore"]


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_causal_ranking_is_ce_pe_symmetric(side):
    evidence = {
        "side": side,
        "mode": "explosion",
        "tier": "ELITE",
        "explosionScore": 82.0,
        "tqs": 52.0,
        "chartConfidence": 74.0,
        "velocity3s": 2.4,
        "velocity9s": 2.0,
        "localBaseMovePct": 19.0,
        "firstLift": True,
        "armedBaseLaunch": True,
        "orderflowPositive": True,
    }
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "S"
    assert ranking["rankScore"] == 100.0


def test_future_pnl_fields_cannot_change_ranking():
    evidence = dict(AUG17_PATTERNS[1][1])
    baseline = rank_trade_evidence(evidence)
    assert rank_trade_evidence({**evidence, "pnlInr": -1_000_000}) == baseline
    assert rank_trade_evidence({**evidence, "pnlInr": 1_000_000}) == baseline


def test_same_grade_candidates_are_ordered_by_causal_rank_score():
    lower = rank_trade_evidence(AUG17_PATTERNS[0][1])
    higher = rank_trade_evidence(AUG17_PATTERNS[4][1])

    assert lower["grade"] == higher["grade"] == "B"
    assert ranking_sort_key(higher) > ranking_sort_key(lower)


def test_aug18_1040_cohort_prefers_24350_s_over_atm_a_candidates():
    s_ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "EXPLODING",
            "explosionScore": 100.0,
            "tqs": 55.6,
            "velocity3s": 3.69,
            "velocity9s": 4.13,
            "localBaseMovePct": 24.4,
            "firstLift": True,
            "armedBaseLaunch": True,
            "flatThenVertical": True,
            "orderflowPositive": True,
        }
    )
    a_24200 = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 92.0,
            "tqs": 58.0,
            "velocity3s": 1.2,
            "velocity9s": 1.1,
            "localBaseMovePct": 18.0,
            "firstLift": True,
            "flatThenVertical": True,
            "orderflowPositive": True,
        }
    )
    a_24250 = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 88.0,
            "tqs": 56.0,
            "velocity3s": 1.1,
            "velocity9s": 1.0,
            "localBaseMovePct": 17.0,
            "firstLift": True,
            "flatThenVertical": True,
            "orderflowPositive": True,
        }
    )

    def candidate(strike, score, ranking):
        return EntryCandidate(
            symbol="NIFTY",
            snap=SimpleNamespace(),
            mode="explosion",
            score=score,
            side=Side.PUT,
            strike=strike,
            premium=100.0,
            strategy_type=StrategyType.EXPLOSIVE,
            confidence=90.0,
            tqs=55.0,
            pretrade_meta={"causalRanking": ranking},
        )

    cohort = [
        candidate(24200.0, 160.0, a_24200),
        candidate(24250.0, 150.0, a_24250),
        candidate(24350.0, 90.0, s_ranking),
    ]
    ranked = rank_candidates_for_selection(cohort, lambda item: item.score)

    assert s_ranking["grade"] == "S"
    assert a_24200["grade"] == a_24250["grade"] == "A"
    assert [item.strike for item in ranked] == [24350.0, 24200.0, 24250.0]


def test_final_sort_uses_rank_score_before_legacy_score_within_grade():
    higher = {"grade": "A", "gradePriority": 3, "rankScore": 88.0}
    lower = {"grade": "A", "gradePriority": 3, "rankScore": 80.0}

    def candidate(strike, score, ranking):
        return EntryCandidate(
            symbol="NIFTY",
            snap=SimpleNamespace(),
            mode="explosion",
            score=score,
            side=Side.CALL,
            strike=strike,
            premium=100.0,
            strategy_type=StrategyType.EXPLOSIVE,
            confidence=80.0,
            tqs=55.0,
            pretrade_meta={"causalRanking": ranking},
        )

    ranked = rank_candidates_for_selection(
        [
            candidate(24200.0, 200.0, lower),
            candidate(24150.0, 50.0, higher),
        ],
        lambda item: item.score,
    )

    assert [item.strike for item in ranked] == [24150.0, 24200.0]
