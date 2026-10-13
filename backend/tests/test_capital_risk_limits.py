"""Day capital: one budget number fits sizing and every INR risk limit (CE/PE agnostic)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engines import capital_allocator as ca
from app.engines.capital_risk_limits import (
    book_capital_inr,
    capital_risk_limits_summary,
    risk_limit_inr,
)


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "capital_scaled_risk_limits_enabled": True,
        "fallback_capital_inr": 100_000,
        "max_sizing_capital_inr": 100_000,
        "daily_loss_stop_inr": 15_000,
        "emergency_stop_inr": 15_000,
        "max_risk_per_trade_inr": 3_000,
        "session_large_loss_pause_inr": 6_000,
        "trade_store_dir": str(tmp_path),
        "use_upstox_capital_for_sizing": False,
        "enable_live_trading": False,
    }
    base.update(overrides)
    return Settings(**base)


@contextmanager
def _use(s: Settings):
    ca.reset_capital_for_tests()
    with patch("app.config.get_settings", lambda: s), patch(
        "app.engines.capital_allocator.get_settings", lambda: s
    ), patch("app.engines.capital_risk_limits.get_settings", lambda: s):
        yield
    ca.reset_capital_for_tests()


def test_flag_off_keeps_fixed_inr_limits(tmp_path):
    s = _settings(tmp_path, capital_scaled_risk_limits_enabled=False)
    with _use(s):
        ca.set_manual_capital_limit(250_000)
        assert risk_limit_inr("daily_loss_stop_inr", s) == 15_000
        assert risk_limit_inr("max_risk_per_trade_inr", s) == 3_000
        assert ca._effective_capital_inr(1e9) == 100_000
    assert not (tmp_path / "manual_capital.json").exists()


def test_limits_follow_env_book(tmp_path):
    s = _settings(tmp_path, fallback_capital_inr=120_000, max_sizing_capital_inr=120_000)
    with _use(s):
        assert book_capital_inr(s) == 120_000
        assert risk_limit_inr("daily_loss_stop_inr", s) == 12_000
        assert risk_limit_inr("emergency_stop_inr", s) == 12_000
        assert risk_limit_inr("max_risk_per_trade_inr", s) == 2_400
        assert risk_limit_inr("session_large_loss_pause_inr", s) == 4_800


@pytest.mark.parametrize("budget", [75_000, 250_000])
def test_operator_budget_above_or_below_env_fits(tmp_path, budget):
    s = _settings(tmp_path)
    with _use(s):
        ca.set_manual_capital_limit(budget)
        assert ca._effective_capital_inr(1e9) == budget
        assert ca.get_capital_snapshot().availableMarginInr == budget
        summary = capital_risk_limits_summary(s)
        assert summary["bookCapitalInr"] == budget
        assert summary["limitsInr"]["daily_loss_stop_inr"] == budget * 0.10
        assert summary["limitsInr"]["max_risk_per_trade_inr"] == budget * 0.02


def test_replay_uses_env_book_not_runtime_budget(tmp_path):
    from app.engines.eod_trade_report import _replay_daily_stop

    s = _settings(tmp_path)
    with _use(s):
        ca.set_manual_capital_limit(250_000)
        assert _replay_daily_stop(s) == 10_000
        assert risk_limit_inr("daily_loss_stop_inr", s) == 25_000


def test_budget_survives_restart_until_env_capital_changes(tmp_path):
    s = _settings(tmp_path)
    with _use(s):
        ca.set_manual_capital_limit(130_000)
    with _use(s):
        assert ca.manual_capital_limit_inr() is None
        assert ca.restore_manual_capital_limit() == 130_000
        assert book_capital_inr(s) == 130_000
    moved = _settings(tmp_path, fallback_capital_inr=180_000, max_sizing_capital_inr=180_000)
    with _use(moved):
        assert ca.restore_manual_capital_limit() is None
        assert book_capital_inr(moved) == 180_000


def test_daily_loss_stop_gate_uses_scaled_limit(tmp_path):
    from app.engines.capital_allocator import update_daily_profit_gate
    from app.models.schemas import AutoTraderState

    s = _settings(tmp_path)
    with _use(s), patch(
        "app.engines.capital_allocator.compute_session_pnl", lambda _st: -9_000.0
    ):
        ca.set_manual_capital_limit(80_000)
        gate = update_daily_profit_gate(AutoTraderState())
        assert gate.status == "DAILY_LOSS_STOP"
        ca.set_manual_capital_limit(100_000)
        gate = update_daily_profit_gate(AutoTraderState())
        assert gate.status != "DAILY_LOSS_STOP"


def test_capital_endpoint_requires_amount_and_returns_fitted_limits(tmp_path):
    from app.main import app

    s = _settings(tmp_path)
    with _use(s), patch("app.engines.auto_trader.get_settings", lambda: s):
        client = TestClient(app)
        assert client.post("/api/capital", json={}).status_code == 422
        assert client.post("/api/capital", json={"allocatedInr": 0}).status_code == 422
        body = client.post("/api/capital", json={"allocatedInr": 140_000}).json()
        limits = body["capitalRiskLimits"]
        assert limits["bookCapitalInr"] == 140_000
        assert limits["limitsInr"]["daily_loss_stop_inr"] == 14_000
