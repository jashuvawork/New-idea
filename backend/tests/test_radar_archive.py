"""Daily ZIP persistence for top radar observations."""

from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.responses import FileResponse

from app.routers.ai import download_radar_archive
from app.services.radar_archive import (
    RadarArchiveCorruptError,
    list_archives,
    read_archive_entries,
    record_top_radars,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(tmp_path, **overrides):
    values = {
        "trade_store_dir": str(tmp_path),
        "radar_archive_enabled": True,
        "radar_archive_dir": "",
        "radar_archive_top_n_per_day": 100,
        "radar_archive_retention_days": 365,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _alert(
    *,
    strike: float,
    score: float,
    tier: str = "BUILDING",
    side: str = "CALL",
    **extra,
):
    return {
        "symbol": "NIFTY",
        "side": side,
        "strike": strike,
        "premium": 100.0,
        "tier": tier,
        "explosionScore": score,
        "dailyMovePct": 18.0,
        "peakMovePct": 20.0,
        "velocity3s": 2.0,
        **extra,
    }


def test_data_purge_every_interval_days(tmp_path):
    """Seed the timer on first run, then wipe every file once the interval elapses."""
    from datetime import timedelta

    import app.services.radar_archive as ra

    settings = _settings(
        tmp_path,
        radar_data_purge_enabled=True,
        radar_data_purge_interval_days=6,
    )
    with patch.object(ra, "get_settings", return_value=settings):
        arch = ra.get_archive_dir()
        telemetry = arch / "telemetry"
        telemetry.mkdir(parents=True, exist_ok=True)
        (arch / "radar-2026-08-18.zip").write_bytes(b"zipdata")
        (telemetry / "2026-08-18.premium.jsonl").write_text("x" * 1000)
        (telemetry / "2026-08-18.funnel.jsonl").write_text("y" * 500)

        day0 = datetime(2026, 8, 24, 6, 0, tzinfo=IST)
        # First run seeds the timer — nothing deleted yet.
        assert ra.data_purge_due(day0) is False
        assert (arch / "radar-2026-08-18.zip").exists()

        # Not yet due at day 5.
        assert ra.data_purge_due(day0 + timedelta(days=5)) is False

        # Due at day 6 → purge removes every data file, keeps the state file.
        due_day = day0 + timedelta(days=6)
        assert ra.data_purge_due(due_day) is True
        res = ra.purge_all_radar_data(due_day)
        assert res["removed"] == 3
        assert res["freedBytes"] >= 1500
        assert not (arch / "radar-2026-08-18.zip").exists()
        assert not (telemetry / "2026-08-18.premium.jsonl").exists()
        assert ra._data_purge_state_path().exists()

        # Timer reset after the purge — not due again the same day.
        assert ra.data_purge_due(due_day) is False


def test_data_purge_disabled_never_due(tmp_path):
    import app.services.radar_archive as ra

    settings = _settings(tmp_path, radar_data_purge_enabled=False)
    with patch.object(ra, "get_settings", return_value=settings):
        assert ra.data_purge_due(datetime(2026, 8, 24, 6, 0, tzinfo=IST)) is False


def _snap(alerts):
    return SimpleNamespace(
        dataAvailable=True,
        timestamp=datetime(2026, 8, 15, 10, 0, tzinfo=IST),
        marketPhase="LIVE_MARKET",
        spot=24500.0,
        atmStrike=24500.0,
        optionExpiry="2026-08-20",
        tradeQualityScore=72.0,
        regime="TREND_EXPANSION",
        breadth={"bias": "BULLISH"},
        spotChart={"direction": "BULLISH"},
        pcr=1.1,
        maxPain=24500.0,
        indiaVix=13.4,
        explosionAlerts=alerts,
    )


def _read_rows(path):
    with zipfile.ZipFile(path, "r") as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "top_radars.json",
            "all_radars.json",
            "README.txt",
        }
        manifest = json.loads(archive.read("manifest.json"))
        rows = json.loads(archive.read("top_radars.json"))
    return manifest, rows


def test_archives_best_unique_radars_and_improvement_milestones(tmp_path):
    settings = _settings(tmp_path)
    now = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    first_lift = _alert(
        strike=24450.0,
        score=35.0,
        tier="WATCH",
        side="PUT",
        tradeable=True,
        ictFirstLift=True,
        localBaseMovePct=15.0,
    )
    ignored = _alert(strike=24300.0, score=90.0, tier="WATCH")

    with patch("app.services.radar_archive.get_settings", return_value=settings):
        count = record_top_radars(
            {"NIFTY": _snap([_alert(strike=24500.0, score=45.0), first_lift, ignored])},
            now=now,
            source="rest_snapshot",
        )
        assert count == 2

        improved = _alert(
            strike=24500.0,
            score=70.0,
            tier="ELITE",
            tradeable=True,
            premium=128.0,
        )
        assert record_top_radars(
            {"NIFTY": _snap([improved])},
            now=now.replace(hour=11),
            source="ws_entry_scan",
        ) == 2

        archive = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
        manifest, rows = _read_rows(archive)

    assert manifest["count"] == 2
    assert rows[0]["tier"] == "ELITE"
    assert rows[0]["alert"]["explosionScore"] == 70.0
    assert len(rows[0]["milestones"]) == 2
    assert rows[0]["context"]["archiveSource"] == "ws_entry_scan"
    assert rows[0]["context"]["volumeReliable"] is False
    assert rows[0]["milestones"][0]["source"] == "rest_snapshot"
    assert rows[0]["milestones"][1]["source"] == "ws_entry_scan"
    assert any(row["alert"].get("ictFirstLift") for row in rows)


def test_lower_rank_tradeable_moment_is_kept_as_causal_milestone(tmp_path):
    settings = _settings(tmp_path)
    now = datetime(2026, 8, 17, 15, 0, tzinfo=IST)
    prior_peak = _alert(
        strike=24350.0,
        score=90.0,
        tier="ELITE",
        side="PUT",
        tradeable=False,
    )
    causal_launch = _alert(
        strike=24350.0,
        score=50.0,
        tier="BUILDING",
        side="PUT",
        tradeable=True,
        ictEliteBaseReady=True,
        ictArmedBaseLaunch=True,
        ictArmedBaseSustainedLift=True,
    )

    with patch("app.services.radar_archive.get_settings", return_value=settings):
        record_top_radars({"NIFTY": _snap([prior_peak])}, now=now)
        record_top_radars(
            {"NIFTY": _snap([causal_launch])},
            now=now.replace(minute=15),
        )
        row = read_archive_entries("2026-08-17")[0]

    assert row["tier"] == "ELITE"
    assert row["alert"]["explosionScore"] == 90.0
    assert len(row["milestones"]) == 2
    assert row["milestones"][-1]["tradeable"] is True
    assert row["milestones"][-1]["ictEliteBaseReady"] is True
    assert row["milestones"][-1]["ictArmedBaseLaunch"] is True


def test_top_n_and_retention_are_enforced(tmp_path):
    settings = _settings(
        tmp_path,
        radar_archive_top_n_per_day=2,
        radar_archive_retention_days=5,
    )
    old = datetime(2026, 8, 1, 10, 0, tzinfo=IST)
    current = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    alerts = [
        _alert(strike=24400.0, score=30.0),
        _alert(strike=24450.0, score=50.0),
        _alert(strike=24500.0, score=70.0, tier="ELITE"),
    ]

    with patch("app.services.radar_archive.get_settings", return_value=settings):
        record_top_radars({"NIFTY": _snap(alerts[:1])}, now=old)
        count = record_top_radars({"NIFTY": _snap(alerts)}, now=current)
        archives = list_archives()
        retained_rows = read_archive_entries("2026-08-15")

    assert count == 2
    assert [row["date"] for row in archives] == ["2026-08-15"]
    path = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
    manifest, rows = _read_rows(path)
    assert [row["strike"] for row in rows] == [24500.0, 24450.0]
    with zipfile.ZipFile(path, "r") as archive:
        all_rows = json.loads(archive.read("all_radars.json"))
    assert manifest["totalDetectedCount"] == 3
    assert len(all_rows) == 3
    assert len(retained_rows) == 3


def test_archive_can_be_listed_and_downloaded(tmp_path):
    settings = _settings(tmp_path)
    now = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with patch("app.services.radar_archive.get_settings", return_value=settings):
        record_top_radars(
            {"NIFTY": _snap([_alert(strike=24500.0, score=60.0)])},
            now=now,
        )
        listing = list_archives()
        response = asyncio.run(download_radar_archive("2026-08-15"))

    assert listing[0]["count"] == 1
    assert listing[0]["downloadUrl"] == "/api/ai/radar-archives/2026-08-15"
    assert isinstance(response, FileResponse)
    assert response.media_type == "application/zip"


def test_disabled_archive_does_not_create_storage(tmp_path):
    settings = _settings(tmp_path, radar_archive_enabled=False)
    with patch("app.services.radar_archive.get_settings", return_value=settings):
        assert record_top_radars(
            {"NIFTY": _snap([_alert(strike=24500.0, score=60.0)])},
        ) == 0

    assert not (tmp_path / "radar_archives").exists()


def test_no_qualifying_alert_does_not_create_empty_archive(tmp_path):
    settings = _settings(tmp_path)
    watch = _alert(strike=24500.0, score=20.0, tier="WATCH")
    with patch("app.services.radar_archive.get_settings", return_value=settings):
        assert record_top_radars(
            {"NIFTY": _snap([watch])},
            now=datetime(2026, 8, 15, 10, 0, tzinfo=IST),
        ) == 0

    assert not (tmp_path / "radar_archives" / "radar-2026-08-15.zip").exists()


def test_armed_watch_state_alone_does_not_expand_full_archive(tmp_path):
    settings = _settings(tmp_path)
    armed_only = _alert(
        strike=24500.0,
        score=20.0,
        tier="WATCH",
        ictBaseArmed=True,
        ictArmedBaseLaunch=False,
        ictBreakout=False,
        tradeable=False,
    )
    launch = _alert(
        strike=24450.0,
        score=48.0,
        tier="WATCH",
        side="PUT",
        ictBaseArmed=True,
        ictArmedBaseLaunch=True,
        ictBreakout=True,
        tradeable=True,
    )
    with patch("app.services.radar_archive.get_settings", return_value=settings):
        assert record_top_radars(
            {"NIFTY": _snap([armed_only, launch])},
            now=datetime(2026, 8, 15, 10, 0, tzinfo=IST),
        ) == 1

    archive = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
    manifest, top_rows = _read_rows(archive)
    with zipfile.ZipFile(archive, "r") as zipped:
        all_rows = json.loads(zipped.read("all_radars.json"))
    assert manifest["totalDetectedCount"] == 1
    assert len(top_rows) == len(all_rows) == 1
    assert all_rows[0]["alert"]["ictArmedBaseLaunch"] is True


def test_corrupt_archive_is_never_silently_overwritten(tmp_path):
    settings = _settings(tmp_path)
    archive = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
    archive.parent.mkdir(parents=True)
    original = b"not-a-zip-but-valuable-for-recovery"
    archive.write_bytes(original)

    with patch("app.services.radar_archive.get_settings", return_value=settings):
        with pytest.raises(RadarArchiveCorruptError):
            record_top_radars(
                {"NIFTY": _snap([_alert(strike=24500.0, score=60.0)])},
                now=datetime(2026, 8, 15, 10, 0, tzinfo=IST),
            )
        archives = list_archives()

    assert archive.read_bytes() == original
    assert archives[0]["corrupt"] is True
