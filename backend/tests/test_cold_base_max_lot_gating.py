"""COLD_BASE probe sizing must not be overridden by FTV / always-max-lot paths."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.engines.capital_allocator import RankedAllocation
from app.engines.trade_ranking import FtvAuthorization


def _cold_base_timing() -> dict:
    return {
        "assessment": "COLD_BASE",
        "action": "lot_cap",
        "lotCap": 3,
        "structuredColdBase": True,
        "reasons": ["structured_cold_base_v3_1.3"],
    }


def test_pad_lane_ftv_skips_max_lots_on_cold_base_timing():
    from app.engines.auto_trader import _pad_lane_ftv_policy_max_lots

    decision = FtvAuthorization(
        "FAST_BULLISH_FTV", "ok", max_capital_pct=0.90,
    )
    allocation = RankedAllocation(
        rank=1,
        budgetInr=90_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.90,
    )
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=18,
    ) as max_lots:
        lots, authorized = _pad_lane_ftv_policy_max_lots(
            lots=3,
            symbol="NIFTY",
            premium=146.95,
            policy_decision=decision,
            allocation=allocation,
            timing_meta=_cold_base_timing(),
        )
    assert authorized is False
    assert lots == 3
    max_lots.assert_not_called()


def test_pad_lane_ftv_still_max_lots_on_good_timing():
    from app.engines.auto_trader import _pad_lane_ftv_policy_max_lots

    decision = FtvAuthorization(
        "FAST_BULLISH_FTV", "ok", max_capital_pct=0.90,
    )
    allocation = RankedAllocation(
        rank=1,
        budgetInr=90_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.90,
    )
    good_timing = {
        "assessment": "GOOD",
        "action": "allow",
        "lotCap": None,
    }
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=18,
    ) as max_lots:
        lots, authorized = _pad_lane_ftv_policy_max_lots(
            lots=3,
            symbol="NIFTY",
            premium=146.95,
            policy_decision=decision,
            allocation=allocation,
            timing_meta=good_timing,
        )
    assert authorized is True
    assert lots == 18
    max_lots.assert_called_once()


def test_building_rip_ftv_skips_max_lots_on_cold_base_timing():
    from app.engines.auto_trader import _building_rip_ftv_policy_max_lots

    decision = FtvAuthorization(
        "BUILDING_RIP_FTV", "ok", max_capital_pct=0.90,
    )
    allocation = RankedAllocation(
        rank=1,
        budgetInr=90_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.90,
    )
    candidate = type(
        "Cand",
        (),
        {
            "alert": {"buildingLiftHelping": True, "buildingRipHelpersOk": True},
            "pretrade_meta": {},
        },
    )()
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=18,
    ) as max_lots:
        lots, authorized = _building_rip_ftv_policy_max_lots(
            lots=3,
            symbol="NIFTY",
            premium=146.95,
            policy_decision=decision,
            allocation=allocation,
            candidate=candidate,
            timing_meta=_cold_base_timing(),
        )
    assert authorized is False
    assert lots == 3
    max_lots.assert_not_called()


def test_apply_explosion_always_max_respects_cold_base_cap():
    from app.engines.entry_timing import cap_lots_for_timing
    from app.engines.capital_allocator import apply_explosion_always_max_lots

    timing = _cold_base_timing()
    boosted = apply_explosion_always_max_lots(
        3, "NIFTY", 146.95, mode="explosion",
    )
    assert boosted > 3
    final = cap_lots_for_timing(boosted, timing)
    assert final == 3
