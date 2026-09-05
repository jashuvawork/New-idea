"""Tests for same-moment Elite dedup — live selector + EOD parity."""

from app.engines.elite_moment_dedup import (
    dedupe_same_moment_candidates,
    dedupe_same_moment_top1,
    parse_moment_key,
)
from app.models.schemas import Side


class _Candidate:
    def __init__(
        self,
        *,
        symbol: str,
        side: str,
        strike: float,
        elite_score: float,
        setup_priority: int = 0,
        rank_score: float = 0.0,
        armed_at: str = "",
    ):
        self.symbol = symbol
        self.side = Side(side)
        self.strike = strike
        self.alert = {"ictBaseArmedAt": armed_at} if armed_at else {}
        self.pretrade_meta = {
            "topMomentGate": {
                "eliteAssessment": {
                    "eliteScore": elite_score,
                    "setupPriority": setup_priority,
                },
            },
            "causalRanking": {"rankScore": rank_score},
        }


def test_parse_moment_key_second_precision():
    assert parse_moment_key("2026-09-03T10:15:42.123456+05:30") == "2026-09-03T10:15:42"


def test_dedupe_same_moment_top1_keeps_highest_score():
    rows = [
        {"momentKey": "2026-09-03T10:15:42", "eliteScore": 91.0, "setupPriority": 1, "ts": "a"},
        {"momentKey": "2026-09-03T10:15:42", "eliteScore": 96.0, "setupPriority": 1, "ts": "b"},
        {"momentKey": "2026-09-03T10:16:00", "eliteScore": 90.0, "setupPriority": 1, "ts": "c"},
    ]
    out = dedupe_same_moment_top1(rows)
    assert len(out) == 2
    scores = sorted(r["eliteScore"] for r in out)
    assert scores == [90.0, 96.0]


def test_dedupe_same_moment_candidates_live():
    armed = "2026-09-03T10:15:42+05:30"
    candidates = [
        _Candidate(symbol="NIFTY", side="CALL", strike=24000, elite_score=92.0, armed_at=armed),
        _Candidate(symbol="SENSEX", side="CALL", strike=76800, elite_score=97.0, armed_at=armed),
    ]
    out = dedupe_same_moment_candidates(candidates)
    assert len(out) == 1
    assert out[0].symbol == "SENSEX"
