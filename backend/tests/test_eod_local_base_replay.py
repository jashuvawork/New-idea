"""EOD local-base replay — production gates on stored premium tape."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.eod_local_base_replay import (
    _enrich_alert_from_contract,
    evaluate_local_base_entry,
    generate_eod_local_base_replay,
    replay_local_base_day,
    _spot_chart_from_history,
)
from app.models.schemas import MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _bullish_chart(spot: float = 77000.0) -> SpotChart:
    return SpotChart(
        direction="BULLISH",
        spot=spot,
        momentum5Pct=0.08,
        momentum10Pct=0.05,
        momentum15Pct=0.02,
    )


def _bearish_chart(spot: float = 77000.0) -> SpotChart:
    return SpotChart(
        direction="BEARISH",
        spot=spot,
        momentum5Pct=-0.08,
        momentum10Pct=-0.05,
        momentum15Pct=-0.02,
    )


def _snap(side: str = "CALL", chart: SpotChart | None = None) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77000.0,
        atmStrike=77000.0,
        spotChart=chart or _bullish_chart(),
        tradeQualityScore=60.0,
    )


def test_enrich_alert_merges_tape_volume():
    alert = {"ictArmedBaseLaunch": True, "volume": 0}
    contract = {"volume": 71_736_060.0, "volumeSurge": 2.5, "velocity3s": 1.2}
    merged = _enrich_alert_from_contract(alert, contract)
    assert merged["volume"] == 71_736_060.0
    assert merged["volumeAwaken"] is True


def test_spot_chart_from_history_builds_momentum():
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=IST)
    hist = [(t0 + timedelta(seconds=30 * i), 77000.0 + i * 8.0) for i in range(20)]
    chart = _spot_chart_from_history(hist, 77160.0)
    assert chart.momentum5Pct > 0


def test_evaluate_local_base_entry_blocks_non_top_moment():
    snap = _snap()
    alert = {
        "tier": "BUILDING",
        "explosionScore": 50,
        "premium": 95.0,
        "side": "CALL",
        "strike": 77000.0,
    }
    allowed, reason, _, _ = evaluate_local_base_entry(alert, snap)
    assert not allowed
    assert reason == "not_top_moment_radar"


@patch("app.engines.eod_local_base_replay.get_settings")
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_evaluate_local_base_entry_passes_v_rip(mock_lift, mock_settings):
    mock_settings.return_value = MagicMock(
        top_moments_only_enabled=True,
        top_moments_min_grade="A",
        explosion_min_premium_inr=15.0,
    )
    mock_lift.return_value = (True, "v_rip_session_low_ready")
    snap = _snap(chart=_bullish_chart())
    alert = {
        "tier": "EXPLODING",
        "explosionScore": 72,
        "premium": 95.0,
        "side": "CALL",
        "strike": 77000.0,
        "ictVRipReady": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 8.0,
        "velocity3s": 2.5,
        "velocity9s": 1.5,
        "volumeSurge": 2.5,
        "ictFirstLift": True,
    }
    allowed, reason, moment, ranking = evaluate_local_base_entry(alert, snap)
    assert allowed
    assert moment == "V"
    assert ranking.get("grade") in ("A", "S", "B")


@patch("app.engines.eod_local_base_replay.get_settings")
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_evaluate_local_base_entry_rejects_failed_lift(mock_lift, mock_settings):
    mock_settings.return_value = MagicMock(
        top_moments_only_enabled=True,
        top_moments_min_grade="A",
        explosion_min_premium_inr=15.0,
    )
    mock_lift.return_value = (False, "first_lift_index_turn_not_confirmed")
    snap = _snap(chart=_bearish_chart())
    alert = {
        "tier": "ELITE",
        "explosionScore": 80,
        "premium": 120.0,
        "side": "CALL",
        "strike": 77000.0,
        "ictEliteBaseReady": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 4.0,
        "velocity3s": 3.0,
        "velocity9s": 2.0,
        "volumeSurge": 3.0,
    }
    allowed, reason, _, _ = evaluate_local_base_entry(alert, snap)
    assert not allowed
    assert reason == "first_lift_index_turn_not_confirmed"


def test_replay_local_base_day_no_tape():
    with patch(
        "app.engines.eod_local_base_replay._load_batches",
        return_value=[],
    ):
        rep = replay_local_base_day("2026-08-22")
    assert rep["status"] == "no_tape"


def test_generate_eod_local_base_replay_includes_comparison():
    date = "2026-08-19"
    with (
        patch(
            "app.engines.eod_local_base_replay.replay_local_base_day",
            return_value={
                "date": date,
                "status": "ok",
                "netPnlInr": 1000,
                "tradeCount": 1,
                "trades": [],
            },
        ),
        patch(
            "app.engines.eod_trade_report.generate_eod_trade_report",
            return_value={
                "date": date,
                "status": "ok",
                "netPnlInr": 500,
                "tradeCount": 2,
                "note": "legacy",
            },
        ),
    ):
        rep = generate_eod_local_base_replay(date)
    assert rep["comparison"]["deltaPnlInr"] == 500
    assert rep["comparison"]["legacyEodReport"]["tradeCount"] == 2
