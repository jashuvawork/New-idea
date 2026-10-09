"""Oct 1 / Frozen Oct — drop post-Oct session halts and harsh selector rejects."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.expiry_day_guards import check_expiry_entry_allowed
from app.engines.rally_capture import explosion_near_miss_waive
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import AutoTraderState, MarketPhase, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _frozen_paper_settings(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=True,
        aggressive_min_explosion_score=45.0,
        expiry_worst_day_halt_entries=True,
        expiry_morning_only=True,
        **kwargs,
    )


@patch("app.config.get_settings")
def test_oct_paper_elite_negative_velocity_not_rejected(mock_settings):
    mock_settings.return_value = _frozen_paper_settings()
    evidence = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "velocity3s": -0.5,
        "velocity9s": 2.0,
        "ictArmedBaseLaunch": True,
        "armedBaseLaunch": True,
        "localBaseMovePct": 12.0,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] != "REJECT"


@patch("app.config.get_settings")
def test_non_paper_still_rejects_negative_velocity(mock_settings):
    mock_settings.return_value = settings_mock(
        october_frozen_profile_enabled=False,
        enable_live_trading=True,
        aggressive_min_explosion_score=45.0,
    )
    evidence = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "velocity3s": -0.5,
        "velocity9s": 2.0,
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 12.0,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "REJECT"


def test_oct_paper_waives_first_lift_quality_near_miss():
    s = _frozen_paper_settings()
    alert = {"tier": "ELITE", "explosionScore": 100.0, "side": "PUT", "strike": 72200.0}
    assert explosion_near_miss_waive(
        alert,
        readiness_reason="first_lift_quality<45",
        settings=s,
    )


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False)
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=False)
@patch("app.engines.expiry_day_guards.predict_worst_expiry_day", return_value=(True, 80, ["chop"]))
@patch("app.engines.expiry_day_guards._session_declining", return_value=True)
def test_oct_paper_skips_expiry_declining_halt(
    _declining,
    _worst,
    _morning,
    _expiry,
    _evening,
    mock_settings,
):
    mock_settings.return_value = _frozen_paper_settings()
    state = AutoTraderState()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=72000.0,
    )
    ok, reason, _meta = check_expiry_entry_allowed(state, {"SENSEX": snap})
    assert ok is True
    assert reason == "ok"


@patch("app.engines.whipsaw_guards.get_settings")
def test_oct_paper_skips_whipsaw_pause(mock_settings):
    from app.engines.whipsaw_guards import check_session_whipsaw_pause

    mock_settings.return_value = _frozen_paper_settings(whipsaw_guards_enabled=True)
    paused, reason, meta = check_session_whipsaw_pause(AutoTraderState(), {})
    assert paused is False
    assert meta.get("octPaperWhipsawSkipped") is True


@patch("app.config.get_settings")
@patch("app.engines.power_hour_guards.in_power_hour_window", return_value=True)
def test_oct_paper_skips_power_hour_top_only(_window, mock_settings):
    from app.engines.power_hour_guards import check_power_hour_session_allowed

    mock_settings.return_value = _frozen_paper_settings()
    ok, reason, meta = check_power_hour_session_allowed(AutoTraderState(), {})
    assert ok is True
    assert reason == "ok"
    assert meta.get("octPaperPowerHourSkipped") is True


@patch("app.engines.chop_live_guards.get_settings")
@patch("app.engines.chop_live_guards.chop_live_guard_day_active", return_value=True)
def test_oct_paper_skips_chop_live_entry_block(_day, mock_settings):
    from app.engines.chop_live_guards import chop_live_entry_blocked
    from types import SimpleNamespace

    mock_settings.return_value = _frozen_paper_settings()
    candidate = SimpleNamespace(mode="explosion", side="PUT", symbol="SENSEX")
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=72000.0,
    )
    blocked, reason, meta = chop_live_entry_blocked(
        candidate, snap, AutoTraderState(), snapshots={"SENSEX": snap},
    )
    assert blocked is False
    assert meta.get("octPaperChopWireSkipped") is True


def test_oct_paper_waives_explosion_score_near_miss():
    s = _frozen_paper_settings()
    alert = {"tier": "ELITE", "explosionScore": 88.0, "side": "PUT", "strike": 72200.0}
    assert explosion_near_miss_waive(
        alert,
        readiness_reason="explosion_score_below_min",
        settings=s,
    )


@patch("app.engines.live_entry_score.compute_live_entry_score")
@patch("app.engines.live_entry_score.get_settings")
def test_oct_paper_skips_live_entry_score_floor_for_hot_elite(
    mock_settings, mock_compute,
):
    from types import SimpleNamespace

    from app.engines.live_entry_score import live_entry_score_blocks_entry

    mock_settings.return_value = _frozen_paper_settings(
        live_entry_score_min_elite=52.0,
        premium_vertical_chase_block_enabled=False,
        premium_post_spike_dump_guard_enabled=False,
    )
    mock_compute.return_value = (40.0, {"liveEntryScore": 40.0})
    candidate = SimpleNamespace(
        tier="ELITE",
        liveEntryScore=40.0,
        alert={
            "tier": "ELITE",
            "explosionScore": 100.0,
            "velocity3s": -1.0,
            "premium": 120.0,
        },
        explosion_event=None,
    )
    blocked, reason, meta = live_entry_score_blocks_entry(candidate, None)
    assert blocked is False
    assert reason == "ok"
    assert meta.get("octPaperLiveEntryScoreFloorSkipped") is True

    mock_settings.return_value = settings_mock(
        enable_live_trading=True,
        october_frozen_profile_enabled=False,
        live_entry_score_min_elite=52.0,
        premium_vertical_chase_block_enabled=False,
        premium_post_spike_dump_guard_enabled=False,
    )
    blocked_legacy, reason_legacy, _ = live_entry_score_blocks_entry(candidate, None)
    assert blocked_legacy is True
    assert "live_entry_score_40_below_52" in reason_legacy


@patch("app.engines.sep917_live_checklist.get_settings")
def test_oct_paper_skips_sep917_checklist_when_enforcement_on(mock_settings):
    from types import SimpleNamespace

    from app.engines.sep917_live_checklist import sep917_live_checklist_entry_blocked

    mock_settings.return_value = _frozen_paper_settings(
        sep917_live_checklist_enforcement_enabled=True,
    )
    candidate = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side="CALL",
        alert={"tier": "BUILDING", "explosionScore": 50.0},
    )
    blocked, reason, meta = sep917_live_checklist_entry_blocked(
        None,
        candidate,
        None,
        settings=mock_settings.return_value,
    )
    assert blocked is False
    assert meta.get("octPaperSep917ChecklistSkipped") is True
