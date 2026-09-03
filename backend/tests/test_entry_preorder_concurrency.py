"""Deterministic replay of the selected-to-order concurrency escape."""

import asyncio
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines import auto_trader, explosion_detector
from app.engines.explosion_detector import (
    _local_base_hist,
    _open_key,
    align_armed_candidate_evidence,
    armed_base_anchor,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.models.schemas import (
    AutoTraderState,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)


IST = ZoneInfo("Asia/Kolkata")


def _archived_24200_pe_candidate():
    """Candidate shape preserved by the 10:51 production funnel archive."""
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-08-24T10:51:35+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=24200.0,
        atmStrike=24200.0,
    )
    event = SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24200.0,
        premium=27.0,
        tier="EXPLODING",
        explosion_score=64.5,
        velocity_3s=2.0,
        velocity_9s=1.6,
        volume_surge=3.0,
        volume=100_000,
        daily_move_pct=25.3,
        peak_move_pct=25.3,
    )
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24200.0,
        premium=27.0,
        tier="EXPLODING",
        mode="explosion",
        score=100.0,
        confidence=64.5,
        tqs=55.0,
        strategy_type=StrategyType.EXPLOSIVE,
        snap=snap,
        explosion_event=event,
        alert={
            "side": "PUT",
            "strike": 24200.0,
            "premium": 27.0,
            "tier": "EXPLODING",
            "explosionScore": 64.5,
            "ictBaseArmed": True,
            "ictArmedBaseLaunch": True,
            "ictBreakout": True,
            "ictFlatThenVertical": True,
            "ictBasePremium": 21.55,
            "ictBaseRelativeMovePct": 25.3,
            "flatVerticalQuality": 70.0,
            "velocity3s": 2.0,
            "velocity9s": 1.6,
            "volume": 100_000,
            "orderflowConfirmed": True,
            "tradeable": True,
        },
        pretrade_meta={
            "causalRanking": {
                "grade": "S",
                "rankScore": 100.0,
                "executionAuthorization": "S_PREAUTHORIZED",
            },
        },
    )


def _process_patches(state, candidate, events, opener):
    settings = Settings(
        auto_trading_enabled=True,
        ftv_ranked_allocation_enabled=True,
        ftv_allocation_max_positions=1,
    )
    profit_gate = SimpleNamespace(
        newEntriesAllowed=True,
        dailyLossStopExpiryTopOnly=False,
        status="ok",
        message="",
        to_dict=lambda: {},
    )
    capital = SimpleNamespace(to_dict=lambda: {})
    limits = SimpleNamespace(
        dayMode="NORMAL",
        confidenceTier="NORMAL",
        phase="LIVE",
        to_dict=lambda: {},
    )
    day_profile = SimpleNamespace(to_dict=lambda: {})
    stack = ExitStack()

    def select_candidate(*_args, **kwargs):
        excluded = kwargs.get("excluded_keys") or set()
        return None if "NIFTY:PUT:24200" in excluded else candidate

    patches = {
        "get_state": lambda: state,
        "get_settings": lambda: settings,
        "_process_open_trades": AsyncMock(return_value=[]),
        "get_market_phase": lambda: "LIVE_MARKET",
        "update_daily_profit_gate": lambda *_a, **_k: profit_gate,
        "get_capital_snapshot": lambda: capital,
        "get_lot_sizes_meta": lambda: {},
        "capital_book_summary": lambda *_a, **_k: {},
        "compute_session_pnl": lambda _state: 0.0,
        "compute_trading_limits": lambda *_a, **_k: limits,
        "session_pf_feedback": lambda _state: SimpleNamespace(
            profit_factor=0.0,
            win_rate=0.0,
            trade_count=0,
            lot_scale=1.0,
            rank_penalty=0.0,
            tighten_exits=False,
            pause_quick_scalps=False,
            message="",
        ),
        "set_session_limits": lambda _limits: None,
        "chop_guard_summary": lambda *_a: {},
        "entries_allowed_now": lambda: (True, "ok"),
        "explosion_entries_allowed_now": lambda: (True, "ok"),
        "resolve_session_entry_pause": lambda _snapshots: (False, "ok", {}),
        "resolve_daily_trade_cap": lambda *_a: (False, "ok", {}),
        "check_session_whipsaw_pause": lambda *_a: (False, "ok", {}),
        "find_best_entry": select_candidate,
        "next_ranked_allocation_rank": lambda _state: 1,
        "ranked_allocation_for_state": lambda *_a: SimpleNamespace(
            rank=1,
            budgetInr=100_000.0,
            remainingBeforeInr=100_000.0,
            cashReserveInr=0.0,
            capitalBaseInr=100_000.0,
            committedInr=0.0,
            weight=1.0,
            to_dict=lambda: {"rank": 1},
        ),
        "_is_ranked_ftv_candidate": lambda _candidate: True,
        "_open_from_candidate": opener,
        "_record_funnel_event_safe": AsyncMock(side_effect=lambda row: events.append(row)),
    }
    for name, replacement in patches.items():
        stack.enter_context(patch.object(auto_trader, name, replacement))
    stack.enter_context(
        patch(
            "app.engines.day_adaptive_engine.build_day_adaptive_profile",
            return_value=day_profile,
        )
    )
    stack.enter_context(
        patch(
            "app.engines.pretrade_validator.collect_session_trades",
            return_value=[],
        )
    )
    stack.enter_context(
        patch(
            "app.engines.pretrade_validator.controlled_daily_cap_reached",
            return_value=(False, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.pretrade_validator.check_last_n_trades_pause",
            return_value=(False, "ok", {}),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.worst_day_guard.session_entry_policy",
            return_value=("NORMAL", {}),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.worst_day_guard.worst_day_blocks_live",
            return_value=(False, "ok", {}),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.expiry_day_guards.check_expiry_entry_allowed",
            return_value=(True, "ok", {}),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.elite_never_block.snapshots_have_top_must_take",
            return_value=False,
        )
    )
    stack.enter_context(
        patch(
            "app.engines.extreme_explosion_moment.snapshots_have_all_in_explosion",
            return_value=False,
        )
    )
    return stack


def test_four_concurrent_cycles_have_one_claim_and_four_terminal_results_on_cancellation():
    state = AutoTraderState(running=True)
    candidate = _archived_24200_pe_candidate()
    snapshots = {"NIFTY": candidate.snap}
    release_monitor = asyncio.Event()

    class EventLog(list):
        def append(self, row):
            super().append(row)
            conflicts = [
                event for event in self
                if event.get("reason") == "entry_preorder_claim_conflict"
            ]
            if len(conflicts) == 3:
                release_monitor.set()

    events = EventLog()
    monitor_count = 0

    async def cancelled_monitor(*_args, **_kwargs):
        nonlocal monitor_count
        monitor_count += 1
        await release_monitor.wait()
        raise asyncio.CancelledError("execution chart task cancelled")

    async def preorder_open(*_args, **_kwargs):
        return await cancelled_monitor()

    async def replay():
        tasks = [
            asyncio.create_task(auto_trader.process(snapshots, client=MagicMock()))
            for _ in range(4)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    with _process_patches(state, candidate, events, preorder_open):
        results = asyncio.run(replay())

    assert sum(isinstance(result, asyncio.CancelledError) for result in results) == 1
    assert monitor_count == 1
    assert [row["event"] for row in events].count("SELECTED") == 1
    terminal = [
        row for row in events
        if row["event"] in {"ORDER_REJECTED", "ENTRY_ABORTED", "ENTERED"}
    ]
    assert len(terminal) == 4
    assert [row["reason"] for row in terminal].count(
        "entry_preorder_claim_conflict"
    ) == 3
    assert [row["reason"] for row in terminal].count("entry_cancelled") == 1
    assert auto_trader._entry_claims == {}


def test_non_cancellation_baseexception_records_terminal_abort_and_releases_claim():
    class ChartMonitorEscape(BaseException):
        pass

    state = AutoTraderState(running=True)
    candidate = _archived_24200_pe_candidate()
    events = []

    async def exceptional_open(*_args, **_kwargs):
        raise ChartMonitorEscape("execution chart monitor escaped")

    with _process_patches(state, candidate, events, exceptional_open):
        try:
            asyncio.run(
                auto_trader.process(
                    {"NIFTY": candidate.snap},
                    client=MagicMock(),
                )
            )
        except ChartMonitorEscape:
            pass
        else:
            raise AssertionError("BaseException must propagate after terminal telemetry")

    terminal = [row for row in events if row["event"] == "ENTRY_ABORTED"]
    assert len(terminal) == 1
    assert terminal[0]["reason"] == "entry_exception_ChartMonitorEscape"
    assert terminal[0]["exceptionType"] == "ChartMonitorEscape"
    assert auto_trader._entry_claims == {}


def test_real_preorder_path_propagates_execution_chart_monitor_cancellation():
    candidate = _archived_24200_pe_candidate()
    settings = Settings(
        controlled_trading_enabled=False,
        ftv_elite_top_only_enabled=False,
        execution_chart_gate_enabled=True,
        adaptive_exits_enabled=False,
    )
    monitor = AsyncMock(
        side_effect=asyncio.CancelledError("execution chart fetch cancelled")
    )
    with (
        patch.object(auto_trader, "get_settings", return_value=settings),
        patch.object(auto_trader, "compute_lots", return_value=1),
        patch.object(auto_trader, "apply_tiered_lot_cap", return_value=1),
        patch.object(auto_trader, "scale_lots_by_edge", return_value=1),
        patch(
            "app.engines.session_mode_feedback.failed_launch_reentry_blocked",
            return_value=(False, {}),
        ),
        patch(
            "app.engines.session_mode_feedback.exhausted_ftv_reentry_blocked",
            return_value=(False, {}),
        ),
        patch(
            "app.engines.explosion_entry_guards.detect_faded_vertical_rip",
            return_value=(False, {}),
        ),
        patch(
            "app.engines.explosion_entry_guards.detect_fake_explosion_trap",
            return_value=(False, "ok", {}),
        ),
        patch(
            "app.engines.execution_chart_monitor.monitor_trade_chart_before_execution",
            new=monitor,
        ),
    ):
        try:
            asyncio.run(
                auto_trader._open_from_candidate(
                    candidate,
                    AutoTraderState(),
                    client=MagicMock(),
                    snapshots={"NIFTY": candidate.snap},
                )
            )
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("chart monitor cancellation must propagate")

    monitor.assert_awaited_once()


def _armed_replay_snapshot(*, tqs=55.0, spot=24200.0):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=tqs,
        spot=spot,
        atmStrike=spot,
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.08,
            momentum10Pct=0.04,
            momentum15Pct=0.01,
        ),
    )


def _seed_2155_armed_base(settings):
    reset_detector_state_for_tests()
    key = _open_key("NIFTY", 24200.0, Side.PUT)
    start = datetime.now(IST) - timedelta(seconds=30)
    _local_base_hist[key] = deque(
        (
            start + timedelta(seconds=index * 3),
            premium,
        )
        for index, premium in enumerate(
            (21.55, 21.65, 21.60, 21.70, 21.58, 21.68, 21.57, 21.62)
        )
    )
    anchor = armed_base_anchor(
        "NIFTY", 24200.0, Side.PUT, 24.5, settings=settings,
    )
    assert anchor["armed"] is True
    return anchor


def test_2155_prearmed_evidence_authorizes_25_to_30_lift_but_not_35_chase():
    settings = Settings()
    anchor = _seed_2155_armed_base(settings)
    persisted = align_armed_candidate_evidence(
        "NIFTY",
        24200.0,
        Side.PUT,
        {
            "explosionScore": 64.5,
            "flatVerticalQuality": 70.0,
            "tradeQualityScore": 48.0,
            "velocity3s": 2.0,
            "velocity9s": 1.6,
            "volume": 100_000,
            "orderflowConfirmed": True,
            "volumeAwakening": True,
            "armedLaunch": True,
            "flatThenVertical": True,
            "activeBreakout": True,
            "sampleCount": anchor["sampleCount"],
            "spanSeconds": anchor["spanSeconds"],
        },
    )
    base_alert = {
        "side": "PUT",
        "strike": 24200.0,
        "tier": "EXPLODING",
        "ictBaseArmed": True,
        "ictBaseArmedAt": anchor["armedAt"],
        "ictArmedBaseLaunch": False,
        "ictFirstLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictArmedBaseSamples": anchor["sampleCount"],
        "ictArmedBaseSpanSeconds": anchor["spanSeconds"],
        "flatVerticalQuality": 52.0,
        "explosionScore": 44.0,
        "velocity3s": 0.8,
        "velocity9s": 0.7,
        "volume": 0,
        "ictArmedEvidence": persisted,
    }

    results = []
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        for premium in (25.0, 27.0, 30.0):
            alert = {
                **base_alert,
                "premium": premium,
                "ictBaseRelativeMovePct": (premium - 21.55) / 21.55 * 100.0,
            }
            results.append(
                first_lift_entry_readiness(
                    snap=_armed_replay_snapshot(),
                    alert=alert,
                )
            )
        chase = {
            **base_alert,
            "premium": 35.0,
            "ictBaseRelativeMovePct": (35.0 - 21.55) / 21.55 * 100.0,
        }
        chase_result = first_lift_entry_readiness(
            snap=_armed_replay_snapshot(),
            alert=chase,
        )

    assert results == [
        (True, "armed_base_option_led_ready"),
        (True, "armed_base_option_led_ready"),
        (True, "armed_base_option_led_ready"),
    ]
    assert chase_result[0] is False
    assert chase_result[1] == "first_lift_base_move_outside_5_40"


def test_prearmed_alignment_never_waives_orderflow_or_atm_itm():
    settings = Settings()
    anchor = _seed_2155_armed_base(settings)
    weak = align_armed_candidate_evidence(
        "NIFTY",
        24200.0,
        Side.PUT,
        {
            "explosionScore": 64.5,
            "flatVerticalQuality": 70.0,
            "tradeQualityScore": 55.0,
            "velocity3s": 2.0,
            "velocity9s": 1.6,
            "armedLaunch": True,
            "flatThenVertical": True,
            "activeBreakout": True,
            "sampleCount": anchor["sampleCount"],
            "spanSeconds": anchor["spanSeconds"],
        },
    )
    alert = {
        "side": "PUT",
        "strike": 24200.0,
        "tier": "EXPLODING",
        "ictBaseArmed": True,
        "ictBaseArmedAt": anchor["armedAt"],
        "ictFirstLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictBaseRelativeMovePct": 25.3,
        "ictArmedBaseSamples": anchor["sampleCount"],
        "ictArmedBaseSpanSeconds": anchor["spanSeconds"],
        "flatVerticalQuality": 70.0,
        "explosionScore": 64.5,
        "velocity3s": 2.0,
        "velocity9s": 1.6,
        "ictArmedEvidence": weak,
    }
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        weak_result = first_lift_entry_readiness(
            snap=_armed_replay_snapshot(),
            alert=alert,
        )
        otm_result = first_lift_entry_readiness(
            snap=_armed_replay_snapshot(spot=24300.0),
            alert={
                **alert,
                "ictArmedEvidence": {
                    **weak,
                    "orderflowConfirmed": True,
                    "volume": 100_000,
                },
            },
        )

    assert weak_result[0] is False
    assert weak_result[1] == "armed_base_orderflow_below_25000"
    assert otm_result == (False, "armed_base_requires_atm_itm_otm")
