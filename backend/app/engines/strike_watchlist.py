"""Strike watchlist — CE + PE priority strikes for NIFTY and SENSEX (live + next-day)."""

from __future__ import annotations

from typing import Any, Optional

from app.models.schemas import SymbolSnapshot

_TIER_RANK = {"ELITE": 4, "EXPLODING": 3, "BUILDING": 2, "WATCH": 1}


def _alert_rows(snap: SymbolSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for alert in snap.explosionAlerts or []:
        if isinstance(alert, dict):
            rows.append(alert)
        else:
            rows.append({
                "side": getattr(alert, "side", None),
                "strike": getattr(alert, "strike", None),
                "premium": getattr(alert, "premium", None),
                "explosionScore": getattr(alert, "explosionScore", None),
                "tier": getattr(alert, "tier", None),
                "dailyMovePct": getattr(alert, "dailyMovePct", None),
                "peakMovePct": getattr(alert, "peakMovePct", None),
                "velocity3s": getattr(alert, "velocity3s", None),
                "tradeable": getattr(alert, "tradeable", True),
                "reason": getattr(alert, "reason", None),
            })
    return rows


def _runner_rows(snap: SymbolSnapshot) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in snap.explosiveRunnerWatchlist or []:
        if isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({
                "side": getattr(item, "side", None),
                "strike": getattr(item, "strike", None),
                "premium": getattr(item, "premium", None),
                "score": getattr(item, "score", None),
                "premiumVelocityPct": getattr(item, "premiumVelocityPct", None),
                "elite": getattr(item, "elite", False),
            })
    return rows


def _priority(score: float, tier: str, move: float) -> float:
    return round(float(score or 0) + _TIER_RANK.get(str(tier or "").upper(), 0) * 8.0 + min(40.0, abs(float(move or 0)) * 0.15), 2)


def _candidates_for_side(snap: SymbolSnapshot, side: str, *, limit: int = 3) -> list[dict[str, Any]]:
    side_u = side.upper()
    scored: list[dict[str, Any]] = []

    for alert in _alert_rows(snap):
        if str(alert.get("side") or "").upper() != side_u:
            continue
        strike = float(alert.get("strike") or 0)
        if strike <= 0:
            continue
        score = float(alert.get("explosionScore") or 0)
        tier = str(alert.get("tier") or "WATCH").upper()
        move = max(float(alert.get("dailyMovePct") or 0), float(alert.get("peakMovePct") or 0))
        scored.append({
            "side": side_u,
            "strike": strike,
            "premium": round(float(alert.get("premium") or 0), 2),
            "score": round(score, 1),
            "tier": tier,
            "movePct": round(move, 1),
            "velocity3s": round(float(alert.get("velocity3s") or 0), 2),
            "tradeable": bool(alert.get("tradeable", True)),
            "source": "explosion_radar",
            "reason": str(alert.get("reason") or tier),
            "priority": _priority(score, tier, move),
        })

    if len(scored) < limit:
        seen = {(r["strike"]) for r in scored}
        for item in _runner_rows(snap):
            if str(item.get("side") or "").upper() != side_u:
                continue
            strike = float(item.get("strike") or 0)
            if strike <= 0 or strike in seen:
                continue
            score = float(item.get("score") or 0)
            elite = bool(item.get("elite"))
            tier = "ELITE" if elite else ("EXPLODING" if score >= 45 else "BUILDING")
            scored.append({
                "side": side_u,
                "strike": strike,
                "premium": round(float(item.get("premium") or 0), 2),
                "score": round(score, 1),
                "tier": tier,
                "movePct": round(float(item.get("premiumVelocityPct") or 0), 1),
                "velocity3s": round(float(item.get("premiumVelocityPct") or 0), 2),
                "tradeable": True,
                "source": "runner_watchlist",
                "reason": "runner_scan",
                "priority": _priority(score, tier, float(item.get("premiumVelocityPct") or 0)),
            })
            seen.add(strike)

    # ATM fallback so every index always shows CE + PE anchors.
    if not scored and snap.atmStrike:
        atm = float(snap.atmStrike)
        scored.append({
            "side": side_u,
            "strike": atm,
            "premium": 0.0,
            "score": float(snap.tradeQualityScore or 0),
            "tier": "ATM",
            "movePct": 0.0,
            "velocity3s": 0.0,
            "tradeable": True,
            "source": "atm_anchor",
            "reason": "ATM fallback",
            "priority": float(snap.tradeQualityScore or 0),
        })

    scored.sort(key=lambda r: (r.get("priority") or 0, r.get("score") or 0), reverse=True)
    # De-dupe by strike keeping highest priority
    out: list[dict[str, Any]] = []
    seen_strikes: set[float] = set()
    for row in scored:
        st = float(row["strike"])
        if st in seen_strikes:
            continue
        seen_strikes.add(st)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def build_symbol_strike_watchlist(snap: SymbolSnapshot, *, per_side: int = 3) -> dict[str, Any]:
    """CE + PE priority strikes for one index."""
    calls = _candidates_for_side(snap, "CALL", limit=per_side)
    puts = _candidates_for_side(snap, "PUT", limit=per_side)
    top = None
    pool = calls + puts
    if pool:
        top = max(pool, key=lambda r: r.get("priority") or 0)
    return {
        "symbol": snap.symbol,
        "spot": snap.spot,
        "atmStrike": snap.atmStrike,
        "optionExpiry": snap.optionExpiry,
        "calls": calls,
        "puts": puts,
        "topPriority": top,
        "bias": (
            "CALL" if (calls and puts and (calls[0].get("priority") or 0) > (puts[0].get("priority") or 0) * 1.15)
            else "PUT" if (calls and puts and (puts[0].get("priority") or 0) > (calls[0].get("priority") or 0) * 1.15)
            else "BOTH"
        ),
    }


def build_strike_watchlist(
    snapshots: dict[str, SymbolSnapshot],
    *,
    per_side: int = 3,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Dual-index CE/PE strike watchlist for trade priority (live or next-day seed).

    Always covers NIFTY + SENSEX when data is available — both CALL and PUT.
    """
    wanted = [s.upper() for s in (symbols or ["NIFTY", "SENSEX"])]
    indexes: list[dict[str, Any]] = []
    for sym in wanted:
        snap = snapshots.get(sym) or snapshots.get(sym.title())
        if snap is None:
            # try case-insensitive
            for k, v in snapshots.items():
                if str(k).upper() == sym:
                    snap = v
                    break
        if snap is None or not getattr(snap, "dataAvailable", False):
            indexes.append({
                "symbol": sym,
                "spot": None,
                "atmStrike": None,
                "optionExpiry": None,
                "calls": [],
                "puts": [],
                "topPriority": None,
                "bias": "—",
                "unavailable": True,
            })
            continue
        indexes.append(build_symbol_strike_watchlist(snap, per_side=per_side))

    flat: list[dict[str, Any]] = []
    for idx in indexes:
        for side_key, side_label in (("calls", "CALL"), ("puts", "PUT")):
            for row in idx.get(side_key) or []:
                flat.append({
                    "symbol": idx.get("symbol"),
                    "expiry": idx.get("optionExpiry"),
                    "spot": idx.get("spot"),
                    "atmStrike": idx.get("atmStrike"),
                    **row,
                    "side": side_label,
                })
    flat.sort(key=lambda r: r.get("priority") or 0, reverse=True)

    return {
        "indexes": indexes,
        "priorityQueue": flat[:16],
        "symbols": [i.get("symbol") for i in indexes],
    }
