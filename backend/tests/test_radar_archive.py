"""Daily ZIP persistence for top radar observations."""

from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.responses import FileResponse

from app.routers.ai import download_radar_archive
from app.services.radar_archive import list_archives, record_top_radars

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
        ) == 2

        archive = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
        manifest, rows = _read_rows(archive)

    assert manifest["count"] == 2
    assert rows[0]["tier"] == "ELITE"
    assert rows[0]["alert"]["explosionScore"] == 70.0
    assert len(rows[0]["milestones"]) == 2
    assert any(row["alert"].get("ictFirstLift") for row in rows)


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

    assert count == 2
    assert [row["date"] for row in archives] == ["2026-08-15"]
    _, rows = _read_rows(tmp_path / "radar_archives" / "radar-2026-08-15.zip")
    assert [row["strike"] for row in rows] == [24500.0, 24450.0]


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
