"""Paper-live parity and mirrored live entry gates."""

from app.config import Settings
from app.engines.execution_mode import (
    live_entry_gates_active,
    paper_live_parity_active,
)


def test_paper_live_parity_when_disarmed():
    s = Settings()
    s.enable_live_trading = False
    s.paper_trading = True
    assert paper_live_parity_active(s) is True
    assert live_entry_gates_active(s) is True


def test_live_entry_gates_off_when_mirror_disabled():
    s = Settings()
    s.enable_live_trading = False
    s.paper_trading = True
    s.paper_mirror_live_entry_gates = False
    assert paper_live_parity_active(s) is True
    assert live_entry_gates_active(s) is False


def test_live_armed_uses_entry_gates_without_paper():
    s = Settings()
    s.enable_live_trading = True
    s.auto_trading_enabled = True
    s.paper_trading = False
    assert live_entry_gates_active(s) is True
