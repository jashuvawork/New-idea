"""Automated EOD learning for FTV / V-momentum moments.

Every trading day (after close) this distils the day's ELITE/EXPLODING flat->vertical and
V-momentum radar outcomes into a compact, interpretable knowledge profile:

  - how far these moments typically run from the local base (peak %),
  - how deep they first dig against you (MAE %),
  - the hit-rate of a real leg,
  - and, derived from those, a recommended NEAR-BASE entry ceiling, trail keep-ratio and
    stop — so next time the same moment appears the system knows how to take it properly
    (near the local base, with sane TP/SL) instead of chasing.

The knowledge is persisted per (symbol, side, tier) and accumulates across days. Once a
day is learned, its heavy raw archive can be pruned (see cleanup_learned_eod_archives) —
the distilled knowledge is kept, the bulky tape is not.

This module only WRITES knowledge + prunes learned raw data. Applying the learned profile
to live entries is intentionally gated (observe-only by default) so a learning artefact
never silently moves live risk without being switched on.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if x == x else default  # drop NaN


def _pct(values: list[float], q: float) -> float:
    """Simple percentile (q in 0..1) on a sorted copy; safe for tiny samples."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    idx = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[idx]


def _entry_fields(entry: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Pull the learnable fields from one archived radar entry."""
    alert = entry.get("alert") if isinstance(entry.get("alert"), Mapping) else {}
    ctx = entry.get("context") if isinstance(entry.get("context"), Mapping) else {}
    outcome = entry.get("outcome") if isinstance(entry.get("outcome"), Mapping) else {}
    symbol = str(entry.get("symbol") or alert.get("symbol") or "").upper()
    side = str(entry.get("side") or alert.get("side") or "").upper()
    tier = str(entry.get("tier") or alert.get("tier") or "").upper()
    if not symbol or side not in ("CALL", "PUT"):
        return None
    # Only learn from genuine FTV / V-momentum / top-tier moments.
    is_ftv = bool(
        alert.get("ictFlatThenVertical")
        or alert.get("ictFirstLift")
        or alert.get("ictArmedBaseLaunch")
        or str(alert.get("ictPattern") or "").lower() in ("flat_then_vertical", "v_reversal")
        or tier in ("ELITE", "EXPLODING")
    )
    if not is_ftv:
        return None
    mfe = _num(outcome.get("mfePct"))
    mae = _num(outcome.get("maePct"))
    if mfe <= 0 and mae == 0:
        return None
    return {
        "symbol": symbol,
        "side": side,
        "tier": tier if tier in ("ELITE", "EXPLODING") else "OTHER",
        "mfePct": mfe,
        "maePct": mae,
        "baseRelPct": _num(alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")),
        "flatVerticalQuality": _num(alert.get("flatVerticalQuality")),
    }


def learn_ftv_profile(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Distil archived radar entries into a per (symbol,side,tier) knowledge profile.

    Pure function — no IO. Returns {key: profile} where key is 'SYMBOL:SIDE:TIER'.
    """
    settings = get_settings()
    hit_floor = _num(getattr(settings, "eod_learning_real_leg_min_mfe_pct", 50.0), 50.0)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        f = _entry_fields(entry)
        if f is None:
            continue
        key = f"{f['symbol']}:{f['side']}:{f['tier']}"
        buckets.setdefault(key, []).append(f)

    profile: dict[str, Any] = {}
    for key, rows in buckets.items():
        mfes = [r["mfePct"] for r in rows]
        maes = [abs(r["maePct"]) for r in rows if r["maePct"] < 0]
        n = len(rows)
        real = [m for m in mfes if m >= hit_floor]
        median_peak = round(statistics.median(mfes), 1) if mfes else 0.0
        p25_peak = round(_pct(mfes, 0.25), 1)
        median_mae = round(statistics.median(maes), 1) if maes else 0.0
        p75_mae = round(_pct(maes, 0.75), 1)
        hit_rate = round(len(real) / n, 3) if n else 0.0
        # Recommended NEAR-BASE entry ceiling: allow entry up to a fraction of the typical
        # first-dig (MAE) — deeper whipsaw => hug the base tighter to survive the drawdown.
        near_base_max = max(15.0, min(40.0, round(median_mae * 0.5, 1) or 20.0))
        # Trail keep: capture the bulk of the typical peak (bounded 0.6..0.85).
        trail_keep = max(0.60, min(0.85, round(0.60 + hit_rate * 0.25, 3)))
        # Recommended SL % of premium: a touch beyond the typical first-dig, capped.
        rec_sl_pct = max(8.0, min(30.0, round(p75_mae + 3.0, 1) or 12.0))
        profile[key] = {
            "count": n,
            "medianPeakPct": median_peak,
            "p25PeakPct": p25_peak,
            "medianMaePct": median_mae,
            "p75MaePct": p75_mae,
            "hitRate": hit_rate,
            "recommendedNearBaseMaxPct": near_base_max,
            "recommendedTrailKeepRatio": trail_keep,
            "recommendedStopPct": rec_sl_pct,
        }
    return profile


# ---------------------------------------------------------------------------
# Persistence + daily cycle + weekly cleanup (IO)
# ---------------------------------------------------------------------------

def _learning_dir() -> Path:
    from app.services.trade_store import get_store_dir

    d = get_store_dir() / "eod_learning"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _learned_params_file() -> Path:
    return _learning_dir() / "learned_params.json"


def load_learned_params() -> dict[str, Any]:
    path = _learned_params_file()
    if not path.exists():
        return {"version": 1, "learnedDates": [], "profiles": {}, "daily": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"version": 1, "learnedDates": [], "profiles": {}, "daily": {}}


def _merge_profiles(agg: dict[str, Any], day: dict[str, Any]) -> dict[str, Any]:
    """Sample-count-weighted blend of the accumulated profile with a new day's profile."""
    out = dict(agg)
    for key, d in day.items():
        prev = out.get(key)
        if not prev:
            out[key] = dict(d)
            continue
        n0 = max(1, int(prev.get("count", 0)))
        n1 = max(1, int(d.get("count", 0)))
        tot = n0 + n1
        blended = {"count": tot}
        for f in (
            "medianPeakPct", "p25PeakPct", "medianMaePct", "p75MaePct", "hitRate",
            "recommendedNearBaseMaxPct", "recommendedTrailKeepRatio", "recommendedStopPct",
        ):
            blended[f] = round(
                (float(prev.get(f, 0)) * n0 + float(d.get(f, 0)) * n1) / tot, 3
            )
        out[key] = blended
    return out


def run_eod_learning_cycle(date: str, *, force: bool = False) -> dict[str, Any]:
    """Learn from one date's archive and persist. Idempotent per date unless force."""
    settings = get_settings()
    if not bool(getattr(settings, "eod_learning_enabled", True)):
        return {"status": "disabled"}
    store = load_learned_params()
    if date in store.get("learnedDates", []) and not force:
        return {"status": "already_learned", "date": date}
    from app.services.radar_archive import read_archive_entries

    entries = read_archive_entries(date)
    if not entries:
        return {"status": "no_data", "date": date}
    day_profile = learn_ftv_profile(entries)
    store["profiles"] = _merge_profiles(store.get("profiles", {}), day_profile)
    store.setdefault("daily", {})[date] = day_profile
    if date not in store.get("learnedDates", []):
        store.setdefault("learnedDates", []).append(date)
        store["learnedDates"] = sorted(set(store["learnedDates"]))[-120:]
    store["updatedAt"] = datetime.now(IST).isoformat()
    _learned_params_file().write_text(json.dumps(store, indent=2, default=str))
    return {"status": "learned", "date": date, "keys": list(day_profile.keys())}


def cleanup_learned_eod_archives(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Delete heavy raw archives older than retention days — ONLY for LEARNED dates.

    The distilled knowledge (learned_params.json) is kept forever; the bulky per-day tape
    zip is removed once its knowledge has been extracted and it is past the retention window.
    """
    settings = get_settings()
    if not bool(getattr(settings, "eod_learning_cleanup_enabled", True)):
        return {"status": "disabled"}
    current = now or datetime.now(IST)
    retention = int(getattr(settings, "eod_learning_raw_retention_days", 7) or 7)
    cutoff = (current - timedelta(days=retention)).date()
    store = load_learned_params()
    learned = set(store.get("learnedDates", []))
    from app.services.radar_archive import archive_path

    removed: list[str] = []
    for date in sorted(learned):
        try:
            d = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= cutoff:
            continue  # still within retention window — keep raw
        path = archive_path(date)
        try:
            if path.exists():
                path.unlink()
                path.with_suffix(".backup.json").unlink(missing_ok=True)
                removed.append(date)
        except OSError:
            continue
    return {"status": "ok", "removed": removed, "retentionDays": retention}


def learned_ftv_profile(symbol: str, side: str, tier: str = "ELITE") -> dict[str, Any]:
    """Read the accumulated learned profile for a moment type (observe-only helper)."""
    store = load_learned_params()
    key = f"{str(symbol).upper()}:{str(side).upper()}:{str(tier).upper()}"
    return dict(store.get("profiles", {}).get(key) or {})
