"""Index imminent flip risk — contested leg + wrong-side selector penalty (CE/PE)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.index_imminent_flip import (
    index_imminent_flip_assessment,
    index_imminent_flip_rank_adjustment,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.index_imminent_flip_enabled = True
    s.index_session_dominant_trend_enabled = True
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    return s


def _snap(mom5: float = 0.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25100.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="NEUTRAL", score=50, aligned=False),
        spotChart=SpotChart(direction="NEUTRAL", momentum5Pct=mom5),
    )


@patch("app.engines.pe_win_ce_mirror.call_rally_unlock_armed", return_value=(True, "ok", {}))
@patch("app.engines.put_slide_ce_mirror.put_slide_unlock_armed", return_value=(True, "ok", {}))
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 40.0, "slidePoints": 42.0, "momentum5Pct": -0.03},
)
def test_contested_both_arms_risk(_m1, _m2, _m3):
    settings = _settings()
    out = index_imminent_flip_assessment("NIFTY", _snap(mom5=-0.03), None, settings=settings)
    assert out["contestedLeg"] is True
    assert out["riskLevel"] == "CONTESTED"
    assert out["predictedBullishOptionSide"] == "PUT"


@patch("app.engines.pe_win_ce_mirror.call_rally_unlock_armed", return_value=(False, "", {}))
@patch("app.engines.put_slide_ce_mirror.put_slide_unlock_armed", return_value=(True, "ok", {}))
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 10.0, "slidePoints": 80.0, "momentum5Pct": -0.05},
)
def test_slide_dominant_put_aligned_no_wrong_penalty(_m1, _m2, _m3):
    settings = _settings()
    snap = _snap()
    snapshots = {"NIFTY": snap}
    put_c = SimpleNamespace(symbol="NIFTY", side="PUT", snap=snap)
    with patch("app.engines.index_imminent_flip._index_velocity_3s", return_value=0.0):
        adj = index_imminent_flip_rank_adjustment(put_c, snapshots, None, settings=settings)
    assert adj >= 0


@patch("app.engines.pe_win_ce_mirror.call_rally_unlock_armed", return_value=(True, "ok", {}))
@patch("app.engines.put_slide_ce_mirror.put_slide_unlock_armed", return_value=(True, "ok", {}))
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 48.0, "slidePoints": 55.0, "momentum5Pct": -0.04},
)
def test_contested_call_wrong_side_when_predicting_slide(_m1, _m2, _m3):
    settings = _settings()
    snap = _snap(mom5=-0.04)
    snapshots = {"NIFTY": snap}
    call_c = SimpleNamespace(symbol="NIFTY", side="CALL", snap=snap)
    adj = index_imminent_flip_rank_adjustment(
        call_c, snapshots, AutoTraderState(), settings=settings,
    )
    assert adj < 0
