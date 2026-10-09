"""Oct 9 2026 — ELITE radar with silent selector drops (open rip selector feed RCA)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.trade_selector import (
    _explosion_candidates,
    _high_signal_pre_candidate_skip_reason,
    diagnose_selector_feed_gaps,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _oct9_gap_open_elite_otm_alert() -> dict:
    """NIFTY CALL 22450-style: ELITE 100 on open rip, tradeable but OTM without shallow waiver."""
    return {
        "id": "oct9-22450",
        "tradeable": True,
        "tier": "ELITE",
        "side": "CALL",
        "strike": 22600.0,
        "premium": 95.0,
        "explosionScore": 100.0,
        "velocity3s": 3.5,
        "velocity9s": 2.5,
        "velocity15s": 2.0,
        "volumeSurge": 2.5,
        "dailyMovePct": 18.0,
        "peakMovePct": 20.0,
        "localBaseMovePct": 12.0,
        "momentType": "v_rip_session_low",
        "vRipReady": True,
        "ictVRipReady": True,
    }


def _snap(alerts: list[dict]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22380.0,
        atmStrike=22400.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=70.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.15,
            trendStrength=70,
            emaBias="BULLISH",
            candleBias="BULLISH",
            macdBias="BULLISH",
        ),
        explosionAlerts=alerts,
        suggestedTrades=[],
    )


@patch("app.services.radar_learning.record_funnel_gate_block")
def test_high_signal_otm_skip_records_selector_gate(mock_gate):

    settings = settings_mock(
        explosion_capture_mode=True,
        explosion_shallow_otm_entry_enabled=True,
        explosion_shallow_otm_entry_steps=1,
        explosion_elite_exploding_only=True,
    )
    alert = _oct9_gap_open_elite_otm_alert()
    snap = _snap([alert])
    state = AutoTraderState()

    with patch("app.engines.trade_selector.get_settings", return_value=settings):
        reason = _high_signal_pre_candidate_skip_reason(
            "NIFTY", alert, snap, state, settings,
        )
    assert reason == "explosion_otm_shallow_not_allowed"

    with patch("app.engines.trade_selector.get_settings", return_value=settings):
        candidates = _explosion_candidates("NIFTY", snap, state, settings)
    assert candidates == []
    assert mock_gate.called
    args = mock_gate.call_args_list[-1][0]
    assert args[0] == "NIFTY"
    assert args[1] == "CALL"
    assert args[2] == 22600.0
    assert args[3] == "explosion_otm_shallow_not_allowed"


@patch("app.engines.trade_selector.get_settings")
def test_diagnose_selector_feed_gaps_surfaces_otm_elite(mock_get_settings):
    settings = settings_mock(
        explosion_shallow_otm_entry_enabled=True,
        explosion_shallow_otm_entry_steps=1,
    )
    mock_get_settings.return_value = settings
    alert = _oct9_gap_open_elite_otm_alert()
    snap = _snap([alert])
    notes = diagnose_selector_feed_gaps({"NIFTY": snap}, AutoTraderState())
    assert len(notes) == 1
    assert notes[0]["reason"] == "explosion_otm_shallow_not_allowed"
    assert notes[0]["strike"] == 22600.0
