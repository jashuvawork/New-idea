"""Oct 1 pad guard on LIVE + Frozen October (parity flags may be off)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.engines.entry_timing import timing_blocks_entry
from app.engines.live_oct1_pad_entry_guard import (
    apply_oct1_pad_timing_block,
    live_oct1_pad_entry_blocked,
    live_oct1_pad_entry_order_gate,
    oct1_pad_entry_guard_active,
)
from app.models.schemas import MarketPhase, Side, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _frozen_live_settings(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        live_paper_parity_enabled=False,
        live_trade_selection_parity_with_paper=False,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        best_trade_sep917_base_shape_align_enabled=True,
        best_trade_base_first_enabled=True,
        **kwargs,
    )


def _snap(symbol: str = "NIFTY") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
    )


def test_oct1_pad_guard_active_on_live_frozen_without_parity():
    s = _frozen_live_settings()
    assert oct1_pad_entry_guard_active(s) is True


def test_oct7_nifty_ce_peak_blocked_on_live_frozen():
    """Oct 7 trade 2: GOOD timing + local ~7% but premium at session high."""
    s = _frozen_live_settings()
    alert = {
        "tier": "EXPLODING",
        "momentType": "armed_base_launch",
        "localBaseMovePct": 6.81,
        "premium": 158.11,
        "sessionLowPremium": 122.0,
        "sessionPeakPremium": 158.7,
        "side": "CALL",
        "velocity3s": 2.37,
        "velocity9s": 2.2,
        "armedBaseLaunch": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "vRipReady": True,
    }
    ev = SimpleNamespace(
        side=Side.CALL,
        strike=22700.0,
        tier="EXPLODING",
        explosion_score=68.4,
        velocity_3s=2.37,
        velocity_9s=2.2,
        daily_move_pct=5.35,
        peak_move_pct=5.35,
    )
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=158.11,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "sessionRangePosition": 0.98},
        explosion_event=ev,
        snap=_snap(),
    )
    blocked, reason, _ = live_oct1_pad_entry_blocked(cand, _snap(), settings=s)
    assert blocked is True
    assert reason in (
        "live_oct1_chase_at_session_high",
        "live_oct1_chase_session_range_high",
    )

    timing = {
        "assessment": "GOOD",
        "action": "allow",
        "reasons": ["hot_v3_2.4_in_window_7%"],
    }
    timing2 = apply_oct1_pad_timing_block(timing, cand, _snap(), settings=s)
    assert timing2["action"] == "block"
    assert timing2["assessment"] == "CHASE"
    blocked2, treason = timing_blocks_entry(timing2)
    assert blocked2 is True
    assert "live_oct1_chase" in treason


def test_oct7_pad_at_base_passes_order_gate_live_frozen():
    """Oct 1-style pad off session high — must still enter on live frozen."""
    s = _frozen_live_settings()
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 8.0,
        "premium": 122.0,
        "sessionLowPremium": 118.0,
        "sessionPeakPremium": 158.0,
        "side": "CALL",
    }
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=122.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": -12.0, "sessionRangePosition": 0.35},
        snap=_snap(),
    )
    blocked, reason, _ = live_oct1_pad_entry_order_gate(cand, _snap(), settings=s)
    assert blocked is False
    assert reason == ""
