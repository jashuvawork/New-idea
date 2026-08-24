"""Local-base pad capture — volume stamp, chart bypass, softened TOP_FTV_A."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_detector import (
    _local_base_hist,
    _open_key,
    align_armed_candidate_evidence,
    armed_base_anchor,
    enrich_alert_armed_evidence,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import (
    _defensive_base_rip_top_allowed,
    first_lift_entry_readiness,
)
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _armed_replay_snapshot(*, tqs: float = 55.0, spot: float = 24200.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=tqs,
        spot=spot,
        atmStrike=spot,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.08,
            momentum10Pct=-0.04,
            momentum15Pct=-0.01,
        ),
    )


def _seed_armed_base(settings: Settings):
    reset_detector_state_for_tests()
    key = _open_key("NIFTY", 24200.0, Side.PUT)
    start = datetime.now(IST) - timedelta(seconds=30)
    _local_base_hist[key] = deque(
        (
            start + timedelta(seconds=index * 3),
            premium,
        )
        for index, premium in enumerate(
            (21.55, 21.65, 21.60, 21.70, 21.58, 21.68, 21.57, 21.62)
        )
    )
    return armed_base_anchor("NIFTY", 24200.0, Side.PUT, 24.5, settings=settings)


def test_enrich_alert_armed_evidence_stamps_volume_from_persisted():
    alert = {
        "ictBaseArmed": True,
        "ictBaseArmedAt": "2026-08-24T11:00:00+05:30",
        "volume": 0,
        "ictArmedEvidence": {
            "armedAt": "2026-08-24T11:00:00+05:30",
            "volume": 72_000,
            "velocity3s": 1.4,
            "orderflowConfirmed": True,
            "volumeAwakening": True,
        },
    }
    merged = enrich_alert_armed_evidence(alert)
    assert merged["volume"] == 72_000
    assert merged["absoluteVolume"] == 72_000
    assert merged["orderflowConfirmed"] is True
    assert merged["volumeAwaken"] is True


def test_first_lift_uses_persisted_volume_when_alert_volume_zero():
    settings = Settings()
    anchor = _seed_armed_base(settings)
    persisted = align_armed_candidate_evidence(
        "NIFTY",
        24200.0,
        Side.PUT,
        {
            "explosionScore": 92.0,
            "flatVerticalQuality": 78.0,
            "tradeQualityScore": 55.0,
            "velocity3s": 2.1,
            "velocity9s": 1.8,
            "volume": 80_000,
            "orderflowConfirmed": True,
            "volumeAwakening": True,
            "armedLaunch": True,
            "flatThenVertical": True,
            "activeBreakout": True,
            "sampleCount": anchor["sampleCount"],
            "spanSeconds": anchor["spanSeconds"],
        },
    )
    alert = {
        "side": "PUT",
        "strike": 24200.0,
        "tier": "EXPLODING",
        "ictBaseArmed": True,
        "ictBaseArmedAt": anchor["armedAt"],
        "ictArmedBaseLaunch": True,
        "ictFirstLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": True,
        "ictArmedBaseSamples": anchor["sampleCount"],
        "ictArmedBaseSpanSeconds": anchor["spanSeconds"],
        "flatVerticalQuality": 78.0,
        "explosionScore": 92.0,
        "velocity3s": 2.1,
        "velocity9s": 1.8,
        "volume": 0,
        "premium": 30.0,
        "ictBaseRelativeMovePct": 22.7,
        "ictArmedEvidence": persisted,
    }
    with patch(
        "app.engines.ict_breakout_monitor.get_settings",
        return_value=settings,
    ):
        ok, reason = first_lift_entry_readiness(
            snap=_armed_replay_snapshot(),
            alert=alert,
        )
    assert ok is True
    assert reason == "armed_base_option_led_ready"
    assert "orderflow_below" not in reason


def test_top_ftv_a_pad_lane_softens_velocity_at_11pct():
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 92.0,
        "tqs": 58.0,
        "velocity3s": 1.5,
        "velocity9s": 1.0,
        "localBaseMovePct": 11.6,
        "vRipReady": True,
        "volumeAwaken": True,
        "orderflowPositive": True,
        "armedBaseLaunch": True,
        "firstLift": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "cvdBuying": True,
        "cvdAcceleration": True,
        "flatVerticalQuality": 82.0,
        "timingAssessment": "GOOD",
        "indexHelpersConfirm": True,
    }
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "A"
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is True
    assert decision.mode == "TOP_FTV_A"


def test_top_ftv_a_pad_lane_waives_cvd_when_volume_awake_and_helpers():
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 92.0,
        "tqs": 58.0,
        "velocity3s": 2.6,
        "velocity9s": 1.8,
        "localBaseMovePct": 11.0,
        "vRipReady": True,
        "volumeAwaken": True,
        "armedBaseLaunch": True,
        "firstLift": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "cvdBuying": False,
        "cvdAcceleration": False,
        "flatVerticalQuality": 82.0,
        "timingAssessment": "GOOD",
        "indexHelpersConfirm": True,
    }
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is True
    assert decision.mode in {"TOP_FTV_A", "S_STRICT"}


def test_defensive_rip_top_softens_velocity_in_pad_lane():
    settings = MagicMock()
    settings.ict_defensive_base_rip_require_top_quality = True
    settings.ict_defensive_base_rip_min_score = 80.0
    settings.ict_defensive_base_rip_min_quality = 70.0
    settings.ict_defensive_base_rip_min_velocity_3s = 2.5
    settings.top_ftv_a_pad_velocity_min_move_pct = 8.0
    settings.top_ftv_a_pad_velocity_max_move_pct = 25.0
    settings.ict_v_rip_pad_min_move_pct = 15.0
    settings.ict_v_rip_volume_awake_min_velocity_3s = 0.85
    settings.ict_v_rip_min_velocity_3s = 1.2
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=82.0,
        score=92.0,
        velocity_3s=1.8,
        settings=settings,
        base_move_pct=11.6,
        volume_awake=True,
        v_rip_ready=True,
    )
    assert ok is True
    assert reason == "ok"


def test_pretrade_chart_bypass_includes_v_rip_session_low_ready():
    from pathlib import Path

    source = Path("app/engines/pretrade_validator.py").read_text()
    assert '"v_rip_session_low_ready"' in source
    assert source.index('"v_rip_session_low_ready"') > source.index(
        "armed_base_chart_bypass"
    )
