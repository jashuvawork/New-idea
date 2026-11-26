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


def test_preflight_live_extended_blocks_neg_mom3_while_mom5_positive():
    """Nov26 chase: mom5 still + at wire while premium fades — armed paper + live parity."""
    paper_settings = Settings(
        enable_live_trading=False,
        auto_trading_enabled=True,
        paper_trading=True,
        execution_order_preflight_min_live_score_recheck=False,
    )
    live_settings = Settings(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=False,
        execution_order_preflight_min_live_score_recheck=False,
    )
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 25850.0,
        "premium": 95.0,
        "sessionRangePosition": 0.97,
        "localPadPct": 12.0,
    }
    cand = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=25850.0,
        alert=alert,
        explosion_event=None,
    )
    prem = PremiumChart(
        lastPremium=95.0,
        momentum3Pct=-0.35,
        momentum5Pct=2.1,
        direction="NEUTRAL",
        drawdownFromHighPct=-5.0,
        postSpikeDump=False,
    )
    for settings in (paper_settings, live_settings):
        blocked, reason, meta = execution_order_preflight_blocked(
            cand, None, premium_chart=prem, settings=settings,
        )
        assert blocked is True
        assert reason == "exec_preflight_live_extended_fade_mom3"
        assert meta.get("liveExtendedChaseContext", {}).get("liveExtendedChase") is True


def test_preflight_live_near_base_allows_shallow_fade_retest():
    live_settings = Settings(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=False,
        execution_order_preflight_min_live_score_recheck=False,
    )
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "strike": 84000.0,
        "premium": 180.0,
        "sessionRangePosition": 0.22,
        "localPadPct": 3.5,
        "fastBullishLocalBase": True,
    }
    cand = SimpleNamespace(
        symbol="SENSEX",
        side=Side.CALL,
        strike=84000.0,
        alert=alert,
        explosion_event=None,
    )
    prem = PremiumChart(
        lastPremium=180.0,
        momentum3Pct=-0.2,
        momentum5Pct=1.5,
        direction="BULLISH",
        drawdownFromHighPct=-1.0,
        postSpikeDump=False,
    )
    blocked, reason, _ = execution_order_preflight_blocked(
        cand, None, premium_chart=prem, settings=live_settings,
    )
    assert blocked is False
    assert reason == "ok"


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