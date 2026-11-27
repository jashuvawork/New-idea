"""New session base identification — trough vs post-rip pullback coil."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import _open_key, armed_base_anchor
from app.engines.new_session_base import (
    alert_pad_move_pct,
    new_session_base_near_miss_waive,
    new_session_base_identify,
    resolve_effective_base_premium_inr,
    session_base_guard_summary,
    session_base_observability_bundle,
    stamp_new_session_base_fields,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.new_session_base_identify_enabled = True
    s.new_session_base_session_trough_stamp_enabled = True
    s.new_session_base_trough_min_fall_from_peak_pct = 0.08
    s.new_session_base_trough_max_off_low_pct = 14.0
    s.new_session_base_post_rip_min_session_run_pct = 0.30
    s.new_session_base_post_rip_min_peak_pullback_pct = 0.12
    s.new_session_base_post_rip_max_pad_pct = 18.0
    s.new_session_base_post_rip_min_velocity_3s = 0.8
    s.new_session_base_stale_ict_gap_pct = 12.0
    return s


def _seed_session(symbol, strike, side, low, peak):
    key = _open_key(symbol, strike, side)
    ed._session_low[key] = float(low)
    ed._session_peak[key] = float(peak)
    ed._session_date = datetime.now(IST).strftime("%Y-%m-%d")


def _seed_tape(symbol, strike, side, prems, *, step_s=30.0):
    key = _open_key(symbol, strike, side)
    t0 = datetime(2026, 11, 25, 12, 0, 0, tzinfo=IST)
    from collections import deque

    ed._local_base_hist[key] = deque(
        (t0 + timedelta(seconds=step_s * i), float(p)) for i, p in enumerate(prems)
    )


def teardown_function(_):
    ed._session_low.clear()
    ed._session_peak.clear()
    ed._local_base_hist.clear()
    ed._armed_base_anchors.clear()


def test_session_trough_stamp_disabled_by_default():
    s = settings_mock()
    s.new_session_base_identify_enabled = True
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    ok, kind, _ = new_session_base_identify(
        "SENSEX", 83600.0, Side.PUT, 190.0, settings=s,
    )
    assert ok is False
    assert kind == ""


def test_session_trough_rejects_chase_at_session_high():
    """Nov26 class: few % off session low but still at session premium peak."""
    s = _settings()
    _seed_session("SENSEX", 84000.0, Side.CALL, 372.85, 414.0)
    ok, kind, meta = new_session_base_identify(
        "SENSEX", 84000.0, Side.CALL, 383.97, settings=s,
    )
    assert ok is False
    assert kind == ""
    assert meta.get("fallFromPeakPct", 100) < 8.0


def test_identifies_session_trough_base():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    ok, kind, meta = new_session_base_identify(
        "SENSEX",
        83600.0,
        Side.PUT,
        190.0,
        settings=_settings(),
    )
    assert ok is True
    assert kind == "session_trough"
    assert meta["effectiveBasePremium"] == 175.0


def test_identifies_post_rip_pullback_coil():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    coil = [500, 498, 495, 492, 490, 488, 200, 198, 196, 198, 202]
    _seed_tape("SENSEX", 83600.0, Side.PUT, coil)
    ok, kind, meta = new_session_base_identify(
        "SENSEX",
        83600.0,
        Side.PUT,
        205.0,
        velocity_3s=1.5,
        stale_ict_base=418.0,
        settings=_settings(),
    )
    assert ok is True
    assert kind == "post_rip_pullback"
    assert meta["effectiveBasePremium"] <= 205.0
    assert meta["effectiveBasePremium"] >= 196.0


def test_stamp_merges_alert_fields():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    row = stamp_new_session_base_fields(
        {"symbol": "SENSEX", "ictBasePremium": 418.0},
        symbol="SENSEX",
        strike=83600.0,
        side=Side.PUT,
        premium=190.0,
        settings=_settings(),
    )
    assert row.get("newSessionBase") is True
    assert float(row["localBaseBasePremium"]) == 175.0


def test_resolve_prefers_effective_over_stale_ict():
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    prem, meta = resolve_effective_base_premium_inr(
        {"newSessionBase": True, "effectiveBasePremium": 175.0, "ictBasePremium": 418.0},
        settings=_settings(),
    )
    assert prem == 175.0
    assert meta.get("fromAlert") is True


def test_session_base_guard_summary_keys():
    s = session_base_guard_summary(_settings())
    assert s["newSessionBaseIdentifyEnabled"] is True
    assert s["newSessionBaseSessionTroughStampEnabled"] is True
    assert s["explosionSessionRipFallBlockEnabled"] is True
    assert s["fakeExplosionTrapPostWinArmedBaseBypassEnabled"] is False


def test_alert_pad_move_pct_from_effective_base():
    pad = alert_pad_move_pct(
        {
            "newSessionBase": True,
            "effectiveBasePremium": 100.0,
            "premium": 108.0,
        }
    )
    assert pad == pytest.approx(8.0, abs=0.1)


def test_near_miss_waive_at_trough_building():
    alert = {
        "newSessionBase": True,
        "newBaseKind": "session_trough",
        "localBaseMovePct": 8.0,
        "tier": "BUILDING",
        "explosionScore": 24,
        "velocity3s": 1.2,
    }
    assert new_session_base_near_miss_waive(alert, settings=_settings()) is True


def test_near_miss_waive_rejects_chase_pad():
    alert = {
        "newSessionBase": True,
        "localBaseMovePct": 35.0,
        "tier": "ELITE",
        "explosionScore": 40,
        "velocity3s": 2.0,
    }
    assert new_session_base_near_miss_waive(alert, settings=_settings()) is False


def _slide_snap() -> SymbolSnapshot:
    IST = ZoneInfo("Asia/Kolkata")
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.05),
        chartAnalysis=ChartAnalysis(consensus="BEARISH"),
    )


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {"rallyPoints": 20, "slidePoints": 60}),
)
def test_call_base_rejected_on_index_slide_leg(_m0, _m1):
    """CE must not stamp a session base when index participation is slide."""
    _seed_session("NIFTY", 25750.0, Side.CALL, 200.0, 280.0)
    ok, kind, meta = new_session_base_identify(
        "NIFTY",
        25750.0,
        Side.CALL,
        215.0,
        snap=_slide_snap(),
        state=AutoTraderState(),
        settings=_settings(),
    )
    assert ok is False
    assert kind == ""
    assert meta.get("indexBaseFormationBlocked") == "index_base_counter_participation"


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {}),
)
def test_put_base_allowed_on_index_slide_leg(_m0, _m1):
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    ok, kind, _ = new_session_base_identify(
        "SENSEX",
        83600.0,
        Side.PUT,
        190.0,
        snap=_slide_snap(),
        state=AutoTraderState(),
        settings=_settings(),
    )
    assert ok is True
    assert kind == "session_trough"


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {}),
)
def test_resolve_rejects_stale_ict_base_on_counter_index_leg(_m0, _m1):
    """Legacy ictBasePremium must not chase CE when participation is slide."""
    prem, meta = resolve_effective_base_premium_inr(
        {"ictBasePremium": 210.0, "symbol": "NIFTY", "side": "CALL", "strike": 25750.0},
        premium=232.0,
        snap=_slide_snap(),
        settings=_settings(),
    )
    assert prem == 0.0
    assert meta.get("indexBaseFormationBlocked") == "index_base_counter_participation"
    assert meta.get("indexBaseIctFallbackRejected") == "ictBasePremium"


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {}),
)
def test_resolve_rejects_matching_fallback_not_ict_row(_m0, _m1):
    """Resolver must not return the same INR passed as fallback after ICT veto."""
    prem, meta = resolve_effective_base_premium_inr(
        {"ictBasePremium": 210.0, "symbol": "NIFTY", "side": "CALL", "strike": 25750.0},
        premium=232.0,
        fallback=210.0,
        snap=_slide_snap(),
        settings=_settings(),
    )
    assert prem == 0.0
    assert meta.get("indexBaseIctFallbackRejected") == "ictBasePremium"


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {}),
)
def test_ict_breakout_probe_respects_participation_with_snap(_m0, _m1):
    from collections import deque
    from datetime import timedelta

    from app.engines.ict_breakout_monitor import analyze_ict_breakout

    ed._armed_base_anchors.clear()
    settings = _settings()
    side = Side.CALL
    key = _open_key("NIFTY", 25750.0, side)
    start = datetime.now(IST) - timedelta(seconds=30)
    ed._local_base_hist[key] = deque(
        [(start + timedelta(seconds=i * 3), 52.8 + (i % 2) * 0.2) for i in range(8)],
        maxlen=1200,
    )
    _seed_session("NIFTY", 25750.0, side, 52.0, 120.0)
    snap = _slide_snap()
    sig = analyze_ict_breakout(
        symbol="NIFTY",
        side=side,
        strike=25750.0,
        premium=57.0,
        session_move_pct=8.0,
        peak_move_pct=8.0,
        velocity_3s=1.2,
        velocity_9s=0.8,
        volume_surge=1.5,
        volume=100000.0,
        tier="WATCH",
        reason="probe",
        snap=snap,
    )
    assert not sig.base_armed


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {}),
)
def test_armed_base_call_blocked_on_index_slide(_m0, _m1):
    from collections import deque
    from datetime import timedelta

    ed._armed_base_anchors.clear()
    settings = _settings()
    side = Side.CALL
    key = _open_key("NIFTY", 25750.0, side)
    start = datetime.now(IST) - timedelta(seconds=30)
    ed._local_base_hist[key] = deque(
        [(start + timedelta(seconds=i * 3), 52.8 + (i % 2) * 0.2) for i in range(8)],
        maxlen=1200,
    )
    _seed_session("NIFTY", 25750.0, side, 52.0, 120.0)
    armed = armed_base_anchor(
        "NIFTY",
        25750.0,
        side,
        57.0,
        snap=_slide_snap(),
        settings=settings,
    )
    assert armed.get("armed") is False
    assert armed.get("indexBaseFormationBlocked") == "index_base_counter_participation"


def test_observability_bundle_merges_rip_fall_and_alert():
    bundle = session_base_observability_bundle(
        alert={"newSessionBase": True, "newBaseKind": "session_trough", "effectiveBasePremium": 21.0},
        pretrade_meta={
            "sessionRipFall": {
                "sessionRipFallExempt": "near_session_trough",
                "liftFromTroughPct": 8.0,
            }
        },
    )
    assert bundle["newSessionBase"] is True
    assert bundle["sessionRipFallExempt"] == "near_session_trough"
    assert bundle["effectiveBasePremium"] == 21.0