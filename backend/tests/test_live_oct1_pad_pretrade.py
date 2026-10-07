"""Oct 1 pad guard on pretrade + order path under paper parity (CE/PE symmetric)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.live_oct1_pad_entry_guard import live_oct1_pad_entry_order_gate
from app.engines.pretrade_validator import validate_candidate
from app.models.schemas import AutoTraderState, MarketPhase, Side, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _parity_settings():
    return settings_mock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        best_trade_sep917_base_shape_align_enabled=True,
        best_trade_base_first_enabled=True,
        ftv_elite_top_only_enabled=False,
        whipsaw_guards_enabled=False,
        controlled_trading_enabled=False,
        execution_chart_gate_enabled=False,
        enable_live_trading=False,
        paper_live_parity_enabled=True,
        paper_simulate_broker_orders=True,
    )


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
    )


def _chase_candidate(*, side: Side = Side.CALL):
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 6.8,
        "premium": 158.11,
        "sessionLowPremium": 122.0,
        "sessionPeakPremium": 158.7,
        "side": side.value,
    }
    ev = SimpleNamespace(
        tier="ELITE",
        explosion_score=180.0,
        velocity_3s=2.0,
        velocity_9s=1.5,
        volume_surge=1.2,
    )
    return SimpleNamespace(
        symbol="NIFTY",
        side=side,
        strike=22700.0 if side == Side.CALL else 22650.0,
        premium=158.11,
        score=72.0,
        mode="explosion",
        tier="ELITE",
        alert=alert,
        snap=_snap(),
        explosion_event=ev,
        pretrade_meta={},
        liveEntryScoreMeta={
            "sessionRangePosition": 0.98,
            "drawdownFromHighPct": 0.0,
        },
    )


def _pad_candidate(*, side: Side = Side.PUT):
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 8.0,
        "premium": 124.0,
        "sessionLowPremium": 118.0,
        "sessionPeakPremium": 158.0,
        "side": side.value,
    }
    ev = SimpleNamespace(
        tier="ELITE",
        explosion_score=175.0,
        velocity_3s=2.5,
        velocity_9s=2.0,
        volume_surge=1.1,
    )
    return SimpleNamespace(
        symbol="NIFTY",
        side=side,
        strike=22650.0,
        premium=124.0,
        score=70.0,
        mode="explosion",
        tier="ELITE",
        alert=alert,
        snap=_snap(),
        explosion_event=ev,
        pretrade_meta={},
        liveEntryScoreMeta={
            "sessionRangePosition": 0.15,
            "drawdownFromHighPct": -21.5,
        },
    )


def _explosion_guard_patches(stack: ExitStack):
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.check_explosion_macd_alignment",
            return_value=(True, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.check_peak_chase_entry",
            return_value=(True, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.explosion_entry_window_blocked",
            return_value=(False, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.tier_promotion_pad_chase_blocked",
            return_value=(False, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.armed_base_late_entry_blocked",
            return_value=(False, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.post_peak_chase_blocked",
            return_value=(False, "ok"),
        )
    )
    stack.enter_context(
        patch(
            "app.engines.explosion_entry_guards.detect_fake_explosion_trap",
            return_value=(False, "ok", {}),
        )
    )


def _run_pretrade(cand, settings):
    with ExitStack() as stack:
        _explosion_guard_patches(stack)
        stack.enter_context(
            patch("app.engines.pretrade_validator.get_settings", return_value=settings)
        )
        stack.enter_context(
            patch(
                "app.engines.worst_day_guard.worst_day_allows_candidate",
                return_value=(True, "ok", {}),
            )
        )
        stack.enter_context(
            patch(
                "app.engines.bad_day_routing.check_bad_day_candidate",
                return_value=(True, "ok", {}),
            )
        )
        stack.enter_context(
            patch(
                "app.engines.live_entry_score.live_entry_score_blocks_entry",
                return_value=(False, "ok", {}),
            )
        )
        stack.enter_context(
            patch(
                "app.engines.premium_spike_dump_guard.post_spike_premium_dump_blocked",
                return_value=(False, "ok", {}),
            )
        )
        stack.enter_context(
            patch(
                "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
                return_value=MagicMock(),
            )
        )
        return validate_candidate(
            cand, AutoTraderState(), snapshots={"NIFTY": _snap()},
        )


def test_pretrade_blocks_ce_chase_at_session_high_under_parity():
    settings = _parity_settings()
    cand = _chase_candidate(side=Side.CALL)
    ok, reason, meta = _run_pretrade(cand, settings)
    assert ok is False
    assert reason in (
        "live_oct1_chase_at_session_high",
        "live_oct1_chase_session_range_high",
    )
    assert meta.get("liveOct1PadGuard", {}).get("nearBaseShape") is True


def test_pretrade_blocks_pe_chase_at_session_high_under_parity():
    settings = _parity_settings()
    cand = _chase_candidate(side=Side.PUT)
    ok, reason, _ = _run_pretrade(cand, settings)
    assert ok is False
    assert "live_oct1_chase" in reason


def test_pretrade_allows_pe_pad_off_session_high_under_parity():
    settings = _parity_settings()
    cand = _pad_candidate(side=Side.PUT)
    ok, reason, meta = _run_pretrade(cand, settings)
    assert "live_oct1_chase" not in reason
    if not ok:
        assert reason != "live_oct1_chase_at_session_high"
    else:
        assert reason == "ok" or meta.get("liveOct1PadGuard", {}).get("nearBaseShape") is not False


def test_order_gate_blocks_chase_under_paper_parity_without_live_flag():
    """Order submit gate matches live + paper-parity sim (not enable_live_trading only)."""
    settings = _parity_settings()
    assert settings.enable_live_trading is False
    cand = _chase_candidate(side=Side.CALL)
    blocked, reason, meta = live_oct1_pad_entry_order_gate(
        cand, _snap(), settings=settings,
    )
    assert blocked is True
    assert "live_oct1_chase" in reason
    assert meta.get("liveOct1PadGuard") is True
