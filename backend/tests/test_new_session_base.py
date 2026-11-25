"""New session base identification — trough vs post-rip pullback coil."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import _open_key
from app.engines.new_session_base import (
    alert_pad_move_pct,
    new_session_base_near_miss_waive,
    new_session_base_identify,
    resolve_effective_base_premium_inr,
    session_base_guard_summary,
    session_base_observability_bundle,
    stamp_new_session_base_fields,
)
from app.models.schemas import Side
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.new_session_base_identify_enabled = True
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