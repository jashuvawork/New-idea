"""Outcome labels, hindsight recall, funnel analytics, health, replay, and backups."""

from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.routers.ai import radar_replay
from app.models.schemas import PaperTrade, Side
from app.services import trade_store
from app.services.radar_archive import read_archive_entries, record_top_radars
from app.services.radar_health import (
    health_status,
    record_component_error,
    record_source,
    reset_health_for_tests,
)
from app.services.radar_learning import (
    RadarOperationBusyError,
    analyze_hindsight,
    backup_archive,
    build_funnel_report,
    finalize_daily_review,
    finalize_pending_reviews,
    funnel_path,
    pipeline_history_summary,
    premium_tape_path,
    read_alerts_tape,
    read_pipeline_history,
    read_premium_tape,
    record_funnel_state,
    record_funnel_event,
    record_market_observations,
    reset_learning_state_for_tests,
    restore_local_base_history,
    run_detector_replay_isolated,
)
from app.services import radar_learning

IST = ZoneInfo("Asia/Kolkata")


def _settings(tmp_path, **overrides):
    values = {
        "trade_store_dir": str(tmp_path),
        "radar_archive_enabled": True,
        "radar_archive_dir": "",
        "radar_archive_top_n_per_day": 100,
        "radar_archive_retention_days": 7,
        "radar_learning_enabled": True,
        "radar_premium_tape_sample_seconds": 15,
        "radar_analysis_only_storage": True,
        "radar_purge_telemetry_after_finalize": True,
        "radar_alerts_tape_enabled": False,
        "radar_pipeline_history_enabled": False,
        "radar_outcome_horizons_seconds_csv": "60,300",
        "radar_outcome_target_pct": 20.0,
        "radar_outcome_stop_pct": 10.0,
        "radar_hindsight_flat_window_seconds": 120,
        "radar_hindsight_flat_max_range_pct": 8.0,
        "radar_hindsight_vertical_min_move_pct": 40.0,
        "radar_hindsight_lookahead_seconds": 1800,
        "radar_funnel_dedupe_seconds": 60,
        "radar_health_stale_seconds": 45,
        "full_rest_min_seconds": 5.0,
        "full_rest_backoff_seconds": 5.0,
        "radar_backup_dir": "",
        "radar_backup_s3_bucket": "",
        "radar_backup_s3_prefix": "nexusquant/radar",
        "radar_backup_retry_max": 3,
        "radar_backup_retry_base_seconds": 0.0,
        "radar_backup_verify_head": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_settings(settings):
    stack = ExitStack()
    stack.enter_context(
        patch("app.services.radar_archive.get_settings", return_value=settings)
    )
    stack.enter_context(
        patch("app.services.radar_learning.get_settings", return_value=settings)
    )
    stack.enter_context(
        patch("app.services.radar_health.get_settings", return_value=settings)
    )
    return stack


def _alert(side="CALL", strike=24500.0, premium=100.0):
    return {
        "symbol": "NIFTY",
        "side": side,
        "strike": strike,
        "premium": premium,
        "tier": "BUILDING",
        "explosionScore": 65.0,
        "tradeable": True,
        "ictFirstLift": True,
        "localBaseMovePct": 15.0,
    }


def _snap(call=100.0, put=100.0, alerts=None):
    heatmap = [
        SimpleNamespace(
            strike=24500.0,
            callLtp=call,
            putLtp=put,
            callOi=10_000,
            putOi=12_000,
        )
    ]
    return SimpleNamespace(
        dataAvailable=True,
        timestamp=datetime(2026, 8, 15, 10, 0, tzinfo=IST),
        marketPhase="LIVE_MARKET",
        symbol="NIFTY",
        spot=24500.0,
        atmStrike=24500.0,
        optionExpiry="2026-08-20",
        tradeQualityScore=70.0,
        regime="TREND_EXPANSION",
        breadth={"bias": "BULLISH"},
        spotChart={"direction": "BULLISH"},
        pcr=1.0,
        maxPain=24500.0,
        indiaVix=13.0,
        heatmap=heatmap,
        explosionAlerts=list(alerts or []),
    )


def setup_function(_):
    reset_learning_state_for_tests()
    reset_health_for_tests()


def test_forward_outcomes_capture_horizons_mfe_mae_and_order(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=start,
            source="rest_snapshot",
        )
        record_market_observations(
            {"NIFTY": _snap(call=125.0)},
            source="ws_entry_scan",
            now=start + timedelta(seconds=60),
            force=True,
        )
        record_market_observations(
            {"NIFTY": _snap(call=85.0)},
            source="ws_entry_scan",
            now=start + timedelta(seconds=300),
            force=True,
        )
        row = next(
            item for item in read_archive_entries("2026-08-15")
            if item["side"] == "CALL"
        )
        tape_rows = read_premium_tape("2026-08-15")

    outcome = row["outcome"]
    assert outcome["status"] == "WINNER"
    assert outcome["targetBeforeStop"] is True
    assert outcome["mfePct"] == 25.0
    assert outcome["maePct"] == -15.0
    assert outcome["horizons"]["60"]["movePct"] == 25.0
    assert outcome["horizons"]["300"]["movePct"] == -15.0
    assert len(tape_rows) == 2


def test_forward_outcome_keeps_tracking_strike_after_heatmap_rotation(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    initial = _snap(alerts=[_alert()])
    initial.heatmap[0].callInstrumentKey = "NSE_FO|NIFTY24500CE"
    rotated = _snap()
    rotated.heatmap[0].strike = 24600.0
    rotated.heatmap[0].callInstrumentKey = "NSE_FO|NIFTY24600CE"

    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": initial},
            now=start,
            source="rest_snapshot",
        )
        with patch(
            "app.services.tick_store.get_ltp",
            side_effect=lambda key, **_: 125.0 if key == "NSE_FO|NIFTY24500CE" else None,
        ):
            record_market_observations(
                {"NIFTY": rotated},
                source="ws_entry_scan",
                now=start + timedelta(seconds=60),
                force=True,
            )
        archived = next(
            row for row in read_archive_entries("2026-08-15")
            if row["key"] == "NIFTY:CALL:24500"
        )
        tape = read_premium_tape("2026-08-15")

    assert archived["outcome"]["status"] == "WINNER"
    fallback = next(
        contract for contract in tape[-1]["contracts"]
        if contract["key"] == "NIFTY:CALL:24500"
    )
    assert fallback["archivedTickFallback"] is True
    assert fallback["premium"] == 125.0


def test_hindsight_scorecard_finds_early_and_missed_ftv_both_sides(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert(side="CALL")])},
            now=start,
            source="rest_snapshot",
        )
        for offset, premium in ((0, 100), (30, 102), (60, 101), (90, 100), (120, 145)):
            record_market_observations(
                {"NIFTY": _snap(call=premium, put=premium)},
                source="ws_entry_scan",
                now=start + timedelta(seconds=offset),
                force=True,
            )
        report = analyze_hindsight("2026-08-15")

    assert report["truthCount"] == 2
    assert report["earlyDetected"] == 1
    assert report["missed"] == 1
    assert report["recallPct"] == 50.0
    assert report["bySide"]["CALL"]["early"] == 1
    assert report["bySide"]["PUT"]["missed"] == 1
    assert all(event["baseToVerticalSeconds"] == 30.0 for event in report["events"])


def test_hindsight_separates_visibility_executable_and_selected_precision(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    truth_key = "NIFTY:CALL:24500"
    visibility_key = "NIFTY:PUT:24500"
    executable_false_key = "NIFTY:CALL:24450"
    archives = [
        {
            "key": truth_key,
            "firstSeenAt": start.isoformat(),
            "alert": {"tradeable": False},
            "milestones": [
                {
                    "seenAt": (start + timedelta(seconds=30)).isoformat(),
                    "tradeable": True,
                }
            ],
        },
        {
            "key": visibility_key,
            "firstSeenAt": start.isoformat(),
            "alert": {"tradeable": False},
            "milestones": [
                {"seenAt": start.isoformat(), "tradeable": False}
            ],
        },
        {
            "key": executable_false_key,
            "firstSeenAt": start.isoformat(),
            "alert": {"tradeable": True},
            "milestones": [],
        },
    ]
    samples = [
        (start + timedelta(seconds=offset), premium)
        for offset, premium in (
            (0, 100.0),
            (30, 102.0),
            (60, 101.0),
            (90, 100.0),
            (120, 145.0),
        )
    ]
    funnel_events = [
        {
            "event": "SELECTED",
            "key": visibility_key,
            "ts": (start - timedelta(seconds=1)).isoformat(),
        },
        {
            "event": "SELECTED",
            "key": truth_key,
            "ts": (start + timedelta(seconds=31)).isoformat(),
        },
    ]
    observation = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24500.0,
        "spot": 24500.0,
        "atmStrike": 24500.0,
    }

    with (
        _patch_settings(settings),
        patch(
            "app.services.radar_learning.read_archive_entries",
            return_value=archives,
        ),
        patch(
            "app.services.radar_learning._premium_series",
            return_value=(
                {truth_key: samples},
                {truth_key: {start + timedelta(seconds=90): observation}},
            ),
        ),
        patch(
            "app.services.radar_learning._read_jsonl",
            return_value=funnel_events,
        ),
    ):
        report = analyze_hindsight("2026-08-15")

    assert report["truthCount"] == 1
    assert report["radarAlertCount"] == 3
    assert report["radarPrecisionPct"] == 33.3
    assert report["radarFalseAlertCount"] == 2
    assert report["precisionPct"] == report["radarPrecisionPct"]
    assert report["executableRadarCount"] == 2
    assert report["executablePrecisionPct"] == 50.0
    assert report["executableFalseAlertCount"] == 1
    assert report["visibilityOnlyCount"] == 1
    assert report["selectedRadarCount"] == 1
    assert report["selectedPrecisionPct"] == 100.0
    assert report["selectedFalseAlertCount"] == 0
    assert report["selectionEventCount"] == 2
    assert report["selectedTelemetryAvailable"] is True


def test_hindsight_excludes_penny_and_deep_otm_moves_from_recall(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)

    def snapshot(atm_call: float, atm_put: float, deep_call: float):
        snap = _snap(call=atm_call, put=atm_put)
        snap.heatmap.append(SimpleNamespace(
            strike=25000.0,
            callLtp=deep_call,
            putLtp=None,
            callOi=10_000,
            putOi=0,
        ))
        return snap

    samples = (
        (0, 100.0, 1.0, 20.0),
        (30, 102.0, 1.0, 20.0),
        (60, 101.0, 1.0, 20.0),
        (90, 100.0, 1.0, 20.0),
        (120, 145.0, 1.5, 30.0),
    )
    with _patch_settings(settings):
        for offset, atm_call, atm_put, deep_call in samples:
            record_market_observations(
                {"NIFTY": snapshot(atm_call, atm_put, deep_call)},
                source="ws_entry_scan",
                now=start + timedelta(seconds=offset),
                force=True,
            )
        report = analyze_hindsight("2026-08-15")

    assert report["rawTruthCount"] == 3
    assert report["truthCount"] == 1
    assert report["excludedTruthCount"] == 2
    assert report["excludedByReason"] == {
        "premium_below_min": 1,
        "deep_otm": 1,
    }
    assert report["events"][0]["key"] == "NIFTY:CALL:24500"
    assert {
        event["key"] for event in report["excludedEvents"]
    } == {"NIFTY:PUT:24500", "NIFTY:CALL:25000"}


def test_funnel_maps_blocker_entry_and_trade_outcome(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=start,
            source="rest_snapshot",
        )
        assert record_funnel_state(
            {"NIFTY": _snap(alerts=[_alert()])},
            [{
                "symbol": "NIFTY",
                "side": "CALL",
                "strike": 24500.0,
                "reason": "chart_alignment",
            }],
            now=start,
        ) == 1
        record_funnel_event(
            {
                "event": "SELECTED",
                "key": "NIFTY:CALL:24500",
                "stage": "selector",
                "selectionScore": 80.0,
            },
            now=start + timedelta(seconds=1),
        )
        record_funnel_event(
            {
                "event": "ORDER_REJECTED",
                "key": "NIFTY:CALL:24500",
                "stage": "preorder",
                "reason": "premium_fading",
            },
            now=start + timedelta(seconds=2),
        )
        with patch(
            "app.services.trade_store.get_day_detail",
            return_value={
                "trades": [{
                    "symbol": "NIFTY",
                    "side": "CALL",
                    "strike": 24500.0,
                    "status": "CLOSED",
                    "pnlInr": 1250.0,
                    "openedAt": (start + timedelta(seconds=3)).isoformat(),
                }]
            },
        ):
            report = build_funnel_report("2026-08-15")

    assert report["detected"] == 1
    assert report["blocked"] == 1
    assert report["entered"] == 1
    assert report["selected"] == 1
    assert report["orderRejected"] == 1
    assert report["closedWins"] == 1
    assert report["rows"][0]["blockers"] == ["chart_alignment"]


def test_ranked_out_is_deduplicated_exposed_and_not_counted_selected(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 18, 10, 40, tzinfo=IST)
    leader_key = "NIFTY:PUT:24350"
    loser_key = "NIFTY:PUT:24250"
    alerts = [
        {**_alert(), "side": "PUT", "strike": 24350.0},
        {**_alert(), "side": "PUT", "strike": 24250.0},
    ]
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=alerts)},
            now=start,
            source="rest_snapshot",
        )
        event = {
            "event": "RANKED_OUT",
            "key": loser_key,
            "symbol": "NIFTY",
            "side": "PUT",
            "strike": 24250.0,
            "stage": "selector",
            "cycleId": "aug18-1040",
            "causalGrade": "A",
            "causalRankScore": 82.0,
            "legacySelectionScore": 155.0,
            "finalRankPosition": 2,
            "leaderKey": leader_key,
            "leaderCausalGrade": "S",
            "leaderCausalRankScore": 100.0,
            "leaderLegacySelectionScore": 90.0,
        }
        assert record_funnel_event(event, now=start) is True
        assert record_funnel_event(event, now=start + timedelta(seconds=1)) is False
        record_funnel_event(
            {"event": "SELECTED", "key": leader_key, "stage": "selector"},
            now=start + timedelta(seconds=2),
        )
        with patch(
            "app.services.trade_store.get_day_detail",
            return_value={"trades": []},
        ):
            report = build_funnel_report("2026-08-18")
        selected, event_count = radar_learning._causal_selected_keys(
            "2026-08-18",
            {
                leader_key: {"firstSeenAt": start.isoformat()},
                loser_key: {"firstSeenAt": start.isoformat()},
            },
        )

    loser = next(row for row in report["rows"] if row["key"] == loser_key)
    assert report["rankedOut"] == 1
    assert report["selected"] == 1
    assert loser["rankedOut"] is True
    assert loser["selected"] is False
    assert sum(
        row["event"] == "RANKED_OUT" for row in loser["timeline"]
    ) == 1
    assert selected == {leader_key}
    assert event_count == 1


def test_funnel_never_attributes_pre_detection_events_or_trades(tmp_path):
    settings = _settings(tmp_path)
    detected = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    key = "NIFTY:CALL:24500"
    with _patch_settings(settings):
        record_funnel_event(
            {"event": "SELECTED", "key": key, "stage": "selector"},
            now=detected - timedelta(minutes=1),
        )
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=detected,
            source="rest_snapshot",
        )
        record_funnel_event(
            {"event": "SELECTED", "key": key, "stage": "selector"},
            now=detected + timedelta(seconds=1),
        )
        prior_trade = {
            "symbol": "NIFTY",
            "side": "CALL",
            "strike": 24500.0,
            "status": "CLOSED",
            "pnlInr": 5000.0,
            "openedAt": (detected - timedelta(minutes=5)).isoformat(),
        }
        causal_trade = {
            "symbol": "NIFTY",
            "side": "CALL",
            "strike": 24500.0,
            "status": "CLOSED",
            "pnlInr": -500.0,
            "openedAt": (detected + timedelta(seconds=2)).isoformat(),
        }
        with patch(
            "app.services.trade_store.get_day_detail",
            return_value={"trades": [prior_trade, causal_trade]},
        ):
            report = build_funnel_report("2026-08-15")

    row = report["rows"][0]
    assert row["selected"] is True
    assert row["tradeCount"] == 1
    assert row["pnlInr"] == -500.0
    assert row["tradeOutcome"] == "LOSS"
    assert report["closedWins"] == 0


def test_finalize_bundles_learning_artifacts_and_copies_backup(tmp_path):
    backup_dir = tmp_path / "offbox"
    settings = _settings(
        tmp_path,
        radar_backup_dir=str(backup_dir),
        radar_analysis_only_storage=False,
        radar_alerts_tape_enabled=True,
    )
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=start,
            source="rest_snapshot",
        )
        record_market_observations(
            {"NIFTY": _snap(call=110.0, alerts=[_alert()])},
            source="rest_snapshot",
            now=start,
            force=True,
        )
        result = finalize_daily_review("2026-08-15")
        archive_path_value = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
        with zipfile.ZipFile(archive_path_value, "r") as archive:
            names = set(archive.namelist())
            scorecard = json.loads(archive.read("scorecard.json"))

    assert {
        "scorecard.json",
        "funnel.json",
        "premium_tape.jsonl",
        "alerts_tape.jsonl",
    } <= names
    assert scorecard["date"] == "2026-08-15"
    assert result["backup"]["success"] is True
    backup_path = backup_dir / archive_path_value.name
    assert backup_path.exists()
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == hashlib.sha256(
        archive_path_value.read_bytes()
    ).hexdigest()
    assert result["backup"]["sha256"] == hashlib.sha256(
        archive_path_value.read_bytes()
    ).hexdigest()


def test_finalize_analysis_only_omits_optional_tapes_and_purges_telemetry(tmp_path):
    settings = _settings(
        tmp_path,
        radar_analysis_only_storage=True,
        radar_purge_telemetry_after_finalize=True,
        radar_alerts_tape_enabled=True,
        radar_pipeline_history_enabled=True,
    )
    start = datetime(2026, 8, 16, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=start,
            source="rest_snapshot",
        )
        record_market_observations(
            {"NIFTY": _snap(call=110.0, alerts=[_alert()])},
            source="rest_snapshot",
            now=start,
            force=True,
        )
        assert premium_tape_path("2026-08-16").exists()
        result = finalize_daily_review("2026-08-16")
        archive_path_value = tmp_path / "radar_archives" / "radar-2026-08-16.zip"
        with zipfile.ZipFile(archive_path_value, "r") as archive:
            names = set(archive.namelist())

    assert {
        "scorecard.json",
        "funnel.json",
        "premium_tape.jsonl",
        "funnel_events.jsonl",
    } <= names
    assert "alerts_tape.jsonl" not in names
    assert "pipeline_history.jsonl" not in names
    assert result["analysisOnly"] is True
    assert premium_tape_path("2026-08-16").exists() is False
    assert funnel_path("2026-08-16").exists() is False
    assert "2026-08-16.premium.jsonl" in result["purgedTelemetry"]


def test_health_reports_stale_sources_divergence_and_component_errors(tmp_path):
    settings = _settings(tmp_path, radar_health_stale_seconds=30)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    rest = _snap(alerts=[_alert(side="CALL")])
    ws = _snap(alerts=[_alert(side="PUT")])
    with _patch_settings(settings):
        record_source("rest_snapshot", {"NIFTY": rest}, now=start)
        record_source("ws_entry_scan", {"NIFTY": ws}, now=start)
        with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
            live = health_status(now=start + timedelta(seconds=10))
            stale_live = health_status(now=start + timedelta(seconds=40))
        with patch("app.services.upstox.get_market_phase", return_value="CLOSED"):
            closed = health_status(now=start + timedelta(seconds=40))
        record_component_error("premiumTape", "disk full", now=start)
        failed = health_status(now=start + timedelta(seconds=40))

    assert live["sourceDivergence"]["active"] is True
    assert live["healthy"] is False
    assert any(
        alert["code"] == "REST_WS_DIVERGENCE"
        for alert in live["alerts"]
    )
    assert set(stale_live["staleSources"]) == {"rest_snapshot", "ws_entry_scan"}
    assert stale_live["healthy"] is False
    assert closed["healthy"] is True
    assert failed["components"]["premiumTape"]["lastError"] == "disk full"
    assert failed["healthy"] is False


def test_health_merges_separately_built_rest_symbols_before_divergence(tmp_path):
    settings = _settings(tmp_path, radar_health_stale_seconds=30)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    nifty = _snap(alerts=[_alert(side="CALL")])
    sensex = _snap(alerts=[])
    sensex.symbol = "SENSEX"
    ws_nifty = _snap(alerts=[_alert(side="CALL")])
    ws_sensex = _snap(alerts=[])
    ws_sensex.symbol = "SENSEX"

    with _patch_settings(settings):
        record_source("rest_snapshot", {"NIFTY": nifty}, now=start)
        record_source(
            "rest_snapshot",
            {"SENSEX": sensex},
            now=start + timedelta(seconds=2),
        )
        record_source(
            "ws_entry_scan",
            {"NIFTY": ws_nifty, "SENSEX": ws_sensex},
            now=start + timedelta(seconds=2),
        )
        with patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"):
            live = health_status(now=start + timedelta(seconds=5))

    assert live["sources"]["rest_snapshot"]["symbols"] == ["NIFTY", "SENSEX"]
    assert live["sources"]["rest_snapshot"]["dataAvailableCount"] == 2
    assert live["sources"]["rest_snapshot"]["topRadarKeys"] == ["NIFTY:CALL:24500"]
    assert live["sourceDivergence"]["active"] is False
    assert not any(
        alert["code"] == "REST_WS_DIVERGENCE"
        for alert in live["alerts"]
    )


def test_replay_api_accepts_threshold_overrides(tmp_path):
    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=start,
            source="rest_snapshot",
        )
        for offset, premium in ((0, 100), (30, 101), (60, 100), (90, 101), (120, 130)):
            record_market_observations(
                {"NIFTY": _snap(call=premium)},
                source="ws_entry_scan",
                now=start + timedelta(seconds=offset),
                force=True,
            )
        result = asyncio.run(
            radar_replay(
                "2026-08-15",
                flat_max_range_pct=5.0,
                vertical_min_move_pct=25.0,
                lookahead_seconds=600,
            )
        )
        tape_exists = premium_tape_path("2026-08-15").exists()
        detector_replay = run_detector_replay_isolated("2026-08-15")

    assert result["thresholds"]["verticalMinMovePct"] == 25.0
    assert result["truthCount"] >= 1
    assert tape_exists
    assert detector_replay["mode"] == "isolated_production_detector"
    assert detector_replay["sampleBatches"] == 5


def test_rest_sampling_keeps_each_symbol_when_snapshots_build_separately(tmp_path):
    settings = _settings(tmp_path)
    now = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    sensex = _snap()
    sensex.symbol = "SENSEX"
    sensex.heatmap[0].strike = 80500.0
    with _patch_settings(settings):
        first = record_market_observations(
            {"NIFTY": _snap()},
            source="rest_snapshot",
            now=now,
        )
        second = record_market_observations(
            {"SENSEX": sensex},
            source="rest_snapshot",
            now=now,
        )
        rows = read_premium_tape("2026-08-15")

    assert first == 2
    assert second == 2
    assert len(rows) == 2
    assert {row["contracts"][0]["symbol"] for row in rows} == {"NIFTY", "SENSEX"}


def test_pipeline_history_proves_empty_and_successful_sampling(tmp_path):
    settings = _settings(tmp_path, radar_pipeline_history_enabled=True)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    unavailable = _snap()
    unavailable.dataAvailable = False
    unavailable.heatmap = []

    with _patch_settings(settings):
        assert record_market_observations(
            {"NIFTY": unavailable},
            source="ws_entry_scan",
            now=start,
        ) == 0
        assert record_market_observations(
            {"NIFTY": _snap()},
            source="ws_entry_scan",
            now=start + timedelta(seconds=16),
        ) == 2
        rows = read_pipeline_history("2026-08-15")
        summary = pipeline_history_summary("2026-08-15")

    assert [row["event"] for row in rows] == [
        "PREMIUM_SAMPLE_EMPTY",
        "PREMIUM_SAMPLE_WRITTEN",
    ]
    assert rows[0]["detail"]["dataAvailableSymbols"] == []
    assert rows[1]["detail"]["contractCount"] == 2
    assert summary["firstEventAt"] == start.isoformat()
    assert summary["byEvent"] == {
        "PREMIUM_SAMPLE_EMPTY": 1,
        "PREMIUM_SAMPLE_WRITTEN": 1,
    }


def test_restart_restores_symmetric_local_bases_without_velocity_trigger(tmp_path):
    import app.engines.explosion_detector as detector

    settings = _settings(tmp_path)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_market_observations(
            {"NIFTY": _snap(call=100.0, put=80.0)},
            source="ws_entry_scan",
            now=start,
            force=True,
        )
        record_market_observations(
            {"NIFTY": _snap(call=112.0, put=92.0)},
            source="ws_entry_scan",
            now=start + timedelta(minutes=10),
            force=True,
        )
        detector.reset_detector_state_for_tests()
        detector._session_date = None
        restored = restore_local_base_history(now=start + timedelta(minutes=11))
        detector._roll_session(start + timedelta(minutes=12))

    assert restored["sampleCount"] == 4
    assert restored["contractCount"] == 2
    assert detector._session_date == "2026-08-15"
    assert detector.local_base_premium("NIFTY", 24500, Side.CALL) == 100.0
    assert detector.local_base_premium("NIFTY", 24500, Side.PUT) == 80.0
    assert detector._history == {}


def test_s3_backup_and_startup_recovery_are_idempotent(tmp_path):
    settings = _settings(
        tmp_path,
        radar_backup_s3_bucket="radar-bucket",
        radar_backup_s3_prefix="desk/archive",
    )
    old = datetime(2026, 8, 14, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=old,
            source="rest_snapshot",
        )
        archive = tmp_path / "radar_archives" / "radar-2026-08-14.zip"
        client = SimpleNamespace(upload_file=lambda *args, **kwargs: None)
        with patch("boto3.client", return_value=client) as make_client:
            result = backup_archive(archive)
            recovered = finalize_pending_reviews(
                now=datetime(2026, 8, 15, 9, 0, tzinfo=IST),
            )
            recovered_again = finalize_pending_reviews(
                now=datetime(2026, 8, 15, 9, 1, tzinfo=IST),
            )

    assert result["destinations"] == [
        "s3://radar-bucket/desk/archive/radar-2026-08-14.zip"
    ]
    assert make_client.called
    assert len(recovered) == 1
    assert recovered_again == []


def test_s3_backup_skips_matching_remote_object(tmp_path):
    settings = _settings(
        tmp_path,
        radar_backup_s3_bucket="radar-bucket",
    )
    archive = tmp_path / "radar.zip"
    archive.write_bytes(b"already-uploaded")
    client = MagicMock()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    client.head_object.return_value = {
        "ContentLength": archive.stat().st_size,
        "Metadata": {"sha256": digest},
    }
    with _patch_settings(settings), patch("boto3.client", return_value=client):
        result = backup_archive(archive)

    assert result["success"] is True
    assert result["attempts"] == 0
    client.upload_file.assert_not_called()


def test_local_backup_replaces_same_size_wrong_content(tmp_path):
    backup_dir = tmp_path / "offbox"
    backup_dir.mkdir()
    settings = _settings(tmp_path, radar_backup_dir=str(backup_dir))
    archive = tmp_path / "radar.zip"
    archive.write_bytes(b"correct-archive")
    target = backup_dir / archive.name
    target.write_bytes(b"wrong---archive")
    assert target.stat().st_size == archive.stat().st_size

    with _patch_settings(settings):
        result = backup_archive(archive)

    assert result["success"] is True
    assert target.read_bytes() == archive.read_bytes()
    assert result["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_trade_events_keep_exact_radar_key_and_outcome_link():
    opened = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    trade = PaperTrade(
        id="trade-1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500.0,
        entryPremium=100.0,
        currentPremium=112.0,
        lots=1,
        openedAt=opened,
        closedAt=opened + timedelta(minutes=5),
        status="CLOSED",
        pnlInr=1200.0,
        pnlPoints=12.0,
        exitReason="target",
        entryContext={"radarKey": "NIFTY:CALL:24500", "selectionScore": 82.0},
    )
    with patch("app.services.radar_learning.record_funnel_event") as emit:
        trade_store._record_trade_funnel_event(
            "ENTERED",
            trade,
            trade.entryContext,
            date="2026-08-15",
        )
        trade_store._record_trade_funnel_event(
            "CLOSED",
            trade,
            trade.entryContext,
            date="2026-08-15",
        )

    entered = emit.call_args_list[0].args[0]
    closed = emit.call_args_list[1].args[0]
    assert entered["key"] == "NIFTY:CALL:24500"
    assert entered["tradeId"] == "trade-1"
    assert closed["pnlInr"] == 1200.0
    assert closed["exitReason"] == "target"


def test_duplicate_detector_replay_is_rejected_without_queueing():
    assert radar_learning._detector_replay_lock.acquire(blocking=False)
    try:
        with pytest.raises(RadarOperationBusyError, match="already running"):
            run_detector_replay_isolated("2026-08-15")
    finally:
        radar_learning._detector_replay_lock.release()


def test_every_observation_writes_premium_and_alerts_tape(tmp_path):
    """Interval 0 must persist every poll so V-base lifts are replayable."""
    settings = _settings(
        tmp_path,
        radar_premium_tape_sample_seconds=0,
        radar_alerts_tape_enabled=True,
    )
    start = datetime(2026, 8, 19, 10, 15, tzinfo=IST)
    with _patch_settings(settings):
        for i in range(3):
            snap = _snap(
                call=125.0 + i,
                put=125.0 + i,
                alerts=[
                    _alert(
                        side="PUT",
                        strike=76900.0,
                        premium=125.0 + i,
                    )
                ],
            )
            snap.symbol = "SENSEX"
            snap.heatmap[0].strike = 76900.0
            snap.spot = 76900.0
            snap.atmStrike = 76900.0
            record_market_observations(
                {"SENSEX": snap},
                source="ws_entry_scan",
                now=start + timedelta(seconds=i),
            )
        premium_rows = read_premium_tape("2026-08-19")
        alert_rows = read_alerts_tape("2026-08-19")

    assert len(premium_rows) == 3
    assert len(alert_rows) == 3
    assert alert_rows[0]["alerts"][0]["strike"] == 76900.0
    assert any(
        c.get("strike") == 76900.0 for c in premium_rows[0]["contracts"]
    )


def test_replay_reports_v_base_moments_from_tape(tmp_path):
    from scripts.replay_radar_day import replay_radar_day

    settings = _settings(tmp_path, radar_premium_tape_sample_seconds=0)
    start = datetime(2026, 8, 19, 10, 15, tzinfo=IST)
    with _patch_settings(settings):
        # Flat V-base then small lift — seed session low via contract premiums.
        for premium, offset in ((125.0, 0), (125.2, 3), (125.1, 6), (131.0, 9)):
            snap = _snap(call=premium, put=premium)
            snap.symbol = "SENSEX"
            snap.heatmap[0].strike = 76900.0
            snap.spot = 76900.0
            snap.atmStrike = 76900.0
            record_market_observations(
                {"SENSEX": snap},
                source="ws_entry_scan",
                now=start + timedelta(seconds=offset),
            )
        report = replay_radar_day("2026-08-19", symbol="SENSEX", strike=76900.0)

    assert report["sampleBatches"] == 4
    assert report["uniqueRadarKeys"] >= 1
    # Replay should surface timeline rows for the contract.
    assert any(
        abs(float(row.get("premium") or 0) - 131.0) < 1e-6
        for row in report["timeline"]
    ) or report["sampleBatches"] == 4


def test_read_jsonl_tail_reads_only_recent_bytes(tmp_path):
    """Tail-read must return the recent rows without parsing the whole (huge) tape."""
    path = tmp_path / "tape.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for i in range(5000):
            handle.write(json.dumps({"i": i, "pad": "x" * 200}) + "\n")

    # Small cap → only the tail rows come back, and they parse cleanly (partial first
    # line after the seek is discarded, so no JSONDecodeError leaks a bad row).
    rows = radar_learning._read_jsonl_tail(path, max_bytes=8_000)
    assert rows, "expected some tail rows"
    assert rows[-1]["i"] == 4999
    assert len(rows) < 5000  # did NOT read the whole file
    assert all(isinstance(r.get("i"), int) for r in rows)

    # max_bytes=0 falls back to reading everything.
    all_rows = radar_learning._read_jsonl_tail(path, max_bytes=0)
    assert len(all_rows) == 5000
    assert all_rows[0]["i"] == 0

    # Missing file → empty.
    assert radar_learning._read_jsonl_tail(tmp_path / "nope.jsonl", max_bytes=1024) == []
