"""Rally capture — avoid wrong-side opens, late OTM chase, and exhaustion entries."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.engines.moneyness import steps_from_atm, strike_step
from app.models.schemas import Side, SpotChart, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def breadth_blocks_explosion_side(side: Side | str, breadth_bias: str, tier: str) -> tuple[bool, str]:
    """No PUT into BULLISH breadth / no CALL into BEARISH unless ELITE."""
    settings = get_settings()
    if not settings.explosion_breadth_alignment_enabled:
        return False, "ok"
    bias = (breadth_bias or "NEUTRAL").upper()
    side_v = _side_val(side)
    if tier == "ELITE":
        return False, "ok"
    if bias == "BULLISH" and side_v == "PUT":
        return True, "explosion_put_vs_bullish_breadth"
    if bias == "BEARISH" and side_v == "CALL":
        return True, "explosion_call_vs_bearish_breadth"
    return False, "ok"


def chart_blocks_explosion_side(side: Side | str, chart: Optional[SpotChart], tier: str) -> tuple[bool, str]:
    """Block counter-trend explosion legs when index chart has clear bias."""
    if chart is None:
        return False, "ok"
    direction = (chart.direction or "NEUTRAL").upper()
    side_v = _side_val(side)
    if direction == "NEUTRAL":
        return False, "ok"
    if tier == "ELITE":
        return False, "ok"
    if direction == "BULLISH" and side_v == "PUT":
        return True, "explosion_put_vs_bullish_chart"
    if direction == "BEARISH" and side_v == "CALL":
        return True, "explosion_call_vs_bearish_chart"
    return False, "ok"


def explosion_exhausted(event: ExplosionEvent) -> tuple[bool, str]:
    """Block late chase — big 15s move already in, 3s fading (buying the top)."""
    settings = get_settings()
    threshold = settings.explosion_exhaustion_v15_pct
    if event.velocity_15s < threshold:
        return False, "ok"
    if event.velocity_3s >= max(1.5, event.velocity_9s * 0.45):
        return False, "ok"
    return True, f"explosion_exhausted_v15_{event.velocity_15s:.1f}"


def dominant_explosion_alert(snap: SymbolSnapshot) -> Optional[dict[str, Any]]:
    alerts = [
        a for a in (snap.explosionAlerts or [])
        if a.get("tradeable") and a.get("tier") in ("EXPLODING", "ELITE")
    ]
    if not alerts:
        return None
    return max(alerts, key=lambda a: float(a.get("explosionScore") or 0))


def cross_side_chase_blocked(event: ExplosionEvent, snap: SymbolSnapshot) -> tuple[bool, str]:
    """When one side is clearly exploding, do not flip to the opposite leg."""
    settings = get_settings()
    if not settings.explosion_single_side_per_symbol:
        return False, "ok"
    dom = dominant_explosion_alert(snap)
    if not dom:
        return False, "ok"
    dom_score = float(dom.get("explosionScore") or 0)
    if dom_score < settings.explosion_dominant_side_min_score:
        return False, "ok"
    dom_side = _side_val(dom.get("side", ""))
    if dom_side and dom_side != _side_val(event.side):
        return True, f"explosion_dominant_{dom_side.lower()}_blocks_{_side_val(event.side).lower()}"
    return False, "ok"


def runner_strike_rank_bonus(event: ExplosionEvent, snap: SymbolSnapshot) -> float:
    """Prefer the live runner strike (e.g. 77300 CE) over far OTM lottery tickets."""
    runner = snap.explosiveRunner
    if not runner or not runner.side or not runner.strike:
        return 0.0
    if _side_val(runner.side) != _side_val(event.side):
        return -8.0
    step = strike_step(event.symbol)
    dist = abs(event.strike - float(runner.strike)) / step
    if dist <= 0.5:
        return 18.0
    if dist <= 1.0:
        return 8.0
    if dist >= 3.0:
        return -15.0
    if dist >= 2.0:
        return -8.0
    return 0.0


def atm_proximity_rank_bonus(event: ExplosionEvent, snap: SymbolSnapshot) -> float:
    spot = float(snap.spot or 0)
    if spot <= 0:
        return 0.0
    atm = float(snap.atmStrike or 0) or spot
    steps = abs(steps_from_atm(event.strike, spot, event.symbol, atm=atm))
    if steps <= 1:
        return 10.0
    if steps >= 4:
        return -12.0
    if steps >= 3:
        return -6.0
    return 0.0
