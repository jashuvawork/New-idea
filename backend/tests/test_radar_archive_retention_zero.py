"""EOD ZIP retention: 0 means keep every finalized daily archive."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.radar_archive import record_top_radars

IST = ZoneInfo("Asia/Kolkata")


def _settings(tmp_path, **overrides):
    from types import SimpleNamespace

    values = {
        "trade_store_dir": str(tmp_path),
        "radar_archive_enabled": True,
        "radar_archive_dir": "",
        "radar_archive_top_n_per_day": 100,
        "radar_archive_retention_days": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _alert(strike: float = 24500.0):
    return {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": strike,
        "premium": 100.0,
        "tier": "BUILDING",
        "explosionScore": 60.0,
        "dailyMovePct": 18.0,
        "peakMovePct": 20.0,
        "velocity3s": 2.0,
    }


def _snap(alerts):
    from types import SimpleNamespace

    return SimpleNamespace(
        dataAvailable=True,
        timestamp=datetime(2026, 8, 1, 10, 0, tzinfo=IST),
        marketPhase="LIVE_MARKET",
        spot=24500.0,
        atmStrike=24500.0,
        optionExpiry="2026-08-07",
        tradeQualityScore=72.0,
        regime="TREND_EXPANSION",
        breadth={"bias": "BULLISH"},
        spotChart={"direction": "BULLISH"},
        pcr=1.1,
        maxPain=24500.0,
        indiaVix=13.4,
        explosionAlerts=alerts,
        heatmap=[],
    )


def test_retention_zero_keeps_old_daily_zip(tmp_path):
    settings = _settings(tmp_path, radar_archive_retention_days=0)
    old = datetime(2026, 8, 1, 10, 0, tzinfo=IST)
    current = datetime(2026, 8, 15, 10, 0, tzinfo=IST)
    with patch("app.services.radar_archive.get_settings", return_value=settings):
        record_top_radars({"NIFTY": _snap([_alert()])}, now=old)
        record_top_radars({"NIFTY": _snap([_alert(strike=24600.0)])}, now=current)

    old_zip = tmp_path / "radar_archives" / "radar-2026-08-01.zip"
    new_zip = tmp_path / "radar_archives" / "radar-2026-08-15.zip"
    assert old_zip.exists()
    assert new_zip.exists()
