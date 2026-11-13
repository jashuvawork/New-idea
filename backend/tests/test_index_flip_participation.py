"""Participation-led index flip — breadth, PCR, book flow (CE/PE symmetric)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.index_flip_participation import index_flip_participation_assessment
from app.engines.index_imminent_flip import (
    index_imminent_flip_assessment,
    index_imminent_flip_rank_adjustment,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Orderflow,
    Regime,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.index_imminent_flip_enabled = True
    s.index_flip_participation_enabled = True
    s.index_session_dominant_trend_enabled = True
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    return s


def _snap(
    *,
    breadth: str = "NEUTRAL",
    pcr: float = 1.0,
    mom5: float = 0.02,
    alerts: list | None = None,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25100.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        pcr=pcr,
        breadth=Breadth(bias=breadth, score=55, aligned=breadth != "NEUTRAL"),
        orderflow=Orderflow(deltaVelocity=-30.0),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=mom5),
        explosionAlerts=alerts or [],
    )


@patch(
    "app.engines.best_side_selection.side_velocity_metrics",
    return_value={
        "callScore": 40.0,
        "putScore": 95.0,
        "callVelocity3s": 0.01,
        "putVelocity3s": 0.12,
        "dominantSide": "PUT",
    },
)
def test_participation_put_leading_from_breadth_pcr_book(_m):
    settings = _settings()
    alerts = [
        {
            "side": "PUT",
            "strike": 25100.0,
            "explosionScore": 90.0,
            "orderflowConfirmed": True,
        },
    ]
    snap = _snap(breadth="BEARISH", pcr=1.25, alerts=alerts)
    out = index_flip_participation_assessment(snap, settings=settings)
    assert out["leadingOptionSide"] == "PUT"
    assert out["confidence"] >= 0.5
    assert "breadth_bearish" in out["reasons"]


@patch("app.engines.pe_win_ce_mirror.call_rally_unlock_armed", return_value=(True, "ok", {}))
@patch("app.engines.put_slide_ce_mirror.put_slide_unlock_armed", return_value=(False, "", {}))
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 120.0, "slidePoints": 35.0, "momentum5Pct": 0.02},
)
@patch(
    "app.engines.best_side_selection.side_velocity_metrics",
    return_value={
        "callScore": 30.0,
        "putScore": 100.0,
        "callVelocity3s": 0.0,
        "putVelocity3s": 0.15,
        "dominantSide": "PUT",
    },
)
def test_rally_leg_participation_predicts_slide_before_spot(_m_book, _m1, _m2, _m3):
    """RALLY dominant but sellers/participants leaning PUT → flip assessment leads SLIDE."""
    settings = _settings()
    snap = _snap(
        breadth="BEARISH",
        pcr=1.3,
        mom5=0.01,
        alerts=[
            {
                "side": "PUT",
                "strike": 25150.0,
                "explosionScore": 120.0,
                "orderflowConfirmed": True,
            },
        ],
    )
    with patch("app.engines.index_imminent_flip._index_velocity_3s", return_value=0.0):
        out = index_imminent_flip_assessment("NIFTY", snap, None, settings=settings)
    assert out["dominantLeg"] == "RALLY"
    assert out["predictedLeg"] == "SLIDE"
    assert out["predictedBullishOptionSide"] == "PUT"
    assert "participation_vs_dominant_leg" in out["reasons"]
    assert out["riskLevel"] in ("WATCH", "IMMINENT", "CONTESTED")


@patch("app.engines.pe_win_ce_mirror.call_rally_unlock_armed", return_value=(True, "ok", {}))
@patch("app.engines.put_slide_ce_mirror.put_slide_unlock_armed", return_value=(False, "", {}))
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 100.0, "slidePoints": 20.0, "momentum5Pct": 0.05},
)
@patch(
    "app.engines.best_side_selection.side_velocity_metrics",
    return_value={
        "callScore": 20.0,
        "putScore": 90.0,
        "callVelocity3s": 0.0,
        "putVelocity3s": 0.1,
        "dominantSide": "PUT",
    },
)
def test_call_penalized_when_participation_leads_put_on_rally(_mb, _m1, _m2, _m3):
    settings = _settings()
    snap = _snap(breadth="BEARISH", pcr=1.2)
    snapshots = {"NIFTY": snap}
    call_c = SimpleNamespace(symbol="NIFTY", side="CALL", snap=snap)
    with patch("app.engines.index_imminent_flip._index_velocity_3s", return_value=0.0):
        adj = index_imminent_flip_rank_adjustment(
            call_c, snapshots, AutoTraderState(), settings=settings,
        )
    # Still dominant-aligned → soft rank (#939): no hard block; may be 0 not negative
    assert adj <= 0.0
