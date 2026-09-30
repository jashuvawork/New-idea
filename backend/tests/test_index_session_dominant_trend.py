"""Paired CE/PE tests for intraday dominant trend read model."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.index_session_dominant_trend import (
    index_session_dominant_trend,
    index_trend_rank_adjustment,
    reset_index_session_dominant_trend_for_tests,
    side_aligns_with_dominant_trend,
)
from tests.mock_defaults import settings_mock
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(symbol: str = "NIFTY", mom5: float = 0.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="NEUTRAL", score=50, aligned=False),
        spotChart=SpotChart(direction="NEUTRAL", emaBias="NEUTRAL", momentum5Pct=mom5),
    )


def _symmetric_settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.index_session_dominant_trend_enabled = True
    return s


def test_rally_leg_dominant_rally_only_call_aligned():
    with patch(
        "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
        return_value=(False, "", {}),
    ), patch(
        "app.engines.index_rally_side_flip.index_rally_metrics",
        return_value={"rallyPoints": 40.0, "slidePoints": 5.0},
    ):
        trend, meta = index_session_dominant_trend(
            "NIFTY", _snap(), AutoTraderState(), settings=_symmetric_settings(),
        )
    assert trend == "RALLY"
    assert meta["dominantTrend"] == "RALLY"
    assert side_aligns_with_dominant_trend("CALL", trend) is True
    assert side_aligns_with_dominant_trend("PUT", trend) is False


def test_slide_leg_dominant_slide_only_put_aligned():
    with patch(
        "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
        return_value=(False, "", {}),
    ), patch(
        "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.index_rally_side_flip.index_rally_metrics",
        return_value={"rallyPoints": 5.0, "slidePoints": 45.0},
    ):
        trend, _ = index_session_dominant_trend(
            "NIFTY", _snap(), AutoTraderState(), settings=_symmetric_settings(),
        )
    assert trend == "SLIDE"
    assert side_aligns_with_dominant_trend("PUT", trend) is True
    assert side_aligns_with_dominant_trend("CALL", trend) is False


def test_both_armed_tie_break_rally_by_points():
    settings = _symmetric_settings()
    settings.index_trend_opposite_side_flip_margin_pts = 20.0
    with patch(
        "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.index_rally_side_flip.index_rally_metrics",
        return_value={"rallyPoints": 80.0, "slidePoints": 50.0},
    ):
        trend, meta = index_session_dominant_trend(
            "NIFTY", _snap(), AutoTraderState(), settings=settings,
        )
    assert trend == "RALLY"
    assert meta.get("indexTrendFlip") == "rally_dominant"


def test_flip_changes_rank_favors_new_leg():
    reset_index_session_dominant_trend_for_tests()
    settings = _symmetric_settings()
    snap = _snap()
    state = AutoTraderState()
    snapshots = {"NIFTY": snap}

    call_cand = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        snap=snap,
        score=50.0,
    )
    put_cand = SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        snap=snap,
        score=50.0,
    )

    rally_patch = patch(
        "app.engines.index_session_dominant_trend._resolve_trend_arms",
        return_value=(True, False, {"indexTrendMetrics": {}}),
    )
    slide_patch = patch(
        "app.engines.index_session_dominant_trend._resolve_trend_arms",
        return_value=(False, True, {"indexTrendMetrics": {}}),
    )

    with rally_patch:
        call_adj_rally = index_trend_rank_adjustment(call_cand, snapshots, state, settings=settings)
        put_adj_rally = index_trend_rank_adjustment(put_cand, snapshots, state, settings=settings)

    assert call_adj_rally > put_adj_rally

    with slide_patch:
        call_adj_slide = index_trend_rank_adjustment(call_cand, snapshots, state, settings=settings)
        put_adj_slide = index_trend_rank_adjustment(put_cand, snapshots, state, settings=settings)

    assert put_adj_slide > call_adj_slide
