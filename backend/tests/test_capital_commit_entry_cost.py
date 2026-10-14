"""Open long-option legs commit their entry cost — a winner's mark never starves the opposite leg."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
import app.engines.capital_allocator as ca
from app.engines.risk_engine import RiskEngine
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
OPPOSITE = {Side.CALL: Side.PUT, Side.PUT: Side.CALL}
ENTRY = 120.0
LOTS = 13
OPP_PREMIUM = 110.0


def _settings(flag: bool) -> Settings:
    return Settings(
        auto_trading_enabled=True,
        fallback_capital_inr=150_000,
        max_sizing_capital_inr=150_000,
        selector_best_only_enabled=True,
        selector_best_only_dual_side_enabled=True,
        capital_commit_at_entry_cost_enabled=flag,
    )


def _state(side: Side, mark: float, symbol: str = "NIFTY") -> AutoTraderState:
    state = AutoTraderState()
    state.openPaperTrades.append(
        PaperTrade(
            id=f"leg1-{side.value}",
            symbol=symbol,
            side=side,
            strike=22250.0,
            entryPremium=ENTRY,
            currentPremium=mark,
            lots=LOTS,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            entryContext={"allocationRank": 1},
        )
    )
    return state


def _opposite_leg(settings: Settings, state: AutoTraderState, side: Side, symbol: str = "NIFTY"):
    with patch("app.config.get_settings", lambda: settings), patch.object(
        ca, "get_settings", lambda: settings
    ), patch("app.engines.risk_engine.get_settings", lambda: settings), patch.object(
        ca, "_capital", None
    ), patch.object(ca, "_manual_capital_limit_inr", None):
        lm = ca.lot_multiplier(symbol)
        alloc = ca.dual_side_allocation(
            ca.ranked_allocation_for_state(state, 2),
            state,
            unit_cost_inr=ca.one_lot_unit_cost_inr(symbol, OPP_PREMIUM),
        )
        lots = int(alloc.budgetInr // (OPP_PREMIUM * lm))
        ok, reason = RiskEngine().check_new_entry(
            state,
            symbol,
            OPPOSITE[side],
            max(lots, 1),
            OPP_PREMIUM,
            lot_multiplier=lm,
            strategy_type=StrategyType.EXPLOSIVE,
            strike=22200.0,
            ignore_per_trade_risk_cap=True,
        )
        return ca.open_exposure_inr(state), alloc, lots, ok, reason, lm


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_winning_leg_commits_entry_cost_and_opposite_leg_buys(side):
    exposure, alloc, lots, ok, reason, lm = _opposite_leg(
        _settings(True), _state(side, ENTRY * 1.6), side,
    )
    assert exposure == pytest.approx(ENTRY * LOTS * lm)
    assert lots >= 5
    assert (ok, reason) == (True, "passed")


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_legacy_marks_winner_and_starves_opposite_leg(side):
    exposure, alloc, lots, ok, reason, lm = _opposite_leg(
        _settings(False), _state(side, ENTRY * 1.6), side,
    )
    assert exposure == pytest.approx(ENTRY * 1.6 * LOTS * lm)
    assert alloc.budgetInr == 0
    assert (ok, reason) == (False, "total_margin_exceeded")


@pytest.mark.parametrize("open_symbol,new_symbol", [
    ("SENSEX", "SENSEX"), ("NIFTY", "SENSEX"), ("SENSEX", "NIFTY"),
])
@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_sensex_and_cross_index_winner_never_shrinks_opposite_book(side, open_symbol, new_symbol):
    s = _settings(True)
    state = _state(side, ENTRY * 1.6, symbol=open_symbol)
    exposure, alloc, lots, *_rest = _opposite_leg(s, state, side, symbol=new_symbol)
    with patch.object(ca, "get_settings", lambda: s):
        open_lm = ca.lot_multiplier(open_symbol)
    assert exposure == pytest.approx(ENTRY * LOTS * open_lm)
    assert alloc.remainingBeforeInr == pytest.approx(150_000 - exposure)
    assert lots >= 1


@pytest.mark.parametrize("flag", [True, False])
@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_losing_mark_never_frees_entry_capital(side, flag):
    exposure, *_rest, lm = _opposite_leg(_settings(flag), _state(side, ENTRY * 0.5), side)
    assert exposure == pytest.approx(ENTRY * LOTS * lm)


def test_flag_off_by_default_and_on_in_frozen_overlay():
    assert Settings().capital_commit_at_entry_cost_enabled is False
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "CAPITAL_COMMIT_AT_ENTRY_COST_ENABLED=true" in overlay.read_text()
