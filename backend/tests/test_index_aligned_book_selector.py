"""Index-leg aligned book vs off-book explosion chase (CE/PE paired)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.index_aligned_book_selector import index_aligned_book_rank_adjustment
from app.engines.index_session_narrative import aligned_explosion_book_picks
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _symmetric_settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.index_session_dominant_trend_enabled = True
    s.index_aligned_book_selector_enabled = True
    return s


def _snap(
    symbol: str = "NIFTY",
    alerts: list | None = None,
    mom5: float = -0.08,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25100.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            emaBias="BEARISH",
            momentum5Pct=mom5,
        ),
        explosionAlerts=alerts or [],
    )


def _put_alerts() -> list:
    """HUD book head only — chase strike 25200 is off this list (Nov-13 shape)."""
    return [
        {
            "side": "PUT",
            "strike": 25150.0,
            "explosionScore": 88.0,
            "localBaseMovePct": 18.8,
            "tier": "EXPLODING",
        },
        {
            "side": "PUT",
            "strike": 25100.0,
            "explosionScore": 86.0,
            "localBaseMovePct": 19.9,
            "tier": "EXPLODING",
        },
    ]


def _slide_leg_patches():
    return (
        patch(
            "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
            return_value=(False, "", {}),
        ),
        patch(
            "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
            return_value=(True, "ok", {}),
        ),
        patch(
            "app.engines.index_rally_side_flip.index_rally_metrics",
            return_value={"rallyPoints": 16.0, "slidePoints": 152.0, "momentum5Pct": -0.08},
        ),
    )


def test_aligned_book_picks_put_near_base_first():
    snap = _snap(alerts=_put_alerts())
    picks = aligned_explosion_book_picks("NIFTY", snap, "PUT", limit=3)
    assert picks[0]["strike"] == 25150.0
    assert picks[0]["nearBase676"] is True


def test_elite_off_book_gap_bypass_keeps_chase_eligible():
    settings = _symmetric_settings()
    settings.index_aligned_book_hard_require_enabled = False
    settings.index_aligned_book_elite_score_gap_bypass = 55.0
    snap = _snap(alerts=_put_alerts())
    snapshots = {"NIFTY": snap}
    state = AutoTraderState()
    p1, p2, p3 = _slide_leg_patches()
    with p1, p2, p3:
        on_book = SimpleNamespace(
            symbol="NIFTY",
            side=Side.PUT,
            strike=25150.0,
            score=88.0,
            snap=snap,
            alert={"strike": 25150, "localBaseMovePct": 18.8},
        )
        chase = SimpleNamespace(
            symbol="NIFTY",
            side=Side.PUT,
            strike=25200.0,
            score=244.0,
            snap=snap,
            alert={"strike": 25200, "localBaseMovePct": 45.0},
        )
        adj_chase = index_aligned_book_rank_adjustment(
            chase, snapshots, state, settings=settings,
        )
        adj_on = index_aligned_book_rank_adjustment(
            on_book, snapshots, state, settings=settings,
        )
    assert adj_chase == 0.0
    assert chase.score + adj_chase > on_book.score + adj_on


def test_off_book_put_penalized_on_slide_leg():
    settings = _symmetric_settings()
    settings.index_aligned_book_elite_score_gap_bypass = 200.0
    snap = _snap(alerts=_put_alerts())
    snapshots = {"NIFTY": snap}
    state = AutoTraderState()
    p1, p2, p3 = _slide_leg_patches()
    with p1, p2, p3:
        on_book = SimpleNamespace(
            symbol="NIFTY",
            side=Side.PUT,
            strike=25150.0,
            score=88.0,
            snap=snap,
            alert={"strike": 25150, "localBaseMovePct": 18.8},
        )
        chase = SimpleNamespace(
            symbol="NIFTY",
            side=Side.PUT,
            strike=25200.0,
            score=105.0,
            snap=snap,
            alert={"strike": 25200, "localBaseMovePct": 45.0},
        )
        adj_on = index_aligned_book_rank_adjustment(
            on_book, snapshots, state, settings=settings,
        )
        adj_chase = index_aligned_book_rank_adjustment(
            chase, snapshots, state, settings=settings,
        )
    assert adj_on > 0
    assert adj_chase < 0
    assert on_book.score + adj_on > chase.score + adj_chase


def test_rally_leg_call_book_bonus_mirrors_put():
    settings = _symmetric_settings()
    alerts = [
        {
            "side": "CALL",
            "strike": 25200.0,
            "explosionScore": 90.0,
            "localBaseMovePct": 15.0,
            "tier": "EXPLODING",
        },
    ]
    snap = _snap(alerts=alerts, mom5=0.1)
    snapshots = {"NIFTY": snap}
    with patch(
        "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
        return_value=(False, "", {}),
    ), patch(
        "app.engines.index_rally_side_flip.index_rally_metrics",
        return_value={"rallyPoints": 80.0, "slidePoints": 10.0, "momentum5Pct": 0.1},
    ):
        on_book = SimpleNamespace(
            symbol="NIFTY",
            side="CALL",
            strike=25200.0,
            alert={"localBaseMovePct": 15.0},
            snap=snap,
        )
        chase = SimpleNamespace(
            symbol="NIFTY",
            side="CALL",
            strike=25350.0,
            alert={"localBaseMovePct": 50.0},
            snap=snap,
        )
        adj_on = index_aligned_book_rank_adjustment(
            on_book, snapshots, None, settings=settings,
        )
        adj_chase = index_aligned_book_rank_adjustment(
            chase, snapshots, None, settings=settings,
        )
    assert adj_on > 0
    assert adj_chase < 0
