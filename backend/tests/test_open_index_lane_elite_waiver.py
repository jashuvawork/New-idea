"""Open index lane — structural elite score waiver."""

from types import SimpleNamespace

from app.config import Settings
from app.engines.open_index_lane import open_index_lane_structural_elite_waiver
from app.models.schemas import ChartAnalysis, Side


def _candidate(*, score_via_rank: float, alert: dict, snap):
    return SimpleNamespace(
        symbol="SENSEX",
        side=Side.CALL,
        tier="ELITE",
        alert=alert,
        snap=snap,
    )


def test_lane_elite_waiver_with_continuation_stamp():
    snap = SimpleNamespace(spot=82_000.0, chartAnalysis=None)
    alert = {
        "tier": "ELITE",
        "side": "CALL",
        "symbol": "SENSEX",
        "firstLift": True,
        "indexContinuationRallyNearMissWaive": True,
    }
    cand = _candidate(score_via_rank=0, alert=alert, snap=snap)
    ranking = {"grade": "A", "rankScore": 82.0}
    ok, meta = open_index_lane_structural_elite_waiver(
        cand, alert, ranking, 82.0, 90.0, settings=Settings(),
    )
    assert ok, meta
    assert meta.get("laneEliteWaiverVia") == "index_continuation_stamp"


def test_lane_elite_waiver_rejects_low_score():
    snap = SimpleNamespace(
        spot=82_000.0,
        chartAnalysis=ChartAnalysis(
            pivots={"P": 81_900.0},
            vwap={"reclaim": "BULLISH_RECLAIM"},
        ),
    )
    alert = {"tier": "ELITE", "side": "CALL", "symbol": "SENSEX", "firstLift": True}
    cand = _candidate(score_via_rank=0, alert=alert, snap=snap)
    ok, meta = open_index_lane_structural_elite_waiver(
        cand, alert, {"grade": "A"}, 70.0, 90.0, settings=Settings(),
    )
    assert not ok
    assert meta.get("laneEliteWaiverReason") == "score_below_floor"