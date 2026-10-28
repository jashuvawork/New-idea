"""Swing trading engine — multi-day index option positions (paper)."""

from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.engines.premium_filter import premium_in_band
from app.engines.strategies.base import compute_max_pain, compute_pcr
from app.models.schemas import Breadth, MarketProfile, Orderflow, Regime, Side


@dataclass
class SwingSetup:
    symbol: str
    side: Side
    strike: float
    premium: float
    swingType: str
    confidence: float
    reason: str
    targetPct: float = 30.0
    stopPct: float = 12.0
    maxHoldDays: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)


def _get_option(chain: list, strike: float, side: Side) -> dict:
    for row in chain:
        s = row.get("strike_price") or row.get("strike", 0)
        if abs(s - strike) < 1:
            key = "call_options" if side == Side.CALL else "put_options"
            alt = "CE" if side == Side.CALL else "PE"
            return row.get(key, {}) or row.get(alt, {})
    return {}


def _trend_follow(
    symbol: str,
    spot: float,
    atm: float,
    chain: list,
    breadth: Breadth,
    profile: MarketProfile,
    regime: Regime,
    orderflow: Orderflow,
    tqs: float,
) -> Optional[SwingSetup]:
    """Ride established trend — hold 2–5 sessions."""
    if regime not in (Regime.TREND_EXPANSION, Regime.VOLATILITY_SPIKE):
        return None
    if tqs < 62 or breadth.score < 58:
        return None

    side = None
    if spot > profile.openingRangeHigh and breadth.bias == "BULLISH" and breadth.aligned:
        side = Side.CALL
    elif spot < profile.openingRangeLow and breadth.bias == "BEARISH" and breadth.aligned:
        side = Side.PUT

    if not side:
        return None

    opt = _get_option(chain, atm, side)
    premium = opt.get("ltp") or opt.get("last_price", 0)
    if not premium_in_band(premium):
        return None

    conf = min(92, 58 + breadth.score * 0.25 + tqs * 0.15 + orderflow.breakoutVelocity * 0.1)
    return SwingSetup(
        symbol=symbol,
        side=side,
        strike=atm,
        premium=premium,
        swingType="trend_follow",
        confidence=conf,
        reason=f"Trend {breadth.bias.lower()} — spot vs opening range, regime {regime.value}",
        metadata={"regime": regime.value, "tqs": tqs, "breadth": breadth.score},
    )


def _pcr_position(
    symbol: str,
    spot: float,
    atm: float,
    chain: list,
    breadth: Breadth,
    regime: Regime,
    tqs: float,
) -> Optional[SwingSetup]:
    """Positional PCR extreme — fade crowd when spot confirms."""
    pcr = compute_pcr(chain)
    side = None
    if pcr > 1.35 and breadth.bias in ("BULLISH", "NEUTRAL") and regime != Regime.CHOP:
        side = Side.CALL
        label = f"High PCR {pcr:.2f} — bullish swing (fear fade)"
    elif pcr < 0.65 and regime != Regime.CHOP:
        side = Side.PUT
        label = f"Low PCR {pcr:.2f} — bearish swing (greed fade)"

    if not side:
        return None

    opt = _get_option(chain, atm, side)
    premium = opt.get("ltp") or opt.get("last_price", 0)
    if not premium_in_band(premium):
        return None

    conf = min(88, 55 + abs(pcr - 1.0) * 25 + tqs * 0.12)
    if conf < 65:
        return None

    return SwingSetup(
        symbol=symbol,
        side=side,
        strike=atm,
        premium=premium,
        swingType="pcr_position",
        confidence=conf,
        reason=label,
        metadata={"pcr": round(pcr, 3)},
    )


def _max_pain_swing(
    symbol: str,
    spot: float,
    atm: float,
    chain: list,
    breadth: Breadth,
    tqs: float,
) -> Optional[SwingSetup]:
    """Multi-day max-pain magnet when spot is far from pin."""
    max_pain = compute_max_pain(chain)
    if not max_pain:
        return None

    dist = max_pain - spot
    if abs(dist) < 80:
        return None

    side = Side.CALL if dist > 0 else Side.PUT
    opt = _get_option(chain, atm, side)
    premium = opt.get("ltp") or opt.get("last_price", 0)
    if not premium_in_band(premium):
        return None

    conf = min(85, 52 + min(abs(dist) / 10, 25) + tqs * 0.1)
    if conf < 65:
        return None

    return SwingSetup(
        symbol=symbol,
        side=side,
        strike=atm,
        premium=premium,
        swingType="max_pain_magnet",
        confidence=conf,
        reason=f"Max pain {max_pain:.0f} — spot {spot:.0f} ({dist:+.0f}pt gap)",
        metadata={"maxPain": max_pain, "gap": dist},
    )


def scan_swing_setups(
    symbol: str,
    spot: float,
    atm: float,
    chain: list,
    orderflow: Orderflow,
    breadth: Breadth,
    profile: MarketProfile,
    regime: Regime,
    tqs: float,
) -> list[SwingSetup]:
    """Return ranked swing setups for a symbol."""
    if not get_settings().swing_trading_enabled:
        return []

    candidates: list[SwingSetup] = []
    for fn in (_trend_follow, _pcr_position, _max_pain_swing):
        try:
            setup = fn(symbol, spot, atm, chain, breadth, profile, regime, orderflow, tqs)
            if setup and setup.confidence >= 65:
                candidates.append(setup)
        except Exception:
            continue

    candidates.sort(key=lambda s: s.confidence, reverse=True)
    seen: set[tuple] = set()
    unique: list[SwingSetup] = []
    for c in candidates:
        key = (c.side, c.strike, c.swingType)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[:3]


def setup_to_dict(setup: SwingSetup) -> dict[str, Any]:
    settings = get_settings()
    return {
        "symbol": setup.symbol,
        "side": setup.side.value,
        "strike": setup.strike,
        "premium": setup.premium,
        "swingType": setup.swingType,
        "confidence": setup.confidence,
        "reason": setup.reason,
        "targetPct": settings.swing_target_pct,
        "stopPct": settings.swing_stop_pct,
        "maxHoldDays": settings.swing_max_hold_days,
        "tradeable": setup.confidence >= 68,
        "metadata": setup.metadata,
    }
