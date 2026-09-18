"""PE-win CE mirror — CALL rally leg after trail-proved PUT win."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.elite_score_engine import elite_call_chop_shallow_blocked, elite_entry_allowed
from app.engines.pe_win_ce_mirror import (
    pe_win_ce_mirror_armed,
    pe_win_ce_mirror_fingerprint,
    pe_win_ce_mirror_near_miss_waive,
    session_put_win_meta,
)
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _put_win_trade(pnl: float = 16000.0) -> SimpleNamespace:
    return SimpleNamespace(
        status="CLOSED",
        side="PUT",
        symbol="NIFTY",
        pnl_inr=pnl,
        exit_reason="explosion_peak_keep_trail",
    )


def _rally_snap(symbol: str = "NIFTY", rally_lo: float = 24100.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=rally_lo + 60.0,
        breadth=Breadth(bias="BEARISH", score=42.0),
        spotChart=SpotChart(
            direction="BULLISH",
            spot=rally_lo + 60.0,
            momentum5Pct=0.08,
            trendStrength=55.0,
            rsi=58.0,
            macdBias="BULLISH",
            macdHistogram=0.5,
        ),
    )


def _mirror_evidence(**overrides) -> dict:
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


def _mirror_ranking(**overrides) -> dict:
    base = {"grade": "A", "eliteScore": 87.0}
    base.update(overrides)
    return base


def _mirror_assessment(**overrides) -> dict:
    base = {"eliteScore": 87.0, "localBasePct": 8.0, "setup": "FTV", "timing": "GOOD"}
    base.update(overrides)
    return base


@patch("app.engines.pe_win_ce_mirror._collect_session_trades")
def test_session_put_win_meta_trail_proved(mock_trades):
    mock_trades.return_value = [_put_win_trade()]
    ok, meta = session_put_win_meta(state=SimpleNamespace())
    assert ok is True
    assert meta["putWinCount"] == 1
    assert meta["putWinPnlInr"] == 16000.0


@patch("app.engines.pe_win_ce_mirror._collect_session_trades")
@patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass")
def test_pe_win_ce_mirror_armed_after_put_win(mock_flip, mock_trades):
    mock_trades.return_value = [_put_win_trade()]
    mock_flip.return_value = (True, "index_rally_side_flip", {"rallyPoints": 55.0})
    snap = _rally_snap()
    armed, reason, _ = pe_win_ce_mirror_armed(SimpleNamespace(), snap, "NIFTY")
    assert armed is True
    assert reason == "pe_win_ce_mirror"


@patch("app.engines.pe_win_ce_mirror.pe_win_ce_mirror_armed")
def test_mirror_fingerprint_accepts_score_85(mock_armed):
    mock_armed.return_value = (True, "pe_win_ce_mirror", {})
    snap = _rally_snap()
    ok = pe_win_ce_mirror_fingerprint(
        _mirror_evidence(),
        _mirror_ranking(eliteScore=86.0),
        _mirror_assessment(eliteScore=86.0),
        state=SimpleNamespace(),
        snap=snap,
        symbol="NIFTY",
        settings=Settings(pe_win_ce_mirror_min_elite_score=85.0),
    )
    assert ok is True


@patch("app.engines.pe_win_ce_mirror.pe_win_ce_mirror_armed")
def test_mirror_fingerprint_accepts_building_rip(mock_armed):
    mock_armed.return_value = (True, "pe_win_ce_mirror", {})
    snap = _rally_snap()
    ok = pe_win_ce_mirror_fingerprint(
        _mirror_evidence(armedBaseLaunch=False, firstLift=False),
        _mirror_ranking(),
        _mirror_assessment(),
        state=SimpleNamespace(),
        snap=snap,
        symbol="NIFTY",
        readiness_reason="building_rip_bullish_ready",
        settings=Settings(),
    )
    assert ok is True


def test_chop_shallow_waived_for_mirror():
    blocked, reason = elite_call_chop_shallow_blocked(
        "CALL",
        "CHOP DAY",
        8.0,
        settings=Settings(elite_call_chop_shallow_block_enabled=True),
        mirror_waived=True,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.pe_win_ce_mirror.pe_win_ce_mirror_armed")
def test_near_miss_waive_building_rip(mock_armed):
    mock_armed.return_value = (True, "pe_win_ce_mirror", {})
    alert = {"side": "CALL", "tier": "ELITE", "symbol": "NIFTY"}
    ok = pe_win_ce_mirror_near_miss_waive(
        alert,
        snap=_rally_snap(),
        state=SimpleNamespace(),
        readiness_reason="building_rip_bullish",
    )
    assert ok is True


def test_premium_fade_bypass_for_mirror():
    blocked, reason = premium_fading_blocks_entry(
        trade_score=86.0,
        premium_momentum_3s=-0.3,
        premium_momentum_5s=-0.4,
        premium_direction="NEUTRAL",
        explosion_event=SimpleNamespace(tier="ELITE", daily_move_pct=12.0),
        pe_win_mirror_bypass=True,
    )
    assert blocked is False
    assert reason == "pe_win_mirror_shallow_fade_ok"


@patch("app.engines.aligned_side_guard.breadth_hard_blocks_side", return_value=(False, "ok"))
@patch("app.engines.best_trade_policy.call_pe_parity_from_candidate", return_value=True)
def test_directional_lock_uses_mirror_state(mock_parity, _mock_breadth):
    from app.engines.directional_lock import check_directional_side_lock

    snap = _rally_snap()
    cand = SimpleNamespace(side=Side.CALL, alert={"tier": "ELITE"}, symbol="NIFTY")
    blocked, reason = check_directional_side_lock(
        "NIFTY", Side.CALL, snap, candidate=cand, state=SimpleNamespace(),
    )
    assert blocked is False
    mock_parity.assert_called_once()
    assert mock_parity.call_args.kwargs.get("state") is not None
