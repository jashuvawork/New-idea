"""Sep 9 intent — early near-base rip per side; block late rank chase (CE/PE)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_detector import _open_key, _session_low, _session_peak
from app.engines.elite_never_block import elite_must_take_bypass_allowed
from app.engines.sep09_intent_guards import (
    candidate_is_rank_one,
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
    assert reason in (
        "sep09_one_early_rip_per_side_already_used",
        "sep09_second_leg_requires_afternoon_structural",
    )


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


def test_sep09_rank_one_outside_entry_window_blocked():
    armed = datetime.now(IST) - timedelta(minutes=6)
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22850.0,
        "cycleRank": 1,
        "tier": "EXPLODING",
        "localBaseMovePct": 12.0,
        "flatThenVertical": True,
        "activeBreakout": True,
        "firstLift": True,
        "spikeRunPct": 12.0,
        "premium": 76.0,
        "timingAssessment": {"inWindow": False, "reason": "late_chase"},
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
    }
    cand = _candidate_from_alert(alert)
    assert candidate_is_rank_one(cand, cand.alert, alert) is True
    settings = Settings(sep09_intent_enforcement_enabled=True)
    blocked, reason, meta = sep09_intent_explosion_entry_blocked(
        AutoTraderState(), cand, None, settings=settings,
    )
    assert blocked is True
    assert reason == "sep09_rank_one_outside_entry_window"
    assert meta.get("rankOneStrict") is True


def test_elite_must_take_respects_sep09_rank_one_chase():
    _seed_peak(symbol="NIFTY", strike=22850.0, side=Side.PUT, low=71.6, peak=89.1)
    alert = _sep28_alert()
    alert["cycleRank"] = 1
    alert["timingAssessment"] = {"inWindow": False}
    now = alert.pop("_entryNow")
    cand = _candidate_from_alert(alert)
    settings = Settings(sep09_intent_enforcement_enabled=True)
    with patch("app.engines.sep09_intent_guards.get_settings", return_value=settings):
        with patch("app.engines.elite_never_block.get_settings", return_value=settings):
            blocked, _, _ = sep09_intent_explosion_entry_blocked(
                AutoTraderState(), cand, None, settings=settings, now=now,
            )
            assert blocked is True
            assert elite_must_take_bypass_allowed(candidate=cand, state=AutoTraderState()) is False


def test_open_premium_first_rip_waives_sep09_near_peak_chase():
    """Sep28 22850 PE open vertical — spike from ₹18 base is capture, not afternoon chase."""
    _seed_peak(symbol="NIFTY", strike=22850.0, side=Side.PUT, low=18.0, peak=85.0)
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22850.0,
        "tier": "EXPLODING",
        "localBaseMovePct": 14.0,
        "flatThenVertical": True,
        "firstLift": True,
        "spikeRunPct": 120.0,
        "sessionMovePct": 130.0,
        "openPremiumMove": 130.0,
        "premium": 42.0,
        "ictCaptureMeta": {"ict": {"armedAt": datetime.now(IST).isoformat()}},
    }
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    with patch("app.engines.session_timing.in_open_premium_window", return_value=True):
        blocked, reason, meta = sep09_intent_explosion_entry_blocked(
            AutoTraderState(), cand, None, settings=settings,
        )
    assert blocked is False, reason
    assert meta.get("openPremiumFirstRip")


def test_session_has_sep09_side_rip_from_trade_store_archive():
    from app.engines.pretrade_validator import TradeRecord

    state = AutoTraderState(closedPaperTrades=[])
    archived = [
        TradeRecord(
            symbol="NIFTY",
            side="PUT",
            pnl_inr=-32000.0,
            exit_reason="adaptive_stop_loss",
            strike=22850.0,
            trade_id="archived-22850",
            mode="explosion",
        )
    ]
    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=archived,
    ):
        assert session_has_sep09_side_rip(state, symbol="NIFTY", side=Side.PUT) is True


def _prior_put_explosion(*, strike: float = 22700.0, closed_minutes_ago: float = 45.0) -> PaperTrade:
    now = datetime(2026, 9, 28, 14, 0, 0, tzinfo=IST)
    return PaperTrade(
        id="prior-put",
        symbol="NIFTY",
        side=Side.PUT,
        strike=strike,
        entryPremium=26.0,
        currentPremium=30.0,
        lots=40,
        openedAt=now - timedelta(minutes=closed_minutes_ago + 30),
        closedAt=now - timedelta(minutes=closed_minutes_ago),
        status="CLOSED",
        exitReason="explosion_peak_keep_trail",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=12000.0,
        entryContext={"selectionMode": "explosion", "sep09RipLane": "EARLY_NEAR_BASE"},
    )


def test_afternoon_structural_allows_second_put_different_strike():
    """Sep28-style 14:00 22850 PE off fresh base after earlier 22700 win."""
    _seed_peak(symbol="NIFTY", strike=22850.0, side=Side.PUT, low=55.0, peak=78.0)
    entry_now = datetime(2026, 9, 28, 14, 0, 0, tzinfo=IST)
    armed = entry_now - timedelta(minutes=6)
    state = AutoTraderState(closedPaperTrades=[_prior_put_explosion()])
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22850.0,
        "tier": "ELITE",
        "localBaseMovePct": 14.0,
        "flatThenVertical": True,
        "firstLift": True,
        "vRipReady": True,
        "spikeRunPct": 12.0,
        "premium": 75.0,
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
    }
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
        blocked, reason, meta = sep09_intent_explosion_entry_blocked(
            state, cand, None, settings=settings, now=entry_now,
        )
    assert blocked is False, reason
    assert meta.get("afternoonStructuralRip")


def test_afternoon_structural_blocks_same_strike_without_flat_time():
    _seed_peak(symbol="NIFTY", strike=22850.0, side=Side.PUT, low=55.0, peak=78.0)
    entry_now = datetime(2026, 9, 28, 14, 0, 0, tzinfo=IST)
    armed = entry_now - timedelta(minutes=5)
    loss = _prior_put_explosion(strike=22850.0, closed_minutes_ago=10.0)
    loss.pnlInr = -8000.0
    loss.exitReason = "adaptive_stop_loss"
    state = AutoTraderState(closedPaperTrades=[loss])
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22850.0,
        "localBaseMovePct": 12.0,
        "flatThenVertical": True,
        "firstLift": True,
        "spikeRunPct": 10.0,
        "premium": 72.0,
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
    }
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
        blocked, reason, _ = sep09_intent_explosion_entry_blocked(
            state, cand, None, settings=settings, now=entry_now,
        )
    assert blocked is True
    assert "sep09_second_leg" in reason or "loss_strike" in reason or "session_same_strike" in reason


def test_afternoon_structural_ce_mirror():
    _seed_peak(symbol="NIFTY", strike=22900.0, side=Side.CALL, low=40.0, peak=58.0)
    entry_now = datetime(2026, 9, 28, 14, 5, 0, tzinfo=IST)
    armed = entry_now - timedelta(minutes=7)
    prior = _prior_put_explosion(strike=22800.0)
    prior.side = Side.CALL
    prior.strike = 22850.0
    state = AutoTraderState(closedPaperTrades=[prior])
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22900.0,
        "localBaseMovePct": 11.0,
        "flatThenVertical": True,
        "firstLift": True,
        "spikeRunPct": 11.0,
        "premium": 62.0,
        "ictCaptureMeta": {"ict": {"armedAt": armed.isoformat()}},
    }
    settings = Settings(sep09_intent_enforcement_enabled=True)
    cand = _candidate_from_alert(alert)
    with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
        blocked, reason, meta = sep09_intent_explosion_entry_blocked(
            state, cand, None, settings=settings, now=entry_now,
        )
    assert blocked is False, reason
    assert meta.get("afternoonStructuralRip")
