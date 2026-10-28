"""Fresh near-base entry — take at launch or skip late chase (Sep17 74600 PE)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import (
    armed_base_late_entry_blocked,
    detect_fake_explosion_trap,
    fresh_near_local_base,
    post_win_fresh_near_base_blocked,
)
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.engines.pretrade_validator import TradeRecord
from app.models.schemas import MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.fresh_near_local_base_max_pct = 10.0
    s.armed_base_fresh_entry_max_seconds = 300.0
    s.armed_base_fresh_max_pad_pct = 12.0
    s.armed_base_late_entry_block_enabled = True
    s.armed_base_late_entry_max_pad_pct = 10.0
    s.fake_explosion_trap_post_win_fresh_near_base_enabled = True
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_post_win_lookback = 1
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _ict(*, base_rel: float, armed_minutes_ago: float = 2.0) -> ICTBreakoutSignal:
    armed_at = (datetime.now(IST) - timedelta(minutes=armed_minutes_ago)).isoformat()
    return ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=80.0,
        reasons=["armed_base_launch"],
        flat_then_vertical=True,
        armed_base_launch=True,
        armed_base_sustained_lift=True,
        base_relative_move_pct=base_rel,
        session_move_pct=25.0,
        armed_at=armed_at,
        armed_base_span_seconds=armed_minutes_ago * 60.0,
    )


def _event(*, daily: float = 25.0, v3: float = 2.37) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=74600.0,
        premium=376.0,
        velocity_3s=v3,
        velocity_9s=v3,
        velocity_15s=v3,
        volume_surge=2.5,
        explosion_score=100.0,
        tier="ELITE",
        reason="armed_base_launch",
        daily_move_pct=daily,
        peak_move_pct=daily,
    )


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.explosion_entry_guards.get_settings")
def test_fresh_near_base_at_8pct_pad(mock_settings, side):
    mock_settings.return_value = _settings()
    fresh, meta = fresh_near_local_base(local_pad=8.0, ict=_ict(base_rel=8.0))
    assert fresh is True
    assert meta.get("freshNearBaseReason") == "near_base_pad"


@patch("app.engines.explosion_entry_guards.get_settings")
def test_armed_base_late_entry_blocks_sep17_style(mock_settings):
    mock_settings.return_value = _settings()
    ict = _ict(base_rel=13.7, armed_minutes_ago=6.9)
    blocked, reason = armed_base_late_entry_blocked(_event(), ict=ict)
    assert blocked is True
    assert "armed_base_late_entry_skip" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_armed_base_fresh_launch_allows_early_pad(mock_settings):
    mock_settings.return_value = _settings()
    ict = _ict(base_rel=11.0, armed_minutes_ago=2.0)
    blocked, reason = armed_base_late_entry_blocked(_event(), ict=ict)
    assert blocked is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.explosion_entry_guards.get_settings")
def test_post_win_requires_fresh_near_base(mock_settings, side):
    mock_settings.return_value = _settings()
    event = _event()
    event.side = side
    cand = MagicMock()
    cand.mode = "explosion"
    cand.pretrade_meta = {}
    cand.alert = {}

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side=side,
                pnl_inr=11603.79,
                exit_reason="explosion_peak_keep_trail",
                strike=23450.0,
            ),
        ],
    ):
        blocked, reason, meta = post_win_fresh_near_base_blocked(
            cand,
            local_pad=13.7,
            ict=_ict(base_rel=13.7, armed_minutes_ago=6.9),
            state=MagicMock(),
        )

    assert blocked is True
    assert reason == "fake_explosion_trap_post_win_fresh_near_base"
    assert meta.get("postWinFreshNearBaseBlock") is True
