"""Sep 9–17 live checklist — lanes and HUD summary."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.engines.sep917_live_checklist import (
    CHECKLIST_VERSION,
    evaluate_sep917_live_checklist,
    resolve_sep917_lane,
    sep917_live_checklist_session_summary,
)
from app.models.schemas import AutoTraderState


def _near_base_evidence(**overrides):
    base = {
        "symbol": "NIFTY",
        "side": "CALL",
        "tier": "ELITE",
        "explosionScore": 92.0,
        "localBaseMovePct": 12.0,
        "ictBaseArmed": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "eliteBaseReady": True,
    }
    base.update(overrides)
    return base


def test_resolve_lane_near_base():
    lane = resolve_sep917_lane(
        "CALL",
        _near_base_evidence(),
        {"grade": "A", "score": 95.0},
        settings=Settings(),
    )
    assert lane == "NEAR_BASE_SEP917"


def test_resolve_lane_chase_block_without_structure():
    lane = resolve_sep917_lane(
        "CALL",
        {
            "tier": "BUILDING",
            "localBaseMovePct": 55.0,
            "explosionScore": 40.0,
        },
        {"grade": "C", "score": 40.0},
        settings=Settings(),
    )
    assert lane == "CHASE_BLOCK"


@patch(
    "app.engines.explosion_detector.retained_peak_velocity_3s",
    return_value=2.4,
)
def test_building_rip_lane_on_helper_alert(_peak):
    from tests.test_building_rip_helper_capture import _nifty23100_ce_chase_alert

    alert = _nifty23100_ce_chase_alert()
    lane = resolve_sep917_lane(
        "CALL",
        alert,
        {"grade": "B", "score": 88.0},
        settings=Settings(),
    )
    assert lane == "BUILDING_RIP"


def test_evaluate_checklist_chase_not_ready():
    result = evaluate_sep917_live_checklist(
        "NIFTY",
        "CALL",
        {"tier": "BUILDING", "localBaseMovePct": 48.0},
        {"grade": "C", "score": 42.0},
        day_mode="CHOP DAY",
        settings=Settings(),
    )
    assert result["lane"] == "CHASE_BLOCK"
    assert result["ready"] is False
    assert result["steps"]["optionShape"]["ok"] is False


def test_session_summary_shape():
    state = AutoTraderState()
    state.buildingLtpMonitor = {}
    snaps = {}
    summary = sep917_live_checklist_session_summary(
        state, snaps, day_mode="MOMENTUM RALLY",
    )
    assert summary["version"] == CHECKLIST_VERSION
    assert len(summary["stepsGuide"]) == 4
    assert "symmetricBestTradeCapture" in summary


@patch("app.engines.chop_day_guards.get_settings")
def test_chop_guard_summary_includes_sep917_checklist(mock_settings):
    from contextlib import ExitStack

    from app.engines.chop_day_guards import chop_guard_summary
    from app.models.schemas import Regime, SymbolSnapshot

    s = Settings()
    mock_settings.return_value = s

    snap = MagicMock(spec=SymbolSnapshot)
    snap.dataAvailable = True
    snap.symbol = "NIFTY"
    snap.breadth = MagicMock(bias="NEUTRAL", score=0.0, aligned=True)
    snap.regime = Regime.RANGE_BOUND
    snap.spotChart = MagicMock(direction="NEUTRAL")
    snap.explosionAlerts = []
    snaps = {"NIFTY": snap}

    stubs = [
        ("app.engines.pretrade_validator.check_last_n_trades_pause", (False, "ok", {})),
        ("app.engines.pretrade_validator.last_n_trades_summary", {}),
        ("app.engines.pretrade_validator.resolve_effective_daily_trade_cap", (20, "chop")),
        ("app.engines.whipsaw_guards.whipsaw_guard_summary", {}),
        ("app.engines.session_timing.in_midday_chop_window", False),
        ("app.engines.session_timing.in_open_caution_window", False),
        ("app.engines.chop_day_guards.in_momentum_rally_window", False),
        ("app.engines.chop_day_guards.before_primary_window", False),
        ("app.engines.expiry_day_guards.is_expiry_session", False),
        ("app.engines.expiry_day_guards.expiry_guard_summary", {}),
        ("app.engines.worst_day_guard.worst_day_guard_summary", {}),
        ("app.engines.dual_mode_strategy.dual_mode_summary", {}),
        ("app.engines.bad_day_routing.bad_day_routing_summary", {}),
        ("app.engines.directional_lock.directional_lock_summary", {"symbols": {}}),
        ("app.engines.confidence_hold.high_confidence_close_summary", {}),
        ("app.engines.psychology_hold.psychology_hold_summary", {}),
        ("app.engines.ict_breakout_monitor.ict_monitor_summary", {}),
        ("app.engines.worst_day_itm_fade.worst_day_trades_summary", {}),
        ("app.engines.moneyness.resolve_preferred_moneyness", "ATM"),
        ("app.engines.simple_profit.get_session_targets", MagicMock(sessionLabel="TEST", targetPoints=20)),
        ("app.engines.daily_18pct_strategy.get_session_limits", MagicMock(confidenceTier="MEDIUM")),
        ("app.engines.market_momentum.index_moment_summary", {}),
        ("app.engines.aligned_side_guard.session_side_flip_alignment_summary", {}),
        ("app.engines.elite_trade_budget.elite_trade_budget_summary", {}),
        ("app.engines.entry_day_adaptive.resolve_entry_day_policy", MagicMock(to_dict=lambda: {})),
    ]
    with ExitStack() as stack:
        for target, value in stubs:
            if callable(value) and not isinstance(value, MagicMock):
                stack.enter_context(patch(target, value))
            else:
                stack.enter_context(patch(target, return_value=value))
        summary = chop_guard_summary(AutoTraderState(), snaps)
    assert "sep917LiveChecklist" in summary
    assert summary["sep917LiveChecklist"]["version"] == CHECKLIST_VERSION
