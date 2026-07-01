"""Explosion detector — captures premium velocity moments like NIFTY CE +67% runs."""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.premium_filter import premium_in_band
from app.models.schemas import Side

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Rolling premium history: symbol -> strike_key -> deque of (timestamp, premium, volume)
_history: dict[str, dict[str, deque]] = {}
MAX_HISTORY = 40  # ~2 min at 3s poll


@dataclass
class ExplosionEvent:
    symbol: str
    side: Side
    strike: float
    premium: float
    velocity_3s: float  # % change last poll
    velocity_9s: float  # % change last 3 polls
    velocity_15s: float  # % change last 5 polls
    volume_surge: float  # ratio vs prior avg
    explosion_score: float  # 0-100 composite
    tier: str  # WATCH | BUILDING | EXPLODING | ELITE
    reason: str
    daily_move_pct: float = 0.0


def _strike_key(strike: float, side: Side) -> str:
    return f"{side.value}:{strike}"


def _record(symbol: str, strike: float, side: Side, premium: float, volume: float = 0) -> None:
    if not premium or premium <= 0:
        return
    if symbol not in _history:
        _history[symbol] = {}
    key = _strike_key(strike, side)
    if key not in _history[symbol]:
        _history[symbol][key] = deque(maxlen=MAX_HISTORY)
    _history[symbol][key].append((datetime.now(IST), premium, volume))


def _velocity(history: deque, polls_back: int) -> float:
    if len(history) < polls_back + 1:
        return 0.0
    current = history[-1][1]
    prior = history[-(polls_back + 1)][1]
    if not prior or prior <= 0:
        return 0.0
    return ((current - prior) / prior) * 100


def _volume_surge(history: deque) -> float:
    if len(history) < 4:
        return 1.0
    recent_vol = sum(h[2] for h in list(history)[-2:]) / 2
    prior_vol = sum(h[2] for h in list(history)[-6:-2]) / max(1, len(list(history)[-6:-2]))
    if prior_vol <= 0:
        return 1.0 if recent_vol > 0 else 1.0
    return recent_vol / prior_vol


def scan_chain_explosions(
    symbol: str,
    chain: list[dict[str, Any]],
    spot: float,
    atm: float,
) -> list[ExplosionEvent]:
    """
    Scan full chain for premium explosions.
    Matches chart pattern: sudden 3-8% moves in 1-3 min with volume spike.
    """
    events: list[ExplosionEvent] = []
    step = 100
    scan_range = 800 if symbol != "SENSEX" else 1000

    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(strike - atm) > scan_range:
            continue

        for side, key, alt in [
            (Side.CALL, "call_options", "CE"),
            (Side.PUT, "put_options", "PE"),
        ]:
            opt = row.get(key, {}) or row.get(alt, {})
            if not opt:
                continue

            premium = opt.get("ltp") or opt.get("last_price") or 0
            volume = opt.get("volume", 0) or 0
            if not premium_in_band(premium, mode="explosion"):
                continue

            _record(symbol, strike, side, premium, volume)
            key_h = _strike_key(strike, side)
            hist = _history.get(symbol, {}).get(key_h)
            if not hist or len(hist) < 2:
                continue

            v3 = _velocity(hist, 1)
            v9 = _velocity(hist, 3)
            v15 = _velocity(hist, 5)
            vol_surge = _volume_surge(hist)

            # Composite explosion score
            score = (
                min(40, max(0, v3) * 8)
                + min(30, max(0, v9) * 5)
                + min(20, max(0, v15) * 3)
                + min(10, (vol_surge - 1) * 10)
            )

            # Tier classification
            tier = "WATCH"
            if v3 >= 2.0 or v9 >= 3.5:
                tier = "BUILDING"
            if v3 >= 3.5 or v9 >= 5.0 or (v3 >= 2.5 and vol_surge >= 1.8):
                tier = "EXPLODING"
            if v3 >= 5.0 or v9 >= 8.0 or (v3 >= 4.0 and vol_surge >= 2.0):
                tier = "ELITE"

            if tier == "WATCH" and score < 25:
                continue

            # OTM bias during explosions (like 24000 CE rallying hard)
            otm_bonus = 0
            if side == Side.CALL and strike > atm:
                otm_bonus = min(10, (strike - atm) / step * 2)
            elif side == Side.PUT and strike < atm:
                otm_bonus = min(10, (atm - strike) / step * 2)
            score = min(100, score + otm_bonus)

            reason_parts = []
            if v3 >= 2:
                reason_parts.append(f"+{v3:.1f}%/3s")
            if v9 >= 3:
                reason_parts.append(f"+{v9:.1f}%/9s")
            if vol_surge >= 1.5:
                reason_parts.append(f"vol×{vol_surge:.1f}")

            events.append(ExplosionEvent(
                symbol=symbol,
                side=side,
                strike=strike,
                premium=premium,
                velocity_3s=round(v3, 2),
                velocity_9s=round(v9, 2),
                velocity_15s=round(v15, 2),
                volume_surge=round(vol_surge, 2),
                explosion_score=round(score, 1),
                tier=tier,
                reason=" ".join(reason_parts) or "momentum building",
            ))

    events.sort(key=lambda e: ({"ELITE": 4, "EXPLODING": 3, "BUILDING": 2, "WATCH": 1}[e.tier], e.explosion_score), reverse=True)
    return events


def event_to_dict(e: ExplosionEvent) -> dict[str, Any]:
    return {
        "symbol": e.symbol,
        "side": e.side.value,
        "strike": e.strike,
        "premium": e.premium,
        "velocity3s": e.velocity_3s,
        "velocity9s": e.velocity_9s,
        "velocity15s": e.velocity_15s,
        "volumeSurge": e.volume_surge,
        "explosionScore": e.explosion_score,
        "tier": e.tier,
        "reason": e.reason,
        "tradeable": e.tier in ("EXPLODING", "ELITE"),
    }
