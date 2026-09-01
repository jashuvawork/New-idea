"""Actual option-premium calibration, quality, drift, and event regressions."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.engines.ftv_premium_calibration import (
    _premium_tape_available,
    build_and_persist_premium_calibration,
    build_premium_calibration,
    extract_premium_observations,
    load_premium_calibration,
)
from app.engines.ftv_probability import (
    clear_ftv_probability_cache,
    estimate_live_probabilities,
)
from app.engines.scheduled_market_events import build_scheduled_event_context
from app.models.schemas import (
    Breadth,
    Greeks,
    HeatmapStrike,
    MarketPhase,
    Orderflow,
    SpotChart,
    SymbolSnapshot,
)
from app.services import radar_archive, radar_learning

IST = ZoneInfo("Asia/Kolkata")


def _premium_series(day: datetime, *, winner: bool) -> list[tuple[datetime, float]]:
    rows: list[tuple[datetime, float]] = []
    for seconds in range(0, 17 * 60 + 1, 15):
        premium = 100.0
        if winner and seconds >= 4 * 60:
            premium = 125.0
        rows.append((day + timedelta(seconds=seconds), premium))
    return rows


def _observations(date: str, *, call_winner: bool) -> list[dict]:
    day = datetime.fromisoformat(f"{date}T10:00:00").replace(tzinfo=IST)
    return extract_premium_observations(
        date,
        {
            "NIFTY:CALL:24500": _premium_series(day, winner=call_winner),
            "NIFTY:PUT:24500": _premium_series(day, winner=not call_winner),
        },
        flat_window_seconds=120,
        flat_max_range_pct=8.0,
        vertical_move_pct=20.0,
        sample_seconds=60,
        bucket_minutes=15,
    )


def test_premium_tape_labels_actual_ce_and_pe_horizons():
    rows = _observations("2026-08-10", call_winner=True)

    call = [row for row in rows if row["side"] == "CALL"]
    put = [row for row in rows if row["side"] == "PUT"]
    assert call and put
    assert any(row["labels"]["5"] == 1 for row in call)
    assert all(row["labels"]["5"] == 0 for row in put)


def test_walk_forward_is_temporal_and_drift_lowers_quality():
    observations: list[dict] = []
    dates = [f"2026-08-{day:02d}" for day in range(1, 11)]
    for date in dates[:8]:
        observations.extend(_observations(date, call_winner=True))
    for date in dates[8:]:
        observations.extend(_observations(date, call_winner=False))

    profile = build_premium_calibration(
        observations,
        generated_at=datetime(2026, 8, 11, tzinfo=IST),
        source_dates=dates,
        drift_warn_pp=8.0,
        drift_critical_pp=15.0,
    )

    assert profile["walkForward"]["status"] == "READY"
    assert profile["walkForward"]["validationSamples"] > 0
    assert profile["walkForward"]["brierScore"] is not None
    assert profile["drift"]["status"] == "DRIFT"
    assert profile["symbols"]["NIFTY"]["rates"]["CALL"]["5"]["samples"] > 0


def test_calibration_is_atomically_persisted_and_reused(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        trade_store_dir=str(tmp_path),
        radar_archive_dir="",
        ftv_probability_profile_cache_seconds=1800,
        ftv_premium_calibration_history_days=30,
        radar_hindsight_flat_window_seconds=120,
        radar_hindsight_flat_max_range_pct=8.0,
        ftv_premium_vertical_move_pct=20.0,
        ftv_premium_calibration_sample_seconds=60,
        ftv_probability_time_bucket_minutes=15,
        ftv_probability_drift_warn_pct_points=8.0,
        ftv_probability_drift_critical_pct_points=15.0,
    )
    monkeypatch.setattr(
        "app.engines.ftv_premium_calibration.get_settings", lambda: settings,
    )
    monkeypatch.setattr(radar_learning, "get_settings", lambda: settings)
    monkeypatch.setattr(radar_archive, "get_settings", lambda: settings)
    current = datetime(2026, 8, 16, 16, 0, tzinfo=IST)
    date = "2026-08-16"
    path = radar_learning.premium_tape_path(date)
    day = datetime(2026, 8, 16, 10, 0, tzinfo=IST)
    batches = []
    for ts, premium in _premium_series(day, winner=True):
        batches.append({
            "ts": ts.isoformat(),
            "contracts": [{
                "key": "NIFTY:CALL:24500",
                "premium": premium,
            }],
        })
    path.write_text(
        "".join(json.dumps(batch) + "\n" for batch in batches),
        encoding="utf-8",
    )

    built = build_and_persist_premium_calibration(force=True, now=current)
    loaded = load_premium_calibration()

    assert built["observationCount"] > 0
    assert date in built["sourceDates"]
    assert loaded == built
    assert (tmp_path / "ftv_probability" / "premium_calibration.json").exists()
    assert not list((tmp_path / "ftv_probability").glob("*.tmp"))


def _profile() -> dict:
    rates = {
        side: {
            str(horizon): {"samples": 300, "wins": 120, "probabilityPct": 40.0}
            for horizon in (1, 3, 5, 15)
        }
        for side in ("CALL", "PUT")
    }
    return {
        "rates": rates,
        "buckets": {},
        "premiumCalibration": {
            "sampleCount": 1200,
            "rates": rates,
            "buckets": {},
        },
        "premiumQuality": {
            "walkForward": {"brierScore": 0.18, "meanCalibrationErrorPct": 4.0},
            "drift": {"status": "STABLE", "maxDeltaPctPoints": 3.0},
        },
    }


def test_live_probability_reports_spread_iv_oi_and_premium_source():
    clear_ftv_probability_cache()
    day = datetime(2026, 8, 12, 9, 15, tzinfo=IST)
    candles = [
        [(day + timedelta(minutes=i)).isoformat(), 100, 100.02, 99.98, 100, 1000, 0]
        for i in range(20)
    ]
    snapshot = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=day + timedelta(minutes=20),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=24_500,
        atmStrike=24_500,
        spotChart=SpotChart(direction="BULLISH"),
        breadth=Breadth(bias="BULLISH", score=65),
        orderflow=Orderflow(bidAskImbalance=60),
        greeks=Greeks(ivExpansion=1.15),
        heatmap=[HeatmapStrike(
            strike=24_500,
            callLtp=100,
            callBid=99,
            callAsk=101,
            callIv=15,
            callOi=45_000,
            callVolume=20_000,
            liquidityScore=80,
        )],
        explosionAlerts=[{
            "side": "CALL",
            "strike": 24_500,
            "explosionScore": 70,
            "velocity3s": 2.0,
            "volumeSurge": 2.0,
        }],
    )

    estimate_live_probabilities(_profile(), candles, snapshot)
    snapshot.heatmap[0].callIv = 18
    snapshot.heatmap[0].callOi = 50_000
    result = estimate_live_probabilities(_profile(), candles, snapshot)
    call = result["sides"]["CALL"]

    assert call["probabilitySources"]["5"] == "HYBRID_PREMIUM_70_INDEX_30"
    assert call["optionFeatures"]["spreadPct"] == 2.0
    assert call["optionFeatures"]["iv"] == 18.0
    assert call["optionFeatures"]["oi"] == 50_000
    assert call["optionFeatures"]["ivExpansion"] == 1.2
    assert call["optionFeatures"]["oiChangePct"] == 11.11
    assert result["modelQuality"]["driftStatus"] == "STABLE"


def test_verified_event_and_upstox_expiry_are_exposed(monkeypatch):
    settings = SimpleNamespace(
        ftv_scheduled_events_json=json.dumps([{
            "date": "2026-08-20",
            "time": "10:00",
            "title": "RBI policy decision",
            "impact": "HIGH",
            "symbols": ["NIFTY"],
            "sideBias": "BOTH",
        }]),
        ftv_scheduled_event_lead_minutes=30,
    )
    monkeypatch.setattr(
        "app.engines.scheduled_market_events.get_settings", lambda: settings,
    )
    now = datetime(2026, 8, 20, 9, 45, tzinfo=IST)
    snapshot = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=now,
        marketPhase=MarketPhase.LIVE_MARKET,
        optionExpiry="2026-08-20",
    )

    result = build_scheduled_event_context({"NIFTY": snapshot}, now=now)

    assert result["riskLevel"] == "HIGH"
    assert {row["source"] for row in result["activeOrUpcoming"]} == {
        "operator_verified", "upstox_option_expiry",
    }
    assert "operator-verified" in result["guardrail"]


def test_premium_calibration_reads_bundled_archive_tape(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        trade_store_dir=str(tmp_path),
        radar_archive_dir=str(tmp_path / "radar_archives"),
        ftv_probability_profile_cache_seconds=1800,
        ftv_premium_calibration_history_days=30,
        ftv_premium_calibration_use_archived_tape=True,
        radar_hindsight_flat_window_seconds=120,
        radar_hindsight_flat_max_range_pct=8.0,
        ftv_premium_vertical_move_pct=20.0,
        ftv_premium_calibration_sample_seconds=60,
        ftv_probability_time_bucket_minutes=15,
        ftv_probability_drift_warn_pct_points=8.0,
        ftv_probability_drift_critical_pct_points=15.0,
    )
    monkeypatch.setattr(
        "app.engines.ftv_premium_calibration.get_settings", lambda: settings,
    )
    monkeypatch.setattr(radar_learning, "get_settings", lambda: settings)
    monkeypatch.setattr(radar_archive, "get_settings", lambda: settings)
    archive_dir = tmp_path / "radar_archives"
    archive_dir.mkdir(parents=True)
    date = "2026-08-16"
    day = datetime(2026, 8, 16, 10, 0, tzinfo=IST)
    batches = []
    for ts, premium in _premium_series(day, winner=True):
        batches.append({
            "ts": ts.isoformat(),
            "contracts": [{
                "key": "NIFTY:CALL:24500",
                "premium": premium,
            }],
        })
    tape_payload = "".join(json.dumps(batch) + "\n" for batch in batches)
    archive_path = archive_dir / f"radar-{date}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("premium_tape.jsonl", tape_payload)

    assert _premium_tape_available(date) is True
    built = build_and_persist_premium_calibration(
        force=True,
        now=datetime(2026, 8, 16, 16, 0, tzinfo=IST),
    )
    assert built["observationCount"] > 0
    assert date in built["sourceDates"]
