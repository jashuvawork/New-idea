"""CE at base — same near-base best-trade bar as PE."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.best_trade_policy import (
    call_at_base_best_trade_fingerprint,
    call_at_base_best_trade_from_candidate,
)
from app.models.schemas import MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
    )


def _evidence(**overrides) -> dict:
    base = {
        "tier": "ELITE",
        "symbol": "NIFTY",
        "side": "CALL",
        "armedBaseLaunch": True,
        "firstLift": True,
        "velocity3s": 1.4,
        "localBaseMovePct": 8.0,
        "timingAssessment": "GOOD",
        "setup": "FTV",
    }
    base.update(overrides)
    return base


def _ranking(**overrides) -> dict:
    base = {"grade": "A", "eliteScore": 92.0}
    base.update(overrides)
    return base


def _assessment(**overrides) -> dict:
    base = {"eliteScore": 92.0, "localBasePct": 8.0, "setup": "FTV", "timing": "GOOD"}
    base.update(overrides)
    return base


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_armed")
def test_call_at_base_best_trade_accepts_near_base_elite(mock_armed):
    mock_armed.return_value = (True, "call_rally_unlock", {})
    ok = call_at_base_best_trade_fingerprint(
        _evidence(),
        _ranking(),
        _assessment(),
        state=SimpleNamespace(),
        snap=_snap(),
        symbol="NIFTY",
    )
    assert ok is True


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_armed")
def test_call_at_base_best_trade_rejects_low_score(mock_armed):
    mock_armed.return_value = (True, "call_rally_unlock", {})
    ok = call_at_base_best_trade_fingerprint(
        _evidence(),
        _ranking(eliteScore=86.0),
        _assessment(eliteScore=86.0),
        state=SimpleNamespace(),
        snap=_snap(),
        symbol="NIFTY",
    )
    assert ok is False


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_armed")
def test_call_at_base_best_trade_rejects_without_rally(mock_armed):
    mock_armed.return_value = (False, "no_rally", {})
    ok = call_at_base_best_trade_fingerprint(
        _evidence(),
        _ranking(),
        _assessment(),
        state=SimpleNamespace(),
        snap=_snap(),
        symbol="NIFTY",
    )
    assert ok is False


@patch("app.engines.best_trade_policy.call_at_base_best_trade_fingerprint", return_value=True)
def test_call_at_base_best_trade_from_candidate(mock_fp):
    cand = MagicMock(
        side=Side.CALL,
        symbol="NIFTY",
        alert={"tier": "ELITE", "armedBaseLaunch": True, "firstLift": True},
        mode="explosion",
    )
    snap = _snap()
    assert call_at_base_best_trade_from_candidate(
        cand, snap, state=SimpleNamespace(),
    ) is True
    mock_fp.assert_called_once()
