"""Aug27 afternoon SENSEX PUT 77300 — pad entry + P&L replay from radar archive."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.bullish_local_base import alert_bullish_local_base_prediction
from app.engines.capital_allocator import lot_multiplier, max_lots_for_capital
from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.engines.moment_stage_trail import build_moment_stage_plan
from app.models.schemas import (
    Breadth,
    MarketPhase,
    PaperTrade,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE = Path("/tmp/radar/radar-2026-08-27.zip")
ARCHIVE_URL = "https://jashuvatrade.xyz/api/ai/radar-archives/2026-08-27"


@pytest.fixture(scope="module")
def aug27_archive() -> Path:
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists() or ARCHIVE.stat().st_size < 1000:
        try:
            urllib.request.urlretrieve(ARCHIVE_URL, ARCHIVE)
        except urllib.error.HTTPError:
            pytest.skip("Aug27 radar archive download failed (API unavailable)")
    if not ARCHIVE.exists():
        pytest.skip("Aug27 radar archive unavailable")
    return ARCHIVE


def _load_77300(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as zf:
        row = next(
            r
            for r in json.loads(zf.read("all_radars.json"))
            if r.get("key") == "SENSEX:PUT:77300"
        )
    return row


def _snap(ctx: dict) -> SymbolSnapshot:
    sc = ctx.get("spotChart") or {}
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 27, 12, 43, 41, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 77350),
        atmStrike=float(ctx.get("atmStrike") or 77300),
        tradeQualityScore=float(ctx.get("tradeQualityScore") or 55),
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction=sc.get("direction", "BEARISH"),
            momentum5Pct=float(sc.get("momentum5Pct") or -0.2),
            momentum10Pct=float(sc.get("momentum10Pct") or -0.1),
            recommendedSide="PUT",
        ),
    )


@patch("app.engines.bullish_local_base.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_afternoon_pad_gates_active_at_1243(mock_ict, mock_bull, aug27_archive):
    row = _load_77300(aug27_archive)
    alert = dict(row["alert"])
    snap = _snap(row.get("context") or {})
    settings = Settings()
    mock_bull.return_value = settings
    mock_ict.return_value = settings

    pred = alert_bullish_local_base_prediction(alert, snap)
    event = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77300.0,
        tier=alert.get("tier"),
        explosion_score=float(alert.get("explosionScore") or 0),
        premium=float(alert.get("premium") or 0),
        velocity_3s=float(alert.get("velocity3s") or 0),
        velocity_9s=float(alert.get("velocity9s") or 0),
        volume_surge=float(alert.get("volumeSurge") or 0),
        daily_move_pct=float(alert.get("dailyMovePct") or 0),
        peak_move_pct=float(alert.get("peakMovePct") or 0),
    )
    ict = SimpleNamespace(
        base_relative_move_pct=float(alert.get("ictBaseRelativeMovePct") or 0),
        base_premium=float(alert.get("ictBasePremium") or 0),
        flat_then_vertical=bool(alert.get("ictFlatThenVertical")),
        volume_awakening=bool(alert.get("ictVolumeAwakening")),
        active=bool(alert.get("ictBreakout")),
        displacement=bool(alert.get("ictDisplacement")),
    )
    ok, reason = first_lift_entry_readiness(
        snap=snap, event=event, ict=ict, alert=alert,
    )

    assert pred["active"] is True, pred
    assert ok is True, reason
    assert float(alert["premium"]) >= 80.0
    assert float(alert["localBaseMovePct"]) >= 20.0


def test_afternoon_session_pnl_replay_to_chart_peak(aug27_archive):
    """Replay 12:43 pad entry → chart afternoon spike (~₹200)."""
    row = _load_77300(aug27_archive)
    alert = row["alert"]
    entry_prem = 83.95  # afternoon local-base pad (chart ~₹80 zone)
    peak_prem = 200.0  # user chart peak
    units = int(lot_multiplier("SENSEX") or 20)
    lots = max(1, max_lots_for_capital("SENSEX", entry_prem))
    stop_pts = max(16.0, entry_prem * 0.18)
    plan = build_moment_stage_plan(
        entry_premium=entry_prem,
        base_premium=float(alert.get("ictBasePremium") or 69.35),
        velocity_3s=4.2,
        volume_surge=2.5,
        session_move_pct=21.0,
        flat_then_vertical=True,
        max_profit=True,
    )
    ctx = {
        "momentType": "flat_then_vertical",
        "ictFlatThenVertical": True,
        "maxProfitCapture": True,
        "ictBasePremium": float(alert.get("ictBasePremium") or 69.35),
        "eliteFullLot": True,
        "velocity3s": 4.2,
        "vBaseFtvRunner": True,
        "exitPlan": {
            "stopPoints": round(stop_pts, 2),
            "entryStopPoints": round(stop_pts, 2),
            "targetPoints": 180.0,
        },
    }
    if plan:
        ctx.update(plan)
    trade = PaperTrade(
        id="SENSEX:PUT:77300",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77300.0,
        entryPremium=entry_prem,
        currentPremium=entry_prem,
        lots=lots,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        bestPnlPoints=0.0,
        entryContext=ctx,
    )
    path = [
        (0, entry_prem),
        (120, 95.0),
        (300, 120.0),
        (600, 160.0),
        (900, peak_prem),
        (1200, 170.0),
        (1800, 140.0),
    ]
    exit_rec = None
    peak_seen = entry_prem
    for elapsed, prem in path:
        trade.currentPremium = prem
        trade.bestPnlPoints = max(trade.bestPnlPoints, prem - entry_prem)
        peak_seen = max(peak_seen, prem)
        v = 3.0 if prem >= peak_seen * 0.98 else 0.5
        trade.entryContext["liveVelocity3s"] = v
        reason, _ = evaluate_explosion_exit(
            trade, prem, "ELITE", units, live_velocity_3s=v,
        )
        if reason:
            exit_rec = (elapsed, prem, reason)
            break
    assert exit_rec is not None
    _, exit_prem, _ = exit_rec
    pnl_inr = (exit_prem - entry_prem) * lots * units
    mfe_inr = (peak_prem - entry_prem) * lots * units
    assert pnl_inr >= 30_000
    assert mfe_inr >= 60_000
