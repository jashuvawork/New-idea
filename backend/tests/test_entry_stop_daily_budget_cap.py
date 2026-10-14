"""Every entry's stop must fit what is left of the daily loss stop (Oct 14 SENSEX 72800 PE)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import Settings
from app.engines.capital_risk_limits import daily_loss_budget_lot_cap


def _settings(**overrides) -> Settings:
    base = dict(
        entry_stop_daily_budget_cap_enabled=True,
        capital_scaled_risk_limits_enabled=False,
        daily_loss_stop_inr=5_000.0,
    )
    base.update(overrides)
    return Settings(**base)


# (symbol/side label, lot multiplier, stop points per unit)
LEGS = [("NIFTY CE", 65, 14.0), ("SENSEX PE", 20, 40.0)]


def test_oct14_sensex_pe_all_in_stop_capped_to_remaining_budget():
    """A ₹5,600 all-in stop (7 × 20 × 40pt) vs ₹4,075 left (session −₹925) → 5 lots."""
    lots, meta = daily_loss_budget_lot_cap(
        lots=7, lot_mult=20, stop_points=40.0, session_pnl_inr=-925.0, settings=_settings(),
    )
    assert meta["requestedStopRiskInr"] == 5_600.0
    assert meta["remainingBudgetInr"] == 4_075.0
    assert lots == 5
    assert lots * 20 * 40.0 <= 4_075.0


@pytest.mark.parametrize("label,mult,stop", LEGS)
def test_fresh_session_caps_to_full_daily_stop(label, mult, stop):
    lots, meta = daily_loss_budget_lot_cap(
        lots=50, lot_mult=mult, stop_points=stop, session_pnl_inr=0.0, settings=_settings(),
    )
    assert lots == int(5_000 // (mult * stop))
    assert lots * mult * stop <= 5_000.0
    assert meta["cappedLots"] == lots


@pytest.mark.parametrize("label,mult,stop", LEGS)
def test_fitting_entry_keeps_lots(label, mult, stop):
    lots, _ = daily_loss_budget_lot_cap(
        lots=1, lot_mult=mult, stop_points=stop, session_pnl_inr=0.0, settings=_settings(),
    )
    assert lots == 1


@pytest.mark.parametrize("label,mult,stop", LEGS)
def test_session_profit_does_not_widen_past_one_daily_stop(label, mult, stop):
    flat, _ = daily_loss_budget_lot_cap(
        lots=50, lot_mult=mult, stop_points=stop, session_pnl_inr=0.0, settings=_settings(),
    )
    green, meta = daily_loss_budget_lot_cap(
        lots=50, lot_mult=mult, stop_points=stop, session_pnl_inr=20_000.0, settings=_settings(),
    )
    assert green == flat
    assert meta["remainingBudgetInr"] == 5_000.0


@pytest.mark.parametrize("label,mult,stop", LEGS)
def test_no_lot_fits_returns_zero(label, mult, stop):
    lots, _ = daily_loss_budget_lot_cap(
        lots=5, lot_mult=mult, stop_points=stop, session_pnl_inr=-4_990.0, settings=_settings(),
    )
    assert lots == 0


@pytest.mark.parametrize("label,mult,stop", LEGS)
def test_disabled_by_default(label, mult, stop):
    assert Settings().entry_stop_daily_budget_cap_enabled is False
    lots, meta = daily_loss_budget_lot_cap(
        lots=50, lot_mult=mult, stop_points=stop, session_pnl_inr=-4_000.0,
        settings=_settings(entry_stop_daily_budget_cap_enabled=False),
    )
    assert (lots, meta) == (50, {})


def test_budget_follows_day_capital_scaling():
    """₹50k book × 10% = ₹5k daily stop when capital-scaled limits are on."""
    s = _settings(
        capital_scaled_risk_limits_enabled=True,
        daily_loss_stop_capital_pct=10.0,
        max_sizing_capital_inr=50_000.0,
        daily_loss_stop_inr=99_999.0,
    )
    with patch("app.engines.capital_allocator.manual_capital_limit_inr", return_value=None):
        lots, meta = daily_loss_budget_lot_cap(
            lots=20, lot_mult=20, stop_points=40.0, session_pnl_inr=0.0, settings=s,
        )
    assert meta["dailyLossStopInr"] == 5_000.0
    assert lots == 6


def test_frozen_overlay_enables_cap():
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "ENTRY_STOP_DAILY_BUDGET_CAP_ENABLED=true" in overlay.read_text()
