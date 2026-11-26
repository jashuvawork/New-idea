"""Order-boundary preflight — stale SELECT must not pass a dumping premium tape."""

from __future__ import annotations

from types import SimpleNamespace

from app.config import Settings
from app.engines.execution_order_preflight import execution_order_preflight_blocked
from app.models.schemas import PremiumChart, Side


def _candidate(**kw):
    base = dict(
        symbol="SENSEX",
        side=Side.CALL,
        strike=84400.0,
        alert={
            "symbol": "SENSEX",
            "side": "CALL",
            "strike": 84400.0,
            "premium": 122.0,
            "velocity3s": 1.2,
            "fastBullishLocalBase": True,
            "callAtBaseBestTradeReason": "call_rally_unlock",
        },
        explosion_event=SimpleNamespace(
            symbol="SENSEX",
            side=Side.CALL,
            strike=84400.0,
            premium=122.0,
            velocity_3s=1.2,
            velocity_9s=0.5,
        ),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_preflight_blocks_post_spike_dump_flag_on_chart():
    settings = Settings()
    cand = _candidate()
    prem = PremiumChart(
        lastPremium=122.0,
        momentum3Pct=1.4,
        momentum5Pct=5.4,
        direction="BULLISH",
        drawdownFromHighPct=-18.0,
        postSpikeDump=True,
    )
    blocked, reason, _ = execution_order_preflight_blocked(
        cand, None, premium_chart=prem, settings=settings,
    )
    assert blocked is True
    assert reason == "exec_preflight_post_spike_dump"


def test_preflight_blocks_falling_momentum():
    settings = Settings()
    cand = _candidate()
    prem = PremiumChart(
        lastPremium=440.0,
        momentum3Pct=-0.4,
        momentum5Pct=-1.0,
        direction="NEUTRAL",
        drawdownFromHighPct=-30.0,
        postSpikeDump=False,
    )
    blocked, reason, _ = execution_order_preflight_blocked(
        cand, None, premium_chart=prem, settings=settings,
    )
    assert blocked is True
    assert reason == "exec_preflight_falling_premium_momentum"


def test_preflight_blocks_bearish_premium_in_drawdown():
    settings = Settings()
    cand = _candidate()
    prem = PremiumChart(
        lastPremium=100.0,
        momentum3Pct=-0.6,
        momentum5Pct=-1.2,
        direction="BEARISH",
        drawdownFromHighPct=-15.0,
        postSpikeDump=False,
    )
    blocked, reason, _ = execution_order_preflight_blocked(
        cand, None, premium_chart=prem, settings=settings,
    )
    assert blocked is True
    assert reason == "exec_preflight_bearish_premium_tape"


def test_preflight_forces_alert_dump_without_global_guard_toggle():
    settings = Settings()
    settings.premium_post_spike_dump_guard_enabled = False
    settings.execution_order_preflight_force_post_spike_dump = True
    settings.execution_order_preflight_min_live_score_recheck = False
    cand = _candidate(
        alert={
            "symbol": "SENSEX",
            "side": "CALL",
            "strike": 84400.0,
            "premium": 130.0,
            "velocity3s": -0.5,
            "velocity9s": -0.6,
            "sessionPeakPremium": 240.0,
            "sessionLowPremium": 90.0,
            "fastBullishLocalBase": True,
            "callAtBaseBestTradeReason": "call_rally_unlock",
        },
    )
    blocked, reason, meta = execution_order_preflight_blocked(
        cand, None, premium_chart=None, settings=settings,
    )
    assert blocked is True
    assert reason == "exec_preflight_premium_post_spike_dump"
    assert meta.get("alertDumpRecheck", {}).get("active") is True