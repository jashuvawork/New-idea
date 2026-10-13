"""Oct 13 CE/PE fixes hold on SENSEX as on NIFTY (and across the two indexes)."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import auto_trader
from app.engines import explosion_profit as ep
from app.engines import index_tick_helpers as ith
from app.engines.capital_allocator import RankedAllocation
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from tests.test_entry_preorder_concurrency import _archived_24200_pe_candidate, _process_patches
from tests.test_smart_ichimoku_index_rally_bypass import BLOCKED, WAIVED, _case
from tests.test_smart_ichimoku_index_rally_bypass import _settings as _ich_settings

IST = ZoneInfo("Asia/Kolkata")
SIDES = [Side.CALL, Side.PUT]
OPPOSITE = {Side.CALL: Side.PUT, Side.PUT: Side.CALL}
SENSEX_SPOT = 74_210.0
LOCK = "explosion_peak_velocity_reversal_keep"


# --- Deep-ITM runner hold: premium floor scales per index (NIFTY ₹100, SENSEX ₹300) ---


def _runner(symbol: str, side: Side, entry: float, spot_entry: float) -> PaperTrade:
    best = entry * 0.15
    return PaperTrade(
        id=f"runner-{symbol}-{side.value}",
        symbol=symbol,
        side=side,
        strike=spot_entry - 800 if side == Side.CALL else spot_entry + 800,
        entryPremium=entry,
        currentPremium=entry + best * 0.75,
        lots=2,
        openedAt=datetime.now(IST) - timedelta(minutes=40),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext={"spotAtEntry": spot_entry},
    )


def _runner_hold(trade: PaperTrade) -> bool:
    s = Settings(deep_itm_runner_pullback_hold_enabled=True)
    prev = ith._session_extremes.get(trade.symbol)
    spot = float(trade.entryContext["spotAtEntry"])
    ith._session_extremes[trade.symbol] = {
        "date": datetime.now(IST).date().isoformat(),
        "open": spot, "hi": spot + 200, "lo": spot - 200, "last": spot,
    }
    try:
        return ep.deep_itm_runner_pullback_hold(
            trade, reason=LOCK, best=trade.bestPnlPoints,
            pnl_pts=trade.currentPremium - trade.entryPremium, settings=s,
        )
    finally:
        if prev is None:
            ith._session_extremes.pop(trade.symbol, None)
        else:
            ith._session_extremes[trade.symbol] = prev


@pytest.mark.parametrize("side", SIDES)
def test_sensex_near_atm_premium_does_not_get_deep_itm_hold(side):
    assert _runner_hold(_runner("SENSEX", side, 180.0, SENSEX_SPOT)) is False


@pytest.mark.parametrize("side", SIDES)
def test_sensex_deep_itm_runner_holds(side):
    assert _runner_hold(_runner("SENSEX", side, 880.0, SENSEX_SPOT)) is True


@pytest.mark.parametrize("side", SIDES)
def test_nifty_deep_itm_floor_unchanged(side):
    assert _runner_hold(_runner("NIFTY", side, 180.0, 22_512.55)) is True


# --- Per-side explosion cooldown on SENSEX ---


@pytest.mark.parametrize("side", SIDES)
def test_sensex_stop_cools_only_its_own_side_and_index(side):
    s = Settings(explosion_cooldown_per_side_enabled=True, explosion_reentry_cooldown_seconds=180)
    with patch.object(ep, "get_settings", lambda: s):
        ep.record_explosion_stop("SENSEX", side=side)
        assert ep.explosion_in_cooldown("SENSEX", side) is True
        assert ep.explosion_in_cooldown("SENSEX", OPPOSITE[side]) is False
        assert ep.explosion_in_cooldown("NIFTY", side) is False


# --- Ichimoku index-rally bypass on SENSEX (130pt move, not NIFTY's 45pt) ---


def _sensex_ichimoku(side: Side, move_pts: float):
    from app.engines.smart_ichimoku import ichimoku_break_supports_side

    s = _ich_settings()
    snap, _ = _case(side, move_pts=move_pts)
    lo, hi = SENSEX_SPOT - 600, SENSEX_SPOT + 600
    spot = lo + move_pts if side == Side.CALL else hi - move_pts
    snap.symbol = "SENSEX"
    snap.spot = spot
    snap.spotChart.spot = spot
    snap.atmStrike = round(spot / 100) * 100
    with patch("app.engines.smart_ichimoku.get_settings", lambda: s), patch(
        "app.config.get_settings", lambda: s
    ), patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(hi, lo, spot),
    ):
        return ichimoku_break_supports_side(side, snap, require_confirmed=True)


@pytest.mark.parametrize("side", SIDES)
def test_sensex_confirmed_move_waives_lagging_cloud(side):
    assert _sensex_ichimoku(side, 300.0) == (True, WAIVED[side])


@pytest.mark.parametrize("side", SIDES)
def test_sensex_nifty_sized_move_keeps_cloud_gate(side):
    assert _sensex_ichimoku(side, 90.0) == (False, BLOCKED[side])


# --- Dual-side best-only slot across NIFTY and SENSEX ---


def _candidate(symbol: str, side: Side, strike: float):
    c = copy.deepcopy(_archived_24200_pe_candidate())
    c.symbol = symbol
    c.snap.symbol = symbol
    c.side = side
    c.strike = strike
    c.explosion_event.symbol = symbol
    c.explosion_event.side = side
    c.explosion_event.strike = strike
    c.alert["side"] = side.value
    c.alert["strike"] = strike
    return c


def _open(symbol: str, side: Side, rank: int = 1) -> PaperTrade:
    return PaperTrade(
        id=f"open-{symbol}-{side.value}",
        symbol=symbol,
        side=side,
        strike=22300.0,
        entryPremium=68.25,
        currentPremium=70.0,
        lots=11,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"allocationRank": rank},
    )


def _cycle(state, candidates):
    settings = Settings(
        auto_trading_enabled=True,
        ftv_ranked_allocation_enabled=True,
        ftv_allocation_max_positions=3,
        selector_best_only_enabled=True,
        selector_best_only_dual_side_enabled=True,
    )
    opened: list = []

    def select(*_a, **kwargs):
        excluded = kwargs.get("excluded_keys") or set()
        for c in candidates:
            if f"{c.symbol}:{c.side.value}:{c.strike:g}" not in excluded:
                return c
        return None

    async def opener(candidate, st, *_a, allocation=None, **_k):
        opened.append((candidate.symbol, candidate.side, allocation.rank))
        st.openPaperTrades.append(_open(candidate.symbol, candidate.side, allocation.rank))
        return True, "ok"

    def ranked(_st, rank):
        return RankedAllocation(
            rank=rank, budgetInr=135_000.0, remainingBeforeInr=150_000.0,
            cashReserveInr=0.0, capitalBaseInr=150_000.0, committedInr=0.0, weight=0.9,
        )

    snaps = {c.symbol: c.snap for c in candidates}
    with _process_patches(state, candidates[0], [], opener), patch.object(
        auto_trader, "get_settings", lambda: settings
    ), patch.object(auto_trader, "find_best_entry", select), patch.object(
        auto_trader, "ranked_allocation_for_state", ranked
    ), patch.object(
        auto_trader, "next_ranked_allocation_rank", lambda st: 1 + len(st.openPaperTrades)
    ):
        asyncio.run(auto_trader.process(snaps, client=MagicMock()))
    return opened, state


@pytest.mark.parametrize("open_symbol,new_symbol", [("NIFTY", "SENSEX"), ("SENSEX", "NIFTY")])
@pytest.mark.parametrize("open_side", SIDES)
def test_opposite_side_leg_opens_on_the_other_index(open_side, open_symbol, new_symbol):
    state = AutoTraderState(running=True)
    state.openPaperTrades.append(_open(open_symbol, open_side))
    opened, _ = _cycle(state, [_candidate(new_symbol, OPPOSITE[open_side], 74_200.0)])
    assert opened == [(new_symbol, OPPOSITE[open_side], 2)]


@pytest.mark.parametrize("open_side", SIDES)
def test_sensex_opposite_leg_while_sensex_side_open(open_side):
    state = AutoTraderState(running=True)
    state.openPaperTrades.append(_open("SENSEX", open_side))
    candidates = [
        _candidate("SENSEX", open_side, 74_300.0),
        _candidate("SENSEX", OPPOSITE[open_side], 74_100.0),
    ]
    opened, state = _cycle(state, candidates)
    assert opened == [("SENSEX", OPPOSITE[open_side], 2)]
    reasons = [row.get("reason") for row in state.skipped or []]
    assert "best_only_dual_side_same_side_open" in reasons
