"""Sep 9 intent — early near-base rip per side; block late rank chase (CE/PE)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_detector import _open_key, _session_low, _session_peak
from app.engines.sep09_intent_guards import (
    sep09_intent_evidence_blocked,
    sep09_intent_explosion_entry_blocked,
    session_has_sep09_side_rip,
)
from app.engines.sep917_live_checklist import evaluate_sep917_live_checklist
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _seed_peak(*, symbol: str, strike: float, side: Side, low: float, peak: float) -> None:
    key = _open_key(symbol, strike, side)
    _session_low[key] = low
    _session_peak[key] = peak


def _sep28_alert(*, side: Side = Side.PUT, strike: float = 22850.0) -> dict:
    armed = datetime(2026, 9, 28, 10, 25, 47, tzinfo=IST)
    entry = datetime(2026, 9, 28, 10, 43, 1, tzinfo=IST)
    return {
        "symbol": "NIFTY",
        "side": side.value,
        "strike": strike,
        "tier": "EXPLODING",
        "explosionScore": 100.0,
        "localBaseMovePct": 17.5,
        "flatThenVertical": True,
        "activeBreakout": True,
        "firstLift": True,
        "vRipReady": True,
        "ictFirstLift": True,
        "ictFlatThenVertical": True,
        "spikeRunPct": 20.39,
        "peakMovePct": 20.39,
        "premium": 84.15,
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
        "_entryNow": entry,
    }


def _candidate_from_alert(alert: dict) -> MagicMock:
    c = MagicMock()
    c.symbol = alert["symbol"]
    c.side = Side(alert["side"])
    c.strike = alert["strike"]
    c.premium = alert["premium"]
    c.alert = {k: v for k, v in alert.items() if k != "_entryNow"}
    c.mode = "explosion"
    return c


def test_sep09_blocks_sep28_late_near_peak_put():
    _seed_peak(symbol="NIFTY", strike=22850.0, side=Side.PUT, low=71.6, peak=89.1)
    alert = _sep28_alert()
    now = alert.pop("_entryNow")
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    with patch("app.engines.sep09_intent_guards.get_settings", return_value=settings):
        blocked, reason, _ = sep09_intent_explosion_entry_blocked(
            AutoTraderState(), cand, None, settings=settings, now=now,
        )
    assert blocked is True
    assert "sep09_near_peak_chase" in reason or "sep09_late_entry" in reason


def test_sep09_blocks_sep28_ce_mirror():
    _seed_peak(symbol="NIFTY", strike=22900.0, side=Side.CALL, low=71.6, peak=89.1)
    alert = _sep28_alert(side=Side.CALL, strike=22900.0)
    now = alert.pop("_entryNow")
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    with patch("app.engines.sep09_intent_guards.get_settings", return_value=settings):
        blocked, reason, _ = sep09_intent_explosion_entry_blocked(
            AutoTraderState(), cand, None, settings=settings, now=now,
        )
    assert blocked is True


def test_sep09_allows_early_near_base_within_arm_window():
    _seed_peak(symbol="NIFTY", strike=22800.0, side=Side.PUT, low=71.6, peak=78.0)
    armed = datetime.now(IST) - timedelta(minutes=8)
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22800.0,
        "tier": "EXPLODING",
        "localBaseMovePct": 12.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "firstLift": True,
        "vRipReady": True,
        "spikeRunPct": 12.0,
        "premium": 76.0,
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
    }
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    blocked, reason, _ = sep09_intent_explosion_entry_blocked(
        AutoTraderState(), cand, None, settings=settings,
    )
    assert blocked is False, reason


def test_sep09_one_rip_per_side_blocks_second_put():
    prior = PaperTrade(
        id="a",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22800.0,
        entryPremium=72.0,
        currentPremium=80.0,
        lots=32,
        openedAt=datetime.now(IST) - timedelta(minutes=30),
        closedAt=datetime.now(IST) - timedelta(minutes=5),
        status="CLOSED",
        exitReason="adaptive_stop_loss",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=-1000.0,
        entryContext={"selectionMode": "explosion"},
    )
    state = AutoTraderState(closedPaperTrades=[prior])
    assert session_has_sep09_side_rip(state, symbol="NIFTY", side=Side.PUT) is True

    armed = datetime.now(IST) - timedelta(minutes=5)
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22850.0,
        "localBaseMovePct": 10.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "firstLift": True,
        "premium": 75.0,
        "spikeRunPct": 10.0,
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
    }
    settings = Settings(sep09_intent_enforcement_enabled=True)
    blocked, reason, _ = sep09_intent_explosion_entry_blocked(
        state, _candidate_from_alert(alert), None, settings=settings,
    )
    assert blocked is True
    assert reason == "sep09_one_early_rip_per_side_already_used"


def test_checklist_not_ready_for_sep28_evidence():
    _seed_peak(symbol="NIFTY", strike=22850.0, side=Side.PUT, low=71.6, peak=89.1)
    alert = _sep28_alert()
    entry_now = alert.pop("_entryNow")
    ranking = {"grade": "A", "rankScore": 99.8}
    settings = Settings(sep09_intent_enforcement_enabled=True)
    with patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass", return_value=(True, "", {})):
        with patch("app.engines.sep09_intent_guards.get_settings", return_value=settings):
            result = evaluate_sep917_live_checklist(
                "NIFTY",
                "PUT",
                alert,
                ranking,
                day_mode="CHOP DAY",
                settings=settings,
            )
    # Near-peak guard should fail shape or funnel when replayed at entry clock
    with patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass", return_value=(True, "", {})):
        blocked, reason = sep09_intent_evidence_blocked(
            "NIFTY", "PUT", alert, settings=settings, now=entry_now,
        )
    assert blocked is True
    assert result["ready"] is False
