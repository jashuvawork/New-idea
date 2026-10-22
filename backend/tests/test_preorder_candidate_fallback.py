"""Deferred exact-leg fallback after execution-time premium fading."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.auto_trader import _record_deferred_candidate_fallback
from app.engines.preorder_rejection_suppression import (
    PREORDER_PREMIUM_FADING_REASONS,
    candidate_preorder_rejection_suppressed,
    reset_preorder_rejection_suppressions,
    suppress_after_preorder_rejection,
)
from app.engines.trade_selector import (
    EntryCandidate,
    _exclude_preorder_rejected_candidates,
)
from app.models.schemas import Side, StrategyType, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 14, 13, 47, tzinfo=IST)


def _candidate(
    strike: float,
    *,
    score: float = 100,
    symbol: str = "NIFTY",
    expiry: str = "2026-08-20",
    side: Side = Side.CALL,
    mode: str = "explosion",
    strategy: StrategyType = StrategyType.EXPLOSIVE,
) -> EntryCandidate:
    snap = SymbolSnapshot(
        symbol=symbol,
        timestamp=NOW.isoformat(),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=90,
        spot=24300,
        optionExpiry=expiry,
    )
    return EntryCandidate(
        symbol=symbol,
        snap=snap,
        mode=mode,
        score=score,
        side=side,
        strike=strike,
        premium=80,
        strategy_type=strategy,
        confidence=95,
        tqs=90,
        tier="ELITE",
    )


@pytest.fixture
def suppression_settings():
    settings = MagicMock()
    settings.preorder_rejection_suppression_seconds = 30
    settings.preorder_structural_rejection_suppression_seconds = 120
    with patch(
        "app.engines.preorder_rejection_suppression.get_settings",
        return_value=settings,
    ):
        yield settings


@pytest.mark.usefixtures("suppression_settings")
def test_rejected_24250_is_excluded_and_24350_wins_next_scan():
    fading = _candidate(24250, score=110)
    flat_vertical = _candidate(24350, score=105)

    first_scan = max(
        _exclude_preorder_rejected_candidates([fading, flat_vertical]),
        key=lambda candidate: candidate.score,
    )
    assert first_scan.strike == 24250
    assert _record_deferred_candidate_fallback(
        first_scan, "exec_premium_fading_at_execution",
    )

    next_scan = _exclude_preorder_rejected_candidates([fading, flat_vertical])
    assert [candidate.strike for candidate in next_scan] == [24350]
    assert max(next_scan, key=lambda candidate: candidate.score).strike == 24350


@pytest.mark.usefixtures("suppression_settings")
@pytest.mark.parametrize(
    "other",
    [
        _candidate(24350),
        _candidate(24250, symbol="SENSEX"),
        _candidate(24250, expiry="2026-08-27"),
        _candidate(24250, side=Side.PUT),
        _candidate(24250, mode="scalp", strategy=StrategyType.SCALP),
        _candidate(24250, strategy=StrategyType.SCALP),
    ],
)
def test_suppression_isolated_to_exact_leg_mode_and_strategy(other):
    rejected = _candidate(24250)
    assert suppress_after_preorder_rejection(
        rejected, "exec_premium_chart_fading", now=NOW,
    )
    assert candidate_preorder_rejection_suppressed(rejected, now=NOW)
    assert not candidate_preorder_rejection_suppressed(other, now=NOW)


@pytest.mark.usefixtures("suppression_settings")
def test_suppression_expires_resets_and_clears_on_session_rollover():
    candidate = _candidate(24250)
    suppress_after_preorder_rejection(
        candidate, "exec_premium_fading_high_score", now=NOW,
    )
    assert candidate_preorder_rejection_suppressed(
        candidate, now=NOW + timedelta(seconds=29),
    )
    assert not candidate_preorder_rejection_suppressed(
        candidate, now=NOW + timedelta(seconds=31),
    )

    suppress_after_preorder_rejection(
        candidate, "exec_premium_fading_high_score", now=NOW,
    )
    reset_preorder_rejection_suppressions()
    assert not candidate_preorder_rejection_suppressed(candidate, now=NOW)

    suppress_after_preorder_rejection(
        candidate, "exec_premium_fading_high_score", now=NOW,
    )
    assert not candidate_preorder_rejection_suppressed(
        candidate, now=NOW + timedelta(days=1),
    )


@pytest.mark.usefixtures("suppression_settings")
def test_successful_first_candidate_creates_no_fallback():
    candidate = _candidate(24250)
    assert not _record_deferred_candidate_fallback(candidate, "opened")
    assert not candidate_preorder_rejection_suppressed(candidate, now=NOW)


@pytest.mark.usefixtures("suppression_settings")
@pytest.mark.parametrize(
    "reason",
    [
        "entry failed: broker timeout",
        "risk_margin_insufficient",
        "daily_loss_limit",
        "outside_entry_session",
        "fake_explosion_trap",
        "exec_chart_live_bearish_no_calls",
    ],
)
def test_unsafe_or_non_leg_specific_failures_do_not_suppress(reason):
    candidate = _candidate(24250)
    assert not _record_deferred_candidate_fallback(candidate, reason)
    assert not candidate_preorder_rejection_suppressed(candidate, now=NOW)


@pytest.mark.usefixtures("suppression_settings")
@pytest.mark.parametrize("reason", sorted(PREORDER_PREMIUM_FADING_REASONS))
def test_all_typed_preorder_premium_fade_reasons_suppress(reason):
    candidate = _candidate(24250)
    assert _record_deferred_candidate_fallback(candidate, reason)
    assert candidate_preorder_rejection_suppressed(candidate)


@pytest.mark.usefixtures("suppression_settings")
@pytest.mark.parametrize(
    "side,otm_strike,atm_strike",
    [(Side.CALL, 73600, 73300), (Side.PUT, 73000, 73300)],
)
def test_expiry_otm_block_lets_atm_leg_take_slot(side, otm_strike, atm_strike):
    """Oct 22 SENSEX expiry: 73600 CE selected 91×, OTM-blocked 90× — ATM never got the slot."""
    otm = _candidate(otm_strike, score=259, symbol="SENSEX", side=side)
    atm = _candidate(atm_strike, score=211, symbol="SENSEX", side=side)

    first = max(_exclude_preorder_rejected_candidates([otm, atm]), key=lambda c: c.score)
    assert first.strike == otm_strike
    assert _record_deferred_candidate_fallback(first, "best_trade_block_expiry_otm_itm_atm_only")

    next_scan = _exclude_preorder_rejected_candidates([otm, atm])
    assert [c.strike for c in next_scan] == [atm_strike]


@pytest.mark.usefixtures("suppression_settings")
@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@pytest.mark.parametrize(
    "reason",
    ["best_trade_block_expiry_otm_itm_atm_only", "best_trade_block_expiry_cheap_otm"],
)
def test_structural_otm_block_holds_longer_than_premium_fade(side, reason):
    candidate = _candidate(73600, symbol="SENSEX", side=side)
    assert suppress_after_preorder_rejection(candidate, reason, now=NOW)
    assert candidate_preorder_rejection_suppressed(candidate, now=NOW + timedelta(seconds=90))
    assert not candidate_preorder_rejection_suppressed(
        candidate, now=NOW + timedelta(seconds=121),
    )


@pytest.mark.usefixtures("suppression_settings")
@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_mtf_5m_premium_fade_suppresses_leg(side):
    candidate = _candidate(73700, symbol="SENSEX", side=side)
    assert _record_deferred_candidate_fallback(candidate, "exec_mtf_premium_5m_fading")
    assert candidate_preorder_rejection_suppressed(candidate)


@pytest.mark.usefixtures("suppression_settings")
def test_high_mover_cooldown_bypass_cannot_bypass_preorder_suppression():
    candidate = _candidate(24250)
    suppress_after_preorder_rejection(
        candidate, "exec_premium_fading_at_execution",
    )
    with patch(
        "app.engines.extreme_explosion_moment.is_high_mover_elite_bypass",
        return_value=True,
    ):
        assert _exclude_preorder_rejected_candidates([candidate]) == []
