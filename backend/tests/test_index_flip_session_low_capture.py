"""Index flip participation + session-low V rip capture (CE/PE symmetric)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.elite_score_engine import _v_rip_moment_evidence
from app.engines.index_flip_session_low_capture import (
    index_flip_opposing_side_rank_penalty,
    index_flip_session_low_capture_active,
    index_flip_session_low_elite_floor,
    tier_explosion_score_floor,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.index_flip_session_low_capture_enabled = True
    s.index_flip_participation_enabled = True
    s.index_flip_session_low_min_off_low_pct = 4.0
    s.index_flip_session_low_max_off_low_pct = 22.0
    return s


def _evidence(*, side: str = "PUT", off_low: float = 8.0):
    return {
        "symbol": "NIFTY",
        "side": side,
        "strike": 25200.0,
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "velocity3s": 2.5,
        "volumeSurge": 2.2,
        "sessionLowMovePct": off_low,
        "explosionScore": 48.0,
    }


@patch(
    "app.engines.index_flip_session_low_capture.index_flip_participation_assessment",
    return_value={
        "enabled": True,
        "leadingOptionSide": "PUT",
        "confidence": 0.72,
        "leadingLeg": "SLIDE",
        "reasons": ["breadth_bearish", "put_book_leading"],
    },
)
def test_session_low_capture_put_when_participation_leads(_m):
    settings = _settings()
    snap = SimpleNamespace(dataAvailable=True, symbol="NIFTY")
    ok, meta = index_flip_session_low_capture_active(
        _evidence(side="PUT"), snap, "PUT", settings=settings,
    )
    assert ok is True
    assert "index_flip_session_low_capture" in meta["reasons"]


@patch(
    "app.engines.index_flip_session_low_capture.index_flip_participation_assessment",
    return_value={
        "enabled": True,
        "leadingOptionSide": "CALL",
        "confidence": 0.72,
        "leadingLeg": "RALLY",
        "reasons": ["breadth_bullish"],
    },
)
def test_session_low_capture_blocks_put_when_call_leads(_m):
    settings = _settings()
    snap = SimpleNamespace(dataAvailable=True)
    ok, _ = index_flip_session_low_capture_active(
        _evidence(side="PUT"), snap, "PUT", settings=settings,
    )
    assert ok is False


@patch(
    "app.engines.index_flip_session_low_capture.index_flip_participation_assessment",
    return_value={
        "enabled": True,
        "leadingOptionSide": "CALL",
        "confidence": 0.8,
        "leadingLeg": "RALLY",
        "reasons": [],
    },
)
def test_session_low_capture_call_symmetric(_m):
    settings = _settings()
    snap = SimpleNamespace(dataAvailable=True)
    ev = _evidence(side="CALL", off_low=10.0)
    ev["momentType"] = "v_rip_session_low"
    ok, meta = index_flip_session_low_capture_active(
        ev, snap, "CALL", settings=settings,
    )
    assert ok is True
    floor, _ = index_flip_session_low_elite_floor(ev, snap, "CALL", settings=settings)
    assert floor == 82.0


def test_v_rip_evidence_detects_moment():
    assert _v_rip_moment_evidence({"momentType": "v_rip_session_low"})


def test_tier_score_floor_elite():
    assert tier_explosion_score_floor("ELITE", settings=_settings()) >= 58.0


@patch(
    "app.engines.index_flip_session_low_capture.index_flip_participation_assessment",
    return_value={
        "enabled": True,
        "leadingOptionSide": "PUT",
        "confidence": 0.7,
        "leadingLeg": "SLIDE",
        "reasons": [],
    },
)
def test_opposing_side_penalty_call_when_put_leads(_m):
    settings = _settings()
    snap = SimpleNamespace(dataAvailable=True)
    pen = index_flip_opposing_side_rank_penalty("CALL", snap, settings=settings)
    assert pen == 18.0
    assert index_flip_opposing_side_rank_penalty("PUT", snap, settings=settings) == 0.0
