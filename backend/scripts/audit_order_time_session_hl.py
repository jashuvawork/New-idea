#!/usr/bin/env python3
"""Prove whether wiring execution-chart dayHigh/dayLow into order-time snap saves losses."""

from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IST = ZoneInfo("Asia/Kolkata")
ARTIFACT = Path("/opt/cursor/artifacts/two-week-1022-1024-loss-audit.json")
OUT = Path("/opt/cursor/artifacts/order-time-session-hl-audit.json")
ZIP_DIR = Path("/tmp/nexusquant/trades/radar_archives")


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        s = str(raw)
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
    except Exception:
        return None


def _index_hi_lo_at(
    batches: list[dict[str, Any]] | None,
    sym: str,
    at: datetime,
) -> tuple[float, float, float]:
    if not batches:
        return 0.0, 0.0, 0.0
    pts: list[tuple[datetime, float]] = []
    for batch in batches:
        ts = _parse_ts(batch.get("ts"))
        if ts is None or ts > at:
            break
        for c in batch.get("contracts") or []:
            if str(c.get("symbol") or "").upper() != sym:
                continue
            spot = float(c.get("spot") or 0)
            if spot > 0:
                pts.append((ts, spot))
                break
    if not pts:
        return 0.0, 0.0, 0.0
    lo = min(s for _, s in pts)
    hi = max(s for _, s in pts)
    spot = pts[-1][1]
    return hi, lo, spot


def _load_tape(date: str) -> list[dict[str, Any]] | None:
    zpath = ZIP_DIR / f"radar-{date}.zip"
    if not zpath.is_file():
        return None
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(zpath) as zf:
        if "premium_tape.jsonl" not in zf.namelist():
            return None
        with zf.open("premium_tape.jsonl") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _rebuild_snap(row: dict[str, Any], hi: float, lo: float, spot: float):
    from app.models.schemas import (
        AutoTraderState,
        Breadth,
        ChartAnalysis,
        MarketPhase,
        Regime,
        Side,
        SpotChart,
        SymbolSnapshot,
    )

    checks = (row.get("checks") or {})
    pv = checks.get("participationVeto") or {}
    metrics = pv.get("indexRallyMetrics") or {}
    sym = str(metrics.get("symbol") or row.get("leg", "").split()[0]).upper()
    side_s = "CALL" if "CALL" in row.get("leg", "") else "PUT"
    wh = checks.get("wireHydration") or {}
    chart_dir = str(wh.get("chartDirection") or "NEUTRAL").upper()
    breadth_bias = str((pv.get("sessionIntent") or {}).get("breadthBias") or "NEUTRAL").upper()

    if spot <= 0:
        spot = float(metrics.get("spot") or wh.get("spot") or 0)
    if hi <= 0 or lo <= 0:
        hi = float(metrics.get("sessionHigh") or spot)
        lo = float(metrics.get("sessionLow") or spot)

    inst = {"dayHigh": hi, "dayLow": lo, "dayOpen": lo}
    snap = SymbolSnapshot(
        symbol=sym,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(
            bias=breadth_bias,
            score=50,
            aligned=breadth_bias in ("BULLISH", "BEARISH"),
        ),
        spotChart=SpotChart(
            direction=chart_dir,
            momentum5Pct=float(metrics.get("momentum5Pct") or 0),
            rsi=float(metrics.get("rsi") or 50),
            macdBias=str(metrics.get("macdBias") or "NEUTRAL"),
            macdHistogram=float(metrics.get("macdHistogram") or 0),
        ),
        chartAnalysis=ChartAnalysis(consensus=chart_dir, institutional=inst),
    )
    cand = SimpleNamespace(
        symbol=sym,
        side=Side.CALL if side_s == "CALL" else Side.PUT,
        alert={"localPadPct": pv.get("localPadPct"), "localBaseMovePct": pv.get("localPadPct")},
        snap=snap,
    )
    return cand, snap, sym


def _chart_meta(hi: float, lo: float, spot: float, row: dict[str, Any]) -> dict[str, Any]:
    wh = row.get("checks", {}).get("wireHydration") or {}
    chart = wh.get("chartDirection") or "NEUTRAL"
    from app.models.schemas import SpotChart

    full = SpotChart(
        direction=str(chart).upper(),
        momentum5Pct=0.0,
    ).model_dump()
    return {
        "source": "upstox_live",
        "spot": spot,
        "indexChartFull": full,
        "quoteContext": {
            "dayHigh": round(hi, 2),
            "dayLow": round(lo, 2),
            "dayOpen": round(lo, 2),
        },
    }


def _replay(row: dict[str, Any], *, stamp_ohlc: bool) -> tuple[bool, str, dict[str, Any]]:
    from app.config import get_settings
    from app.engines.order_time_entry_pass import order_time_entry_blocked
    from app.models.schemas import AutoTraderState

    settings = get_settings()
    at = _parse_ts(row.get("openedAt") or row.get("date"))
    sym = str(row.get("leg", "NIFTY").split()[0]).upper()
    batches = _load_tape(str(row.get("date") or (at.date() if at else "")))
    hi, lo, spot = _index_hi_lo_at(batches, sym, at) if at else (0.0, 0.0, 0.0)
    cand, base_snap, sym_u = _rebuild_snap(row, hi, lo, spot)

    if stamp_ohlc and (hi <= 0 or lo <= 0):
        stamp_ohlc = False

    # Baseline: flat session range (reproduces prod miss)
    flat_snap = base_snap.model_copy(
        update={
            "chartAnalysis": base_snap.chartAnalysis.model_copy(
                update={"institutional": {}}
            )
            if base_snap.chartAnalysis
            else None,
        }
    )
    flat_snap = flat_snap.model_copy(update={"spot": spot or flat_snap.spot})
    # Collapse extremes like broken wire
    if flat_snap.chartAnalysis:
        flat_snap.chartAnalysis.institutional = {}
    wire_snap = flat_snap
    if stamp_ohlc and hi > 0 and lo > 0:
        ca = wire_snap.chartAnalysis.model_copy(deep=True) if wire_snap.chartAnalysis else None
        if ca is not None:
            inst = dict(ca.institutional or {})
            inst["dayHigh"] = round(hi, 2)
            inst["dayLow"] = round(lo, 2)
            if inst.get("dayOpen", 0) <= 0:
                inst["dayOpen"] = round(lo, 2)
            ca.institutional = inst
            wire_snap = wire_snap.model_copy(
                update={"chartAnalysis": ca, "spot": spot or wire_snap.spot}
            )
    snapshots = {sym_u: wire_snap}
    state = AutoTraderState()
    chart_meta = _chart_meta(hi, lo, spot or flat_snap.spot, row) if stamp_ohlc else None

    blocked, reason, meta = order_time_entry_blocked(
        cand,
        state,
        snapshots,
        chart_meta=chart_meta,
        is_live=True,
        settings=settings,
    )
    return blocked, reason, meta


def main() -> None:
    if not ARTIFACT.is_file():
        print("missing", ARTIFACT)
        sys.exit(1)
    rows = json.loads(ARTIFACT.read_text())
    out: list[dict[str, Any]] = []
    loss_saved = 0.0
    newly_blocked = 0
    for row in rows:
        pnl = float(row.get("pnlInr") or 0)
        before_b = bool(row.get("order1022_blocked"))
        after_b, after_r, after_meta = _replay(row, stamp_ohlc=True)
        with_pv = ((after_meta.get("checks") or {}).get("participationVeto") or {})
        metrics = with_pv.get("indexRallyMetrics") or {}
        helps = pnl < 0 and after_b and not before_b
        if helps:
            newly_blocked += 1
            loss_saved += abs(pnl)
        out.append(
            {
                "leg": row.get("leg"),
                "date": row.get("date"),
                "pnlInr": pnl,
                "beforeBlocked": before_b,
                "afterBlocked": after_b,
                "afterReason": after_r,
                "helpsLoss": helps,
                "indexRallyAfter": metrics,
            }
        )
    placement = {
        "order_time_only_in_auto_trader_open_from_candidate": True,
        "skipped_when_snapshots_falsy": "if snapshots: guard in auto_trader — use snap fallback missing",
        "snapshots_vs_snap_divergence": "preflight uses snap; order_time uses snapshots[sym]",
        "quoteContext_not_merged_today": True,
    }
    summary = {
        "lossLegs": sum(1 for r in rows if float(r.get("pnlInr") or 0) < 0),
        "newlyBlockedLosses": newly_blocked,
        "inrSavedIfBlocked": round(loss_saved, 2),
        "placementGaps": placement,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": out}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()