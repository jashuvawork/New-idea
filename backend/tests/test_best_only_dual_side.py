"""Best-only CE+PE dual-side slot: one opposite-side leg while a side is open."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import auto_trader
from app.engines.capital_allocator import RankedAllocation, dual_side_allocation
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from tests.test_entry_preorder_concurrency import _archived_24200_pe_candidate, _process_patches

IST = ZoneInfo("Asia/Kolkata")
OPPOSITE = {Side.CALL: Side.PUT, Side.PUT: Side.CALL}


def _alloc(*, remaining: float = 150_000.0, budget: float = 135_000.0, rank: int = 1) -> RankedAllocation:
    return RankedAllocation(
        rank=rank,
        budgetInr=budget,
        remainingBeforeInr=remaining,
        cashReserveInr=0.0,
        capitalBaseInr=150_000.0,
        committedInr=150_000.0 - remaining,
        weight=0.9,
    )


def _open_trade(side: Side, *, rank: int = 1) -> PaperTrade:
    return PaperTrade(
        id=f"open-{side.value}",
        symbol="NIFTY",
        side=side,
        strike=22300.0,
        entryPremium=68.25,
        currentPremium=70.0,
        lots=11,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"allocationRank": rank},
    )


def _candidate(side: Side, strike: float):
    c = copy.deepcopy(_archived_24200_pe_candidate())
    c.side = side
    c.strike = strike
    c.explosion_event.side = side
    c.explosion_event.strike = strike
    c.alert["side"] = side.value
    c.alert["strike"] = strike
    return c


def _settings(dual: bool, **kw) -> Settings:
    return Settings(
        auto_trading_enabled=True,
        ftv_ranked_allocation_enabled=True,
        ftv_allocation_max_positions=3,
        selector_best_only_enabled=True,
        selector_best_only_dual_side_enabled=dual,
        **kw,
    )


def _run_cycle(state, candidates, settings):
    events: list[dict] = []
    opened: list = []

    def select(*_a, **kwargs):
        excluded = kwargs.get("excluded_keys") or set()
        for c in candidates:
            if f"NIFTY:{c.side.value}:{c.strike:g}" not in excluded:
                return c
        return None

    async def opener(candidate, st, *_a, allocation=None, **_k):
        opened.append((candidate.side, candidate.strike, allocation))
        st.openPaperTrades.append(_open_trade(candidate.side, rank=allocation.rank))
        return True, "ok"

    alloc_calls = {"n": 0}

    def ranked(st, rank):
        alloc_calls["n"] += 1
        return _alloc(rank=rank)

    with _process_patches(state, candidates[0], events, opener), patch.object(
        auto_trader, "get_settings", lambda: settings
    ), patch.object(auto_trader, "find_best_entry", select), patch.object(
        auto_trader, "ranked_allocation_for_state", ranked
    ), patch.object(
        auto_trader, "next_ranked_allocation_rank", lambda st: 1 + len(st.openPaperTrades)
    ):
        asyncio.run(auto_trader.process({"NIFTY": candidates[0].snap}, client=MagicMock()))
    return opened, state


@pytest.mark.parametrize("open_side", [Side.PUT, Side.CALL])
def test_dual_side_opens_opposite_leg_and_skips_same_side(open_side):
    state = AutoTraderState(running=True)
    state.openPaperTrades.append(_open_trade(open_side))
    other = OPPOSITE[open_side]
    candidates = [_candidate(open_side, 22350.0), _candidate(other, 22250.0)]
    opened, state = _run_cycle(state, candidates, _settings(True))
    assert [(s, k) for s, k, _ in opened] == [(other, 22250.0)]
    assert opened[0][2].rank == 2
    assert opened[0][2].budgetInr == pytest.approx(opened[0][2].remainingBeforeInr)
    reasons = [row.get("reason") for row in state.skipped or []]
    assert "best_only_dual_side_same_side_open" in reasons


@pytest.mark.parametrize("open_side", [Side.PUT, Side.CALL])
def test_legacy_best_only_never_opens_second_leg(open_side):
    state = AutoTraderState(running=True)
    state.openPaperTrades.append(_open_trade(open_side))
    candidates = [_candidate(OPPOSITE[open_side], 22250.0)]
    opened, _ = _run_cycle(state, candidates, _settings(False))
    assert opened == []


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_dual_side_still_one_entry_per_cycle_from_flat_book(side):
    state = AutoTraderState(running=True)
    candidates = [_candidate(side, 22300.0), _candidate(OPPOSITE[side], 22300.0)]
    opened, _ = _run_cycle(state, candidates, _settings(True))
    assert [(s, k) for s, k, _ in opened] == [(side, 22300.0)]
    first = opened[0][2]
    assert first.rank == 1
    assert first.remainingBeforeInr == pytest.approx(150_000 * 0.70)


@pytest.mark.parametrize("open_side", [Side.PUT, Side.CALL])
def test_dual_side_both_sides_open_blocks_third_leg(open_side):
    state = AutoTraderState(running=True)
    state.openPaperTrades.append(_open_trade(open_side, rank=1))
    state.openPaperTrades.append(_open_trade(OPPOSITE[open_side], rank=2))
    candidates = [_candidate(open_side, 22400.0)]
    opened, _ = _run_cycle(state, candidates, _settings(True))
    assert opened == []


def test_first_leg_reserve_and_one_lot_floor():
    s = Settings(selector_best_only_dual_side_reserve_pct=0.30)
    state = AutoTraderState()
    with patch("app.engines.capital_allocator.get_settings", lambda: s):
        a = dual_side_allocation(_alloc(), state, unit_cost_inr=4_436.0)
        assert a.remainingBeforeInr == pytest.approx(105_000.0)
        assert a.budgetInr == pytest.approx(105_000.0)
        small = dual_side_allocation(
            _alloc(remaining=20_000.0, budget=18_000.0), state, unit_cost_inr=17_000.0,
        )
        assert small.remainingBeforeInr == pytest.approx(17_000.0)
        assert small.budgetInr == pytest.approx(17_000.0)


def test_opposite_leg_uses_whole_remaining_book():
    s = Settings(selector_best_only_dual_side_reserve_pct=0.30)
    state = AutoTraderState()
    state.openPaperTrades.append(_open_trade(Side.PUT))
    with patch("app.engines.capital_allocator.get_settings", lambda: s):
        a = dual_side_allocation(
            _alloc(remaining=45_000.0, budget=4_050.0, rank=2), state, unit_cost_inr=17_000.0,
        )
    assert a.budgetInr == pytest.approx(45_000.0)
    assert a.rank == 2


def test_zero_reserve_is_passthrough():
    s = Settings(selector_best_only_dual_side_reserve_pct=0.0)
    with patch("app.engines.capital_allocator.get_settings", lambda: s):
        base = _alloc()
        assert dual_side_allocation(base, AutoTraderState(), unit_cost_inr=4_436.0) == base


def test_flag_off_by_default_and_on_in_frozen_overlay():
    from pathlib import Path

    assert Settings().selector_best_only_dual_side_enabled is False
    assert Settings().selector_best_only_enabled is True
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "SELECTOR_BEST_ONLY_DUAL_SIDE_ENABLED=true" in overlay.read_text()
