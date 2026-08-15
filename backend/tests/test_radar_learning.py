"""Outcome labels, hindsight recall, funnel analytics, health, replay, and backups."""

from __future__ import annotations

import asyncio
import json
import zipfile
from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.routers.ai import radar_replay
from app.services.radar_archive import read_archive_entries, record_top_radars
from app.services.radar_health import (
    health_status,
    record_component_error,
    record_source,
    reset_health_for_tests,
)
from app.services.radar_learning import (
    analyze_hindsight,
    build_funnel_report,
    finalize_daily_review,
    premium_tape_path,
    read_premium_tape,
    record_funnel_state,
    record_market_observations,
    reset_learning_state_for_tests,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(tmp_path, **overrides):
    values = {
        "trade_store_dir": str(tmp_path),
        "radar_archive_enabled": True,
        "radar_archive_dir": "",
        "radar_archive_top_n_per_day": 100,
        "radar_archive_retention_days": 365,
        "radar_learning_enabled": True,
        "radar_premium_tape_sample_seconds": 15,
        "radar_outcome_horizons_seconds_csv": "60,300",
        "radar_outcome_target_pct": 20.0,
        "radar_outcome_stop_pct": 10.0,
        "radar_hindsight_flat_window_seconds": 120,
        "radar_hindsight_flat_max_range_pct": 8.0,
        "radar_hindsight_vertical_min_move_pct": 40.0,
        "radar_hindsight_lookahead_seconds": 1800,
        "radar_funnel_dedupe_seconds": 60,
        "radar_health_stale_seconds": 45,
        "radar_backup_dir": "",
        "radar_backup_s3_bucket": "",
        "radar_backup_s3_prefix": "nexusquant/radar",
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
        with patch(
            "app.services.trade_store.get_day_detail",
            return_value={
                "trades": [{
                    "symbol": "NIFTY",
                    "side": "CALL",
                    "strike": 24500.0,
                    "status": "CLOSED",
                    "pnlInr": 1250.0,
                }]
            },
        ):
            report = build_funnel_report("2026-08-15")

    assert report["detected"] == 1
    assert report["blocked"] == 1
    assert report["entered"] == 1
    assert report["closedWins"] == 1
    assert report["rows"][0]["blockers"] == ["chart_alignment"]


def test_finalize_bundles_learning_artifacts_and_copies_backup(tmp_path):
    backup_dir = tmp_path / "offbox"
    settings = _settings(tmp_path, radar_backup_dir=str(backup_dir))
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with _patch_settings(settings):
        record_top_radars(
            {"NIFTY": _snap(alerts=[_alert()])},
            now=start,
            source="rest_snapshot",
        )
        record_market_observations(
            {"NIFTY": _snap(call=110.0)},
            source="rest_snapshot",
            now=start,
            force=True,
        )
        result = finalize_daily_review("2026-08-15")
        archive_path_value = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
        with zipfile.ZipFile(archive_path_value, "r") as archive:
            names = set(archive.namelist())
            scorecard = json.loads(archive.read("scorecard.json"))

    assert {"scorecard.json", "funnel.json", "premium_tape.jsonl"} <= names
    assert scorecard["date"] == "2026-08-15"
    assert result["backup"]["success"] is True
    assert (backup_dir / archive_path_value.name).exists()


def test_health_reports_stale_sources_divergence_and_component_errors(tmp_path):
    settings = _settings(tmp_path, radar_health_stale_seconds=30)
    start = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    rest = _snap(alerts=[_alert(side="CALL")])
    ws = _snap(alerts=[_alert(side="PUT")])
    with _patch_settings(settings):
        record_source("rest_snapshot", {"NIFTY": rest}, now=start)
        record_source("ws_entry_scan", {"NIFTY": ws}, now=start)
        live = health_status(now=start + timedelta(seconds=10))
        record_component_error("premiumTape", "disk full", now=start)
        failed = health_status(now=start + timedelta(seconds=40))

    assert live["sourceDivergence"]["active"] is True
    assert live["healthy"] is True
    assert set(failed["staleSources"]) == {"rest_snapshot", "ws_entry_scan"}
    assert failed["components"]["premiumTape"]["lastError"] == "disk full"
    assert failed["healthy"] is False


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

    assert result["thresholds"]["verticalMinMovePct"] == 25.0
    assert result["truthCount"] >= 1
    assert tape_exists
