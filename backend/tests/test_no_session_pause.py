"""Session must keep scanning entries — no manual stop or loss-streak blanking by default."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.engines.auto_trader import entries_execution_active, stop_trading
from app.engines.chop_day_guards import record_session_trade_close, session_pause_active
from app.models.schemas import AutoTraderState


@pytest.fixture
def cfg():
    c = Settings()
    c.auto_trading_enabled = True
    c.chop_day_guards_enabled = True
    c.session_loss_pause_enabled = False
    c.execution_stop_endpoint_pauses_entries = False
    return c


def test_loss_pause_disabled_by_default(cfg):
    with patch("app.engines.chop_day_guards.get_settings", return_value=cfg):
        record_session_trade_close(-15_000.0)
        paused, reason = session_pause_active()
    assert paused is False
    assert reason == "ok"


def test_loss_pause_active_when_enabled(cfg):
    cfg.session_loss_pause_enabled = True
    cfg.session_large_loss_pause_inr = 8_000.0
    cfg.session_large_loss_pause_seconds = 900
    with patch("app.engines.chop_day_guards.get_settings", return_value=cfg):
        record_session_trade_close(-15_000.0)
        paused, reason = session_pause_active()
    assert paused is True
    assert reason.startswith("large_loss_pause")


def test_manual_stop_does_not_block_entries(cfg):
    state = AutoTraderState(running=False)
    with patch("app.engines.auto_trader.get_settings", return_value=cfg):
        with patch("app.engines.auto_trader._auto_trader_state", state):
            stop_trading()
            assert entries_execution_active(state) is True


def test_manual_stop_blocks_only_when_flag_enabled(cfg):
    cfg.execution_stop_endpoint_pauses_entries = True
    state = AutoTraderState(running=False)
    with patch("app.engines.auto_trader.get_settings", return_value=cfg):
        assert entries_execution_active(state) is False
    state.running = True
    with patch("app.engines.auto_trader.get_settings", return_value=cfg):
        assert entries_execution_active(state) is True
