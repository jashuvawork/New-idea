"""Index session monitoring HUD payload."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.index_session_narrative import index_session_monitoring_summary

IST = ZoneInfo("Asia/Kolkata")


def _snap(symbol: str, alerts: list):
    return SimpleNamespace(
        symbol=symbol,
        dataAvailable=True,
        spot=100.0,
        explosionAlerts=alerts,
    )


@patch("app.engines.index_session_narrative.index_session_narrative_summary")
def test_monitoring_prefers_near_base_aligned_picks(mock_narr):
    mock_narr.return_value = {
        "enabled": True,
        "symbols": {
            "SENSEX": {
                "dominantLeg": "SLIDE",
                "bullishOptionSide": "PUT",
                "rallyPoints": 40,
                "slidePoints": 180,
            },
        },
    }
    snapshots = {
        "SENSEX": _snap(
            "SENSEX",
            [
                {"side": "PUT", "strike": 81800, "explosionScore": 90, "localBaseMovePct": 8.0, "tier": "EXPLODING"},
                {"side": "PUT", "strike": 81700, "explosionScore": 95, "localBaseMovePct": 35.0, "tier": "ELITE"},
                {"side": "CALL", "strike": 82000, "explosionScore": 99, "localBaseMovePct": 5.0, "tier": "ELITE"},
            ],
        ),
    }
    flip_stub = {"riskLevel": "NONE", "predictedBullishOptionSide": "PUT"}
    with patch(
        "app.engines.index_slide_capture_lane.index_slide_capture_lane_status",
        return_value=(True, "ok", {"dominantTrend": "SLIDE"}),
    ), patch(
        "app.engines.index_imminent_flip.index_imminent_flip_assessment",
        return_value=flip_stub,
    ):
        out = index_session_monitoring_summary(
            snapshots,
            settings=Settings(),
            when=datetime(2026, 11, 13, 11, 0, tzinfo=IST),
        )
    picks = out["symbols"]["SENSEX"]["alignedBookPicks"]
    assert len(picks) == 2
    assert all(p["side"] == "PUT" for p in picks)
    assert picks[0]["strike"] == 81800
    assert picks[0]["nearBase676"] is True
