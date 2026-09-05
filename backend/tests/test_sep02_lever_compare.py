"""Sep 2 lever comparison — gate pass delta for afternoon miss pattern."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings

IST = ZoneInfo("Asia/Kolkata")

from app.engines.index_rally_side_flip import index_rally_side_flip_bypass
from app.engines.top_moment_gate import top_moment_entry_allowed
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot


def _sep02_exploding_grade_b_evidence() -> dict:
    return {
        "mode": "explosion",
        "tier": "EXPLODING",
        "flatThenVertical": True,
        "activeBreakout": True,
        "velocity3s": 0.8,
        "velocity9s": 0.5,
        "localBaseMovePct": 8.0,
        "orderflowPositive": True,
    }


def _sep02_rally_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 9, 2, 12, 7, 0, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=76512.0,
        atmStrike=76500.0,
        breadth=Breadth(bias="BEARISH"),
        spotChart=SpotChart(
            direction="BEARISH",
            spot=76512.0,
            rsi=63.0,
            macdBias="NEUTRAL",
            macdHistogram=0.0,
            momentum5Pct=0.438,
            momentum15Pct=0.2,
        ),
    )


def test_grade_b_exploding_blocked_off_allowed_on():
    evidence = _sep02_exploding_grade_b_evidence()
    ranking = {"grade": "B", "gradePriority": 4}

    off = Settings(
        elite_trade_engine_enabled=False,
        top_moments_exploding_elite_grade_b_enabled=False,
        top_moments_momentum_rally_grade_b_enabled=False,
        top_moments_day_type_grade_policy_enabled=False,
        top_moments_fast_day_grade_c_enabled=False,
    )
    on = Settings(
        elite_trade_engine_enabled=False,
        top_moments_exploding_elite_grade_b_enabled=True,
        top_moments_momentum_rally_grade_b_enabled=True,
        top_moments_day_type_grade_policy_enabled=True,
        top_moments_fast_day_grade_c_enabled=True,
    )

    with patch("app.config.get_settings", return_value=off):
        ok, reason, _ = top_moment_entry_allowed(
            evidence, ranking, min_grade="A", day_mode="MOMENTUM RALLY",
        )
    assert ok is False
    assert "grade" in reason

    with patch("app.config.get_settings", return_value=on):
        ok, reason, moment = top_moment_entry_allowed(
            evidence, ranking, min_grade="A", day_mode="MOMENTUM RALLY",
        )
    assert ok is True
    assert reason == "ok"
    assert moment == "EXPLODING"


@patch("app.engines.index_rally_side_flip.get_settings")
def test_sep02_index_rally_neutral_macd_waiver(mock_settings):
    mock_settings.return_value = Settings(
        index_rally_side_flip_enabled=True,
        index_rally_side_flip_neutral_macd_mom5_waiver_enabled=True,
        index_rally_side_flip_min_pts=130.0,
        index_rally_side_flip_min_rsi=50.0,
        index_rally_side_flip_min_mom5_pct=0.05,
    )
    snap = _sep02_rally_snap()
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76567.0, 76135.0, 76512.0),
    ), patch(
        "app.engines.directional_lock.session_locked_side",
        return_value="PUT",
    ), patch(
        "app.engines.directional_lock.market_direction",
        return_value="BEARISH",
    ):
        ok, reason, meta = index_rally_side_flip_bypass("SENSEX", Side.CALL, snap)
    assert ok is True
    assert reason == "index_rally_side_flip"
    assert meta["rallyPoints"] == pytest.approx(377.0, abs=1.0)
