"""NSE (NIFTY) / BSE (SENSEX) index momentum from constituent heatmap + gap data."""

from __future__ import annotations

from typing import Optional

from app.models.schemas import PremarketAnalysis, Side, SymbolSnapshot
from app.engines.premarket_engine import is_open_drive_window

EXCHANGE_LABEL = {
    "NIFTY": "NSE",
    "SENSEX": "BSE",
    "BANKNIFTY": "NSE",
}


def exchange_for_symbol(symbol: str) -> str:
    return EXCHANGE_LABEL.get(symbol.upper(), symbol.upper())


def _side_from_gap(gap_direction: str) -> Optional[Side]:
    if gap_direction == "GAP_DOWN":
        return Side.PUT
    if gap_direction == "GAP_UP":
        return Side.CALL
    return None


def side_aligned_with_index_moment(side: Side, snap: SymbolSnapshot) -> bool:
    """CALL+gap-up / PUT+gap-down with constituent breadth confirmation."""
    pm = snap.premarket
    hm = snap.constituentHeatmap
    if not pm:
        return False

    gap_side = _side_from_gap(pm.gapDirection)
    if gap_side is None or gap_side != side:
        return False

    if pm.gapSize in ("LARGE", "EXTREME"):
        return True

    if hm and hm.dataAvailable:
        if side == Side.PUT and hm.bias == "BEARISH":
            return True
        if side == Side.CALL and hm.bias == "BULLISH":
            return True

    if pm.auctionBias == "BEARISH" and side == Side.PUT:
        return pm.gapSize in ("MODERATE", "LARGE", "EXTREME")
    if pm.auctionBias == "BULLISH" and side == Side.CALL:
        return pm.gapSize in ("MODERATE", "LARGE", "EXTREME")

    return pm.gapSize in ("MODERATE", "LARGE", "EXTREME") and pm.confidence >= 55


def index_moment_active(snap: SymbolSnapshot) -> tuple[bool, str]:
    """
    Strong open-drive moment — NSE/BSE constituent breadth + index gap aligned.
    Captures chart-style premium explosions at the open (e.g. NIFTY PE gap-up).
    """
    if not is_open_drive_window():
        return False, "outside_open_drive"

    pm: Optional[PremarketAnalysis] = snap.premarket
    hm = snap.constituentHeatmap
    if not pm:
        return False, "no_premarket"

    if pm.gapSize in ("FLAT", "SMALL") and (not hm or not hm.dataAvailable):
        return False, "flat_gap_no_constituents"

    vel = 0.0
    if snap.explosiveRunner and snap.explosiveRunner.signal:
        vel = snap.explosiveRunner.signal.premiumVelocityPct or 0.0

    gap_ok = pm.gapSize in ("MODERATE", "LARGE", "EXTREME")
    explosion_risk = (pm.explosionRisk or "").upper() in ("HIGH", "ELEVATED", "MEDIUM")
    breadth_ok = False
    if hm and hm.dataAvailable:
        breadth_ok = hm.breadthPct >= 58 or hm.breadthPct <= 42
        if pm.gapDirection == "GAP_DOWN" and hm.bias == "BEARISH":
            breadth_ok = True
        if pm.gapDirection == "GAP_UP" and hm.bias == "BULLISH":
            breadth_ok = True

    if pm.gapSize in ("LARGE", "EXTREME") and (breadth_ok or explosion_risk or vel >= 2.0):
        return True, f"{exchange_for_symbol(snap.symbol)}_gap_{pm.gapSize.lower()}"

    if gap_ok and breadth_ok and (explosion_risk or vel >= 1.5 or pm.volumeSurgeScore >= 50):
        return True, f"{exchange_for_symbol(snap.symbol)}_open_moment"

    if vel >= 2.5 and pm.gapSize != "FLAT":
        return True, f"{exchange_for_symbol(snap.symbol)}_premium_velocity"

    return False, "no_moment"


def index_moment_rank_bonus(snap: SymbolSnapshot, side: Side) -> float:
    active, _ = index_moment_active(snap)
    if not active or not side_aligned_with_index_moment(side, snap):
        return 0.0
    pm = snap.premarket
    bonus = 8.0
    if pm and pm.gapSize in ("LARGE", "EXTREME"):
        bonus += 7.0
    elif pm and pm.gapSize == "MODERATE":
        bonus += 4.0
    hm = snap.constituentHeatmap
    if hm and hm.dataAvailable and hm.bias in ("BULLISH", "BEARISH"):
        bonus += 3.0
    return bonus


def any_index_moment_active(snapshots: dict[str, SymbolSnapshot]) -> bool:
    return any(index_moment_active(s)[0] for s in snapshots.values() if s.dataAvailable)


def index_moment_summary(snap: SymbolSnapshot) -> dict:
    """Per-symbol NSE/BSE moment for dashboard + chop guards."""
    active, reason = index_moment_active(snap)
    pm = snap.premarket
    hm = snap.constituentHeatmap
    return {
        "exchange": exchange_for_symbol(snap.symbol),
        "momentActive": active,
        "momentReason": reason if active else None,
        "gapDirection": pm.gapDirection if pm else None,
        "gapSize": pm.gapSize if pm else None,
        "gapPct": round(pm.gapPct, 2) if pm else None,
        "auctionBias": pm.auctionBias if pm else None,
        "explosionRisk": pm.explosionRisk if pm else None,
        "constituentBreadthPct": hm.breadthPct if hm and hm.dataAvailable else None,
        "constituentBias": hm.bias if hm and hm.dataAvailable else None,
        "constituentAdvancing": hm.advancing if hm and hm.dataAvailable else None,
        "constituentDeclining": hm.declining if hm and hm.dataAvailable else None,
    }
