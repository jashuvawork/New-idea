"""Local-base audit week — 5-layer daily proof scoring."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.local_base_week_audit import (
    build_local_base_audit,
    build_local_base_audit_week,
)
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


def _settings(tmp_path, **overrides):
    values = {
        "trade_store_dir": str(tmp_path),
        "radar_archive_enabled": True,
        "radar_archive_dir": "",
        "radar_learning_enabled": True,
        "local_base_audit_week_enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_audit_week_overrides_lower_floors():
    from app.config import Settings, _with_audit_week_overrides

    base = Settings(local_base_audit_week_enabled=False)
    audit = _with_audit_week_overrides(
        Settings(local_base_audit_week_enabled=True)
    )
    assert audit.ftv_s_strict_min_local_base_move_pct < base.ftv_s_strict_min_local_base_move_pct
    assert audit.explosion_local_base_entry_min_move_pct < base.explosion_local_base_entry_min_move_pct
    assert audit.building_ltp_monitor_min_ms <= base.building_ltp_monitor_min_ms


def test_local_base_audit_scores_layers(tmp_path):
    date = "2026-08-19"
    settings = _settings(tmp_path)

    scorecard = {
        "truthCount": 4,
        "earlyRecallPct": 75.0,
        "recallPct": 100.0,
        "events": [
            {"key": "SENSEX:PUT:76900", "capture": "EARLY", "leadSeconds": 45.0, "peakMovePct": 106.0},
            {"key": "NIFTY:CALL:24500", "capture": "EARLY", "leadSeconds": 30.0, "peakMovePct": 80.0},
            {"key": "NIFTY:PUT:24400", "capture": "LATE", "leadSeconds": -5.0, "peakMovePct": 50.0},
            {"key": "SENSEX:CALL:77000", "capture": "MISSED", "peakMovePct": 90.0},
        ],
    }
    funnel = {
        "detected": 3,
        "selected": 2,
        "entered": 1,
        "detectionToEntryPct": 33.3,
        "entryWinRatePct": 100.0,
    }
    archives = [
        {
            "key": "SENSEX:PUT:76900",
            "outcome": {"mfePct": 100.0},
        }
    ]
    trade = {
        "id": "t1",
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 76900,
        "status": "CLOSED",
        "entryPremium": 95.0,
        "exitPremium": 140.0,
        "pnlInr": 2250.0,
        "entryContext": {
            "explosionTier": "BUILDING",
            "momentType": "first_lift_local_base",
            "localBaseBaseRelPct": 12.5,
            "indexConfirmedFtv": True,
            "ftvAuthorizationMode": "BUILDING_RIP_FTV",
            "radarKey": "SENSEX:PUT:76900",
        },
    }
    day_file = tmp_path / f"{date}.json"
    day_file.write_text(
        __import__("json").dumps(
            {"date": date, "trades": [trade], "events": [], "summary": {}}
        ),
        encoding="utf-8",
    )

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.local_base_week_audit.get_settings", return_value=settings),
        patch(
            "app.services.radar_learning.analyze_hindsight",
            return_value=scorecard,
        ),
        patch(
            "app.services.radar_learning.build_funnel_report",
            return_value=funnel,
        ),
        patch(
            "app.services.radar_archive.read_archive_entries",
            return_value=archives,
        ),
        patch.object(trade_store, "get_store_dir", return_value=tmp_path),
    ):
        report = build_local_base_audit(date)

    assert report["auditWeekEnabled"] is True
    assert report["layers"]["detectionLead"]["earlyRecallPct"] == 75.0
    assert report["layers"]["entryPad"]["earlyPadPct"] == 100.0
    assert report["layers"]["causality"]["causalityPct"] == 100.0
    assert report["layers"]["tierTiming"]["earlyTierPct"] == 100.0
    assert report["overall"]["verdict"] in {"AHEAD", "ON_TRACK"}
    assert len(report["checklist"]) == 6
    assert any(item["status"] == "PASS" for item in report["checklist"])


def test_local_base_audit_week_rollup(tmp_path):
    date = "2026-08-18"
    settings = _settings(tmp_path)
    empty_scorecard = {
        "truthCount": 0,
        "earlyRecallPct": 0.0,
        "recallPct": 0.0,
        "events": [],
    }
    empty_funnel = {
        "detected": 0,
        "selected": 0,
        "entered": 0,
        "detectionToEntryPct": 0.0,
        "entryWinRatePct": 0.0,
    }

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.local_base_week_audit.get_settings", return_value=settings),
        patch(
            "app.services.radar_learning.analyze_hindsight",
            return_value=empty_scorecard,
        ),
        patch(
            "app.services.radar_learning.build_funnel_report",
            return_value=empty_funnel,
        ),
        patch(
            "app.services.radar_archive.read_archive_entries",
            return_value=[],
        ),
        patch.object(trade_store, "get_store_dir", return_value=tmp_path),
    ):
        week = build_local_base_audit_week(date, days=2)

    assert week["startDate"] == date
    assert len(week["daily"]) == 2
    assert "summary" in week
