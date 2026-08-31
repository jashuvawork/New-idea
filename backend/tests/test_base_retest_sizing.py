"""Size so a base retest can't shake out a near-base winner (protective lot cap)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines import capital_allocator as ca


def _settings(**over):
    s = SimpleNamespace(
        size_to_base_retest_enabled=True,
        size_to_base_retest_max_pct_of_capital=0.10,
        size_to_base_retest_break_buffer_pct=0.15,
        fallback_capital_inr=200_000.0,
        max_sizing_capital_inr=200_000.0,
        per_trade_capital_pct=0.90,
        use_upstox_lot_sizes=False,
        lot_size_nifty=65,
        lot_size_banknifty=30,
        lot_size_sensex=20,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _cap(avail):
    return SimpleNamespace(
        availableMarginInr=avail, usedMarginInr=0, totalEquityInr=avail, source="test",
        perTradeRiskInr=0, perTradeCapitalInr=avail * 0.9, maxExposureInr=avail,
        minLots=1, targetLots=1, maxLots=9999, fetchedAt="",
    )


def test_caps_lots_so_base_retest_within_pct():
    # NIFTY entry 37, base 33.6, 15% break buffer -> stop floor 28.56, risk 8.44pt.
    # 2L capital, 10% = 20k -> max_lots = 20000/(8.44*65) = 36. Full-capital 118 -> 36.
    with (
        patch.object(ca, "get_settings", return_value=_settings()),
        patch.object(ca, "get_capital_snapshot", return_value=_cap(200_000.0)),
    ):
        out = ca.cap_lots_for_base_retest(118, "NIFTY", 37.0, 33.6)
    assert out == 36
    # A break to 15% below the base stays within 10% of capital (survives the wick).
    assert (37.0 - 33.6 * 0.85) * out * 65 <= 20_000 + 1


def test_no_reduction_when_already_small():
    with (
        patch.object(ca, "get_settings", return_value=_settings()),
        patch.object(ca, "get_capital_snapshot", return_value=_cap(200_000.0)),
    ):
        assert ca.cap_lots_for_base_retest(10, "NIFTY", 37.0, 33.6) == 10


def test_small_capital_caps_to_survive_break():
    # 10k capital, 10% = 1k; risk to 15%-below-base = 8.44pt -> max 1000/(8.44*65)=1 lot.
    # Small size is required so a break below the base can't blow >10% of a tiny book.
    with (
        patch.object(ca, "get_settings", return_value=_settings()),
        patch.object(ca, "get_capital_snapshot", return_value=_cap(10_000.0)),
    ):
        assert ca.cap_lots_for_base_retest(3, "NIFTY", 37.0, 33.6) == 1


def test_disabled_is_noop():
    with (
        patch.object(ca, "get_settings", return_value=_settings(size_to_base_retest_enabled=False)),
        patch.object(ca, "get_capital_snapshot", return_value=_cap(200_000.0)),
    ):
        assert ca.cap_lots_for_base_retest(118, "NIFTY", 37.0, 33.6) == 118


def test_noop_when_base_unknown_or_above_entry():
    with (
        patch.object(ca, "get_settings", return_value=_settings()),
        patch.object(ca, "get_capital_snapshot", return_value=_cap(200_000.0)),
    ):
        assert ca.cap_lots_for_base_retest(118, "NIFTY", 37.0, 0.0) == 118
        # base >= entry → not a near-base long above its base → no-op
        assert ca.cap_lots_for_base_retest(118, "NIFTY", 37.0, 40.0) == 118
