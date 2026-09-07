"""Rally capture — avoid wrong-side opens, late OTM chase, and exhaustion entries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.engines.moneyness import steps_from_atm, strike_step
from app.models.schemas import Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

# symbol:side:strike -> when exhaustion last blocked (for timed reset)
_exhaustion_marked_at: dict[str, datetime] = {}


def _exhaustion_key(event: ExplosionEvent) -> str:
    side = _side_val(event.side)
    return f"{event.symbol.upper()}:{side}:{event.strike:.0f}"


def _in_consolidation(event: ExplosionEvent) -> bool:
    settings = get_settings()
    return (
        event.velocity_3s <= settings.explosion_exhaustion_consolidation_v3_max
        and event.velocity_9s <= settings.explosion_exhaustion_consolidation_v9_max
    )


def explosion_exhausted(event: ExplosionEvent) -> tuple[bool, str]:
    """Block late chase — big 15s move already in, 3s fading (buying the top)."""
    settings = get_settings()
    key = _exhaustion_key(event)

    open_move = float(getattr(event, "daily_move_pct", 0) or 0)
    open_min = float(getattr(settings, "open_premium_min_move_pct", 25.0) or 25.0)
    if open_move >= open_min and event.velocity_3s >= 1.5:
        _exhaustion_marked_at.pop(key, None)
        return False, "ok"

    if settings.explosion_exhaustion_consolidation_reset_enabled:
        if _in_consolidation(event):
            _exhaustion_marked_at.pop(key, None)
            return False, "ok"

        marked = _exhaustion_marked_at.get(key)
        if marked is not None:
            if marked.tzinfo is None:
                marked = marked.replace(tzinfo=IST)
            elapsed_min = (datetime.now(IST) - marked.astimezone(IST)).total_seconds() / 60.0
            if elapsed_min >= settings.explosion_exhaustion_reset_minutes and _in_consolidation(event):
                _exhaustion_marked_at.pop(key, None)
                return False, "ok"

    threshold = settings.explosion_exhaustion_v15_pct
    if event.velocity_15s < threshold:
        _exhaustion_marked_at.pop(key, None)
        return False, "ok"
    if event.velocity_3s >= max(1.5, event.velocity_9s * 0.45):
        _exhaustion_marked_at.pop(key, None)
        return False, "ok"

    _exhaustion_marked_at[key] = datetime.now(IST)
    return True, f"explosion_exhausted_v15_{event.velocity_15s:.1f}"


def index_pin_blocks_put_explosion(event: ExplosionEvent, snap: SymbolSnapshot) -> tuple[bool, str]:
    """Block PE fades when index pins at day high with bullish stock breadth."""
    settings = get_settings()
    if not settings.index_pin_put_block_enabled:
        return False, "ok"
    if _side_val(event.side) != "PUT":
        return False, "ok"

    hm = snap.constituentHeatmap
    stock_pct = float(hm.breadthPct) if hm and hm.dataAvailable else float(snap.breadth.stockScore or 0)
    if stock_pct < settings.index_pin_min_stock_breadth_pct:
        return False, "ok"

    chart = snap.spotChart
    profile = snap.marketProfile
    if not chart or chart.spot <= 0:
        return False, "ok"

    or_high = profile.openingRangeHigh or profile.vah or 0
    if or_high <= 0:
        return False, "ok"

    pinning = chart.spot >= or_high * 0.9995
    if not pinning:
        return False, "ok"

    return True, "put_blocked_index_pin_bullish_stocks"


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def breadth_blocks_explosion_side(
    side: Side | str,
    breadth_bias: str,
    tier: str,
    *,
    event: Optional[ExplosionEvent] = None,
    snap: Optional[SymbolSnapshot] = None,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """No PUT into BULLISH breadth / no CALL into BEARISH unless ELITE."""
    from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

    if event is not None and qualifies_for_vertical_rip_bypass(event):
        return False, "ok"

    if snap is not None:
        from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

        if local_base_overrides_side_bias(side, snap, event=event, alert=alert):
            return False, "ok"

    settings = get_settings()
    if not settings.explosion_breadth_alignment_enabled:
        return False, "ok"
    bias = (breadth_bias or "NEUTRAL").upper()
    side_v = _side_val(side)
    if bias == "BULLISH" and side_v == "PUT":
        return True, "explosion_put_vs_bullish_breadth"
    if bias == "BEARISH" and side_v == "CALL":
        return True, "explosion_call_vs_bearish_breadth"
    return False, "ok"


def chart_blocks_explosion_side(
    side: Side | str,
    chart: Optional[SpotChart],
    tier: str,
    *,
    event: Optional[ExplosionEvent] = None,
    breadth_bias: str = "NEUTRAL",
    snap: Optional[SymbolSnapshot] = None,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Block counter-trend explosion legs when index chart has clear bias."""
    from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

    if event is not None and qualifies_for_vertical_rip_bypass(event):
        return False, "ok"

    if event is not None and chart is not None:
        from app.engines.morning_premium_capture import premium_led_explosion_bypass

        if premium_led_explosion_bypass(event, chart, breadth_bias, snap=snap):
            return False, "ok"

    if snap is not None:
        from app.engines.local_base_chart_bypass import local_base_ichimoku_chart_bypass

        if local_base_ichimoku_chart_bypass(
            side, snap, event=event, alert=alert,
        ):
            return False, "ok"

    if chart is None:
        return False, "ok"
    direction = (chart.direction or "NEUTRAL").upper()
    side_v = _side_val(side)
    if direction == "NEUTRAL":
        return False, "ok"
    if direction == "BULLISH" and side_v == "PUT":
        return True, "explosion_put_vs_bullish_chart"
    if direction == "BEARISH" and side_v == "CALL":
        return True, "explosion_call_vs_bearish_chart"
    return False, "ok"


def dominant_explosion_alert(snap: SymbolSnapshot) -> Optional[dict[str, Any]]:
    settings = get_settings()
    dom_min = float(getattr(settings, "all_day_explosion_dominant_min_score", 40.0) or 40.0)
    session_move_min = float(getattr(settings, "all_day_explosion_session_move_min_pct", 40.0) or 40.0)
    alerts = []
    for a in snap.explosionAlerts or []:
        if not a.get("tradeable") and a.get("tier") not in ("BUILDING", "EXPLODING", "ELITE"):
            continue
        tier = str(a.get("tier") or "")
        score = float(a.get("explosionScore") or 0)
        daily_move = float(a.get("dailyMovePct") or a.get("openPremiumMove") or 0)
        if tier in ("EXPLODING", "ELITE"):
            alerts.append(a)
        elif tier == "BUILDING" and (
            score >= dom_min
            or daily_move >= session_move_min
        ):
            alerts.append(a)
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


def near_strike_explosion_rank_adjustment(
    event: ExplosionEvent, snap: SymbolSnapshot,
) -> float:
    """Prefer ATM and 1-step OTM (near spot) over deep ITM explosion legs."""
    settings = get_settings()
    if not bool(getattr(settings, "near_strike_explosion_rank_enabled", True)):
        return 0.0
    spot = float(snap.spot or 0)
    if spot <= 0:
        return 0.0
    atm = float(snap.atmStrike or 0) or spot
    from app.engines.moneyness import _depth_steps, classify_moneyness

    money = classify_moneyness(
        event.side, event.strike, spot, symbol=event.symbol, atm=atm,
    )
    depth = _depth_steps(event.side, event.strike, spot, event.symbol, atm)
    near_bonus = float(
        getattr(settings, "near_strike_explosion_rank_bonus", 12.0) or 12.0
    )
    deep_pen = float(
        getattr(settings, "deep_itm_explosion_rank_penalty", 15.0) or 15.0
    )
    if depth <= 1 and money in ("ATM", "OTM"):
        return near_bonus
    if money == "ITM" and depth >= 2:
        return -deep_pen
    return 0.0


_NEAR_STRIKE_ARMED_MOMENTS = frozenset(
    {
        "armed_base_launch",
        "v_rip_session_low",
        "v_rip_session_high",
        "first_lift_local_base",
    }
)

_GRADE_PRIORITY = {"REJECT": 0, "C": 1, "B": 2, "A": 3, "S": 4}


def _grade_meets_min(grade: str, min_grade: str) -> bool:
    return _GRADE_PRIORITY.get(str(grade or "").upper(), 0) >= _GRADE_PRIORITY.get(
        str(min_grade or "").upper(), 0
    )


def infer_alert_causal_grade(
    alert: Optional[dict[str, Any]],
    *,
    ranking: Optional[dict[str, Any]] = None,
) -> str:
    """Infer causal grade from alert evidence when rank_entry_candidate has not run yet."""
    if not isinstance(alert, dict):
        return ""
    stamped = str(
        (ranking or {}).get("grade")
        or alert.get("causalGrade")
        or alert.get("rankGrade")
        or ""
    ).upper()
    if stamped:
        return stamped

    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return ""
    explosion_score = float(alert.get("explosionScore") or alert.get("score") or 0)
    local = float(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("offLowMovePct")
        or 0
    )
    armed = bool(
        alert.get("ictArmedBaseLaunch")
        or alert.get("armedBaseLaunch")
        or str(alert.get("momentType") or "") in _NEAR_STRIKE_ARMED_MOMENTS
    )
    orderflow = bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or alert.get("orderflowPositive")
        or float(alert.get("volumeSurge") or 0) >= 1.2
        or float(alert.get("flatVerticalQuality") or 0) >= 50.0
    )
    v3 = float(alert.get("velocity3s") or 0)
    v9 = float(alert.get("velocity9s") or 0)
    steps = float(alert.get("strikeStepsFromAtm") or 0)
    near_strike = 0 < steps <= 2 and str(alert.get("moneyness") or "").upper() != "ITM"
    armed_top_local = armed and near_strike and local <= 15.0
    if (
        tier in ("ELITE", "EXPLODING")
        and armed_top_local
        and orderflow
        and local <= 40.0
        and (v3 >= 1.5 or v9 >= 1.5 or explosion_score >= 90.0)
    ):
        return "S"
    if (
        armed
        and tier in ("ELITE", "EXPLODING")
        and explosion_score >= 70.0
        and 2.0 <= local <= 25.0
        and orderflow
    ):
        return "A"
    if explosion_score >= 60.0:
        return "B"
    if explosion_score >= 40.0:
        return "C"
    return ""


def _armed_pad_moment_active(alert: dict[str, Any]) -> bool:
    moment = str(alert.get("momentType") or "")
    return bool(
        alert.get("ictArmedBaseLaunch")
        or alert.get("armedBaseLaunch")
        or moment in _NEAR_STRIKE_ARMED_MOMENTS
    )


def _armed_pad_orderflow_active(alert: dict[str, Any]) -> bool:
    return bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or alert.get("orderflowConfirmed")
        or alert.get("optionCvdBuying")
        or float(alert.get("volumeSurge") or 0) >= 1.2
        or float(alert.get("flatVerticalQuality") or 0) >= 50.0
    )


def _near_miss_otm_allowed(
    alert: dict[str, Any],
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
) -> bool:
    if snap is None:
        return True
    side = str(alert.get("side") or "").upper()
    strike = float(alert.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if side not in ("CALL", "PUT") or strike <= 0 or spot <= 0:
        return True
    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side

    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or alert.get("symbol") or ""),
        atm=atm if atm > 0 else None,
    )
    if money in ("ATM", "ITM"):
        return True
    from app.engines.early_radar_pad_capture import (
        building_coil_pad_moneyness_ok,
        otm_reversal_entry_allowed,
    )

    s = settings or get_settings()
    if building_coil_pad_moneyness_ok(alert, snap, s):
        return True
    return otm_reversal_entry_allowed(alert, snap)


def armed_base_pad_near_miss_waive(
    alert: Optional[dict[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    settings: Any = None,
) -> bool:
    """High-score armed ELITE at local pad — waive quality/structure near-miss lag."""
    s = settings or get_settings()
    if not bool(getattr(s, "armed_base_pad_near_miss_waive_enabled", True)):
        return False
    if not isinstance(alert, dict):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if not _armed_pad_moment_active(alert):
        return False
    if not _armed_pad_orderflow_active(alert):
        return False
    if not _near_miss_otm_allowed(alert, snap, settings=s):
        return False
    local = float(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("offLowMovePct")
        or 0
    )
    max_local = float(
        getattr(s, "armed_base_pad_near_miss_max_local_pct", 15.0) or 15.0
    )
    if local <= 0 or local > max_local + 1e-6:
        return False
    min_score = float(
        getattr(s, "armed_base_pad_near_miss_min_explosion_score", 80.0) or 80.0
    )
    score = float(alert.get("explosionScore") or alert.get("score") or 0)
    if score < min_score - 1e-6:
        return False
    if str(alert.get("moneyness") or "").upper() == "ITM":
        steps = float(alert.get("strikeStepsFromAtm") or 0)
        max_steps = int(
            getattr(s, "near_strike_armed_near_miss_max_steps", 2) or 2
        )
        if steps > max_steps + 1e-6:
            return False
    return True


def explosion_near_miss_waive(
    alert: Optional[dict[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    ranking: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    """Unified near-miss waiver for explosion first-lift / quality / tier lag."""
    rr = str(readiness_reason or "").lower()
    if rr.startswith(
        (
            "first_lift_live_velocity_negative",
            "mid_rip_armed_coil_rejected",
            "first_lift_base_move_outside",
        )
    ):
        return False
    if near_strike_armed_near_miss_waive(
        alert, snap=snap, ranking=ranking, settings=settings,
    ):
        return True
    return armed_base_pad_near_miss_waive(alert, snap=snap, settings=settings)


def near_strike_armed_near_miss_waive(
    alert: Optional[dict[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    ranking: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> bool:
    """Grade-S near-strike armed pad — waive first_lift_structure near-miss at base."""
    s = settings or get_settings()
    if not bool(getattr(s, "near_strike_armed_near_miss_waive_enabled", True)):
        return False
    if not isinstance(alert, dict):
        return False
    grade = infer_alert_causal_grade(alert, ranking=ranking)
    min_grade = str(
        getattr(s, "near_strike_armed_near_miss_min_grade", "S") or "S"
    ).upper()
    if not _grade_meets_min(grade, min_grade):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    max_steps = int(getattr(s, "near_strike_armed_near_miss_max_steps", 2) or 2)
    steps = float(alert.get("strikeStepsFromAtm") or 0)
    if steps <= 0 or steps > max_steps + 1e-6:
        return False
    if str(alert.get("moneyness") or "").upper() == "ITM":
        return False
    if not _near_miss_otm_allowed(alert, snap, settings=s):
        return False
    if not _armed_pad_moment_active(alert):
        return False
    local = float(
        alert.get("localBaseMovePct")
        or alert.get("ictBaseRelativeMovePct")
        or alert.get("offLowMovePct")
        or 0
    )
    max_local = float(
        getattr(s, "near_strike_armed_near_miss_max_local_pct", 15.0) or 15.0
    )
    return local <= max_local + 1e-6
