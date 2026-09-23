"""Symmetric best-trade capture — CE and PE compete on merit; no day-side lock."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings, get_settings
from app.engines.aligned_side_guard import (
    breadth_hard_blocks_side,
    session_side_alignment_blocks,
)
from app.engines.best_trade_policy import (
    symmetric_best_trade_capture_active,
    symmetric_structural_base_evidence,
)
from app.engines.directional_lock import check_directional_side_lock
from app.engines.explosion_detector import ExplosionEvent
from app.engines.elite_score_engine import (
    elite_call_chop_shallow_blocked,
    elite_side_day_mode_blocked,
    elite_side_local_base_cap,
    top_trades_only_blocks_entry,
)
from app.engines.pe_win_ce_mirror import call_ce_base_context_armed
from app.engines.rally_capture import cross_side_chase_blocked
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _enable_symmetric_capture():
    object.__setattr__(get_settings(), "symmetric_best_trade_capture_enabled", True)
    yield


def _settings(**overrides):
    s = Settings()
    for key, value in overrides.items():
        object.__setattr__(s, key, value)
    return s


def _snap(*, direction: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 22, 14, 15, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=23350.0,
        atmStrike=23350.0,
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=-0.2 if direction == "BEARISH" else 0.2,
            trendStrength=55.0,
        ),
        breadth=Breadth(bias="BEARISH" if direction == "BEARISH" else "BULLISH", score=60),
    )


def test_symmetric_mode_disables_directional_lock():
    snap = _snap()
    blocked, reason = check_directional_side_lock("NIFTY", Side.CALL, snap)
    assert blocked is False
    assert reason == "ok"


def test_symmetric_mode_disables_session_side_alignment():
    snap = _snap(direction="BEARISH")
    blocked, reason = session_side_alignment_blocks(
        "CALL",
        snap,
        day_mode="CHOP + RALLY",
    )
    assert blocked is False
    assert reason == ""


def test_symmetric_mode_disables_breadth_hard_block():
    blocked, reason = breadth_hard_blocks_side("CALL", "BEARISH")
    assert blocked is False
    assert reason == "ok"


def test_symmetric_mode_disables_cross_side_dominant_block():
    snap = _snap()
    snap.explosionAlerts = [
        {
            "side": "PUT",
            "tier": "ELITE",
            "explosionScore": 95.0,
            "tradeable": True,
        }
    ]
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23300.0,
        premium=45.0,
        tier="ELITE",
        explosion_score=90.0,
        velocity_3s=2.0,
        velocity_9s=1.5,
        velocity_15s=1.0,
        volume_surge=2.0,
        reason="test",
    )
    blocked, reason = cross_side_chase_blocked(event, snap)
    assert blocked is False
    assert reason == "ok"


def test_symmetric_mode_waives_chop_and_day_mode_blocks():
    object.__setattr__(get_settings(), "top_trades_only_strict_enabled", True)
    assessment = {
        "mustTake": False,
        "eliteScore": 95.0,
        "grade": "A",
        "setup": "FTV",
        "localBasePct": 12.0,
    }
    ev = {
        "tier": "ELITE",
        "localBaseMovePct": 12.0,
        "timingAssessment": "GOOD",
    }
    ranking = {"grade": "A", "rankScore": 80.0, "side": "PUT"}
    chop_blocked, _chop_reason = top_trades_only_blocks_entry(
        ev, ranking, assessment, day_mode="EXPIRY WORST", side="PUT",
    )
    day_blocked, _day_reason = elite_side_day_mode_blocked(
        "CALL", "MOMENTUM RALLY", settings=get_settings(),
    )
    assert chop_blocked is False
    assert day_blocked is False


def test_symmetric_structural_base_evidence():
    evidence = {
        "localBaseMovePct": 12.0,
        "ictFlatThenVertical": True,
        "ictBaseArmed": True,
    }
    assert symmetric_structural_base_evidence(evidence, settings=get_settings()) is True


def test_symmetric_ce_raw_base_context_armed():
    snap = _snap(direction="BEARISH")
    state = MagicMock()
    evidence = {
        "localBaseMovePct": 11.0,
        "ictFlatThenVertical": True,
        "ictBaseArmed": True,
        "tier": "ELITE",
    }
    ok, reason, _meta = call_ce_base_context_armed(
        state, snap, "NIFTY", evidence,
    )
    assert ok is True
    assert reason == "symmetric_ce_raw_base"


def test_symmetric_mode_can_be_disabled():
    object.__setattr__(get_settings(), "symmetric_best_trade_capture_enabled", False)
    assert symmetric_best_trade_capture_active(get_settings()) is False


def test_symmetric_ce_same_local_cap_as_pe():
    cap_ce = elite_side_local_base_cap("CALL", settings=get_settings())
    cap_pe = elite_side_local_base_cap("PUT", settings=get_settings())
    assert cap_ce == cap_pe == 20.0


def test_symmetric_ce_chop_shallow_not_blocked():
    blocked, reason = elite_call_chop_shallow_blocked(
        "CALL",
        "CHOP DAY",
        5.0,
        settings=get_settings(),
    )
    assert blocked is False
    assert reason == ""
