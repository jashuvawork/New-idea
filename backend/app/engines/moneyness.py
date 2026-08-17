"""ITM / ATM / OTM strike selection for index options."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.chop_day_guards import is_chop_session
from app.engines.premium_filter import premium_in_band
from app.engines.whipsaw_guards import is_bearish_sideways
from app.models.schemas import Side, SymbolSnapshot, SuggestedTrade, StrategyType

Moneyness = str  # "ITM" | "ATM" | "OTM"


def strike_step(symbol: str) -> float:
    """Listed strike interval per index — NIFTY 50, SENSEX/BANKNIFTY 100 (config-driven)."""
    settings = get_settings()
    sym = symbol.upper()
    if sym == "SENSEX":
        return float(getattr(settings, "sensex_strike_step", 100.0) or 100.0)
    if sym == "BANKNIFTY":
        return float(getattr(settings, "banknifty_strike_step", 100.0) or 100.0)
    if sym == "NIFTY":
        return float(getattr(settings, "nifty_strike_step", 50.0) or 50.0)
    return 50.0


def atm_strike(spot: float, symbol: str) -> float:
    step = strike_step(symbol)
    return round(spot / step) * step


def classify_moneyness(
    side: Side | str,
    strike: float,
    spot: float,
    *,
    symbol: str = "NIFTY",
    atm: Optional[float] = None,
) -> Moneyness:
    """CALL ITM below spot/ATM; PUT ITM above spot/ATM."""
    settings = get_settings()
    ref = atm if atm is not None else atm_strike(spot, symbol)
    tol = float(getattr(settings, "moneyness_atm_tolerance_points", 50.0) or 50.0)
    side_val = side.value if isinstance(side, Side) else str(side).upper()

    if abs(strike - ref) <= tol:
        return "ATM"

    if side_val == "CALL":
        return "ITM" if strike < ref - tol else "OTM"
    return "ITM" if strike > ref + tol else "OTM"


def steps_from_atm(
    strike: float,
    spot: float,
    symbol: str,
    *,
    atm: Optional[float] = None,
) -> int:
    step = strike_step(symbol)
    ref = atm if atm is not None else atm_strike(spot, symbol)
    return int(round((strike - ref) / step))


def signed_steps_from_atm(
    side: Side | str,
    strike: float,
    spot: float,
    symbol: str,
    *,
    atm: Optional[float] = None,
) -> int:
    """
    OTM steps are positive depth; ITM steps are negative.
    CALL OTM = strike above ATM (+1, +2…); PUT OTM = strike below ATM.
    """
    raw = steps_from_atm(strike, spot, symbol, atm=atm)
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    money = classify_moneyness(side_val, strike, spot, symbol=symbol, atm=atm)
    if money == "ATM":
        return 0
    if money == "OTM":
        return abs(raw) if side_val == "CALL" else -abs(raw) if raw < 0 else abs(raw)
    # ITM
    if side_val == "CALL":
        return -abs(raw) if raw < 0 else -abs(raw)
    return abs(raw) if raw > 0 else abs(raw)


def _depth_steps(side: Side | str, strike: float, spot: float, symbol: str, atm: float) -> int:
    """Absolute strike steps away from ATM (0 = ATM)."""
    return abs(steps_from_atm(strike, spot, symbol, atm=atm))


def resolve_preferred_moneyness(
    mode: str,
    snap: SymbolSnapshot,
    *,
    candidate_score: float = 0.0,
    side: Optional[Side | str] = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> Moneyness:
    """
    AUTO picks OTM for explosions, ITM for chop/bearish/high-confidence scalps,
    ATM otherwise.
    """
    settings = get_settings()
    mode_key = (settings.trade_moneyness_mode or "AUTO").upper()
    if mode_key in ("ITM", "OTM", "ATM"):
        return mode_key

    if mode == "explosion":
        return settings.moneyness_explosion_prefer.upper()

    chop = is_chop_session(snapshots or {snap.symbol: snap})
    bearish_side = is_bearish_sideways(snap)
    if candidate_score >= settings.high_confidence_min_score:
        return settings.moneyness_high_conf_prefer.upper()
    if chop or bearish_side:
        return settings.moneyness_scalp_chop_prefer.upper()

    return "ATM"


def _local_base_otm_bypass(
    side: Side | str,
    depth: int,
    snap: SymbolSnapshot,
    *,
    candidate_score: float = 0.0,
    candidate: Any = None,
) -> bool:
    """Shallow OTM CE/PE with confirmed local base — ATM often missing on directional rips."""
    settings = get_settings()
    if not getattr(settings, "moneyness_local_base_otm_bypass_enabled", True):
        return False
    side_v = side.value if isinstance(side, Side) else str(side).upper()
    if side_v not in ("CALL", "PUT"):
        return False
    max_steps = int(getattr(settings, "moneyness_local_base_max_otm_steps", 3) or 3)
    if depth < 1 or depth > max_steps:
        return False
    min_score = float(
        getattr(settings, "moneyness_local_base_otm_min_score", 75.0) or 75.0
    )
    if float(candidate_score or 0) < min_score:
        return False
    from app.engines.local_base_chart_bypass import local_base_structure_active

    alert = getattr(candidate, "alert", None) if candidate is not None else None
    if not isinstance(alert, dict):
        alert = None
    event = (
        getattr(candidate, "explosion_event", None) if candidate is not None else None
    )
    return local_base_structure_active(side_v, snap, event=event, alert=alert)


# Backward-compatible alias.
_local_base_call_otm_bypass = _local_base_otm_bypass


def strict_first_lift_shallow_otm_allows(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
    *,
    alert: Optional[dict[str, Any]] = None,
    candidate: Any = None,
) -> bool:
    """Allow only fully confirmed first lifts one listed step outside ATM."""
    settings = get_settings()
    if not bool(getattr(settings, "first_lift_shallow_otm_entry_enabled", True)):
        return False
    spot = float(snap.spot or 0)
    atm = float(snap.atmStrike or (atm_strike(spot, snap.symbol) if spot > 0 else 0))
    if spot <= 0 or atm <= 0:
        return False
    if classify_moneyness(side, strike, spot, symbol=snap.symbol, atm=atm) != "OTM":
        return False
    step = strike_step(snap.symbol)
    tolerance = float(
        getattr(settings, "moneyness_atm_tolerance_points", step) or step
    )
    max_steps = int(
        getattr(settings, "first_lift_shallow_otm_max_steps", 1) or 1
    )
    if abs(float(strike) - atm) > tolerance + step * max(0, max_steps):
        return False

    row = alert
    if row is None and candidate is not None:
        candidate_alert = getattr(candidate, "alert", None)
        row = candidate_alert if isinstance(candidate_alert, dict) else None
    from app.engines.ict_breakout_monitor import first_lift_entry_ready

    return first_lift_entry_ready(snap=snap, alert=row)


def moneyness_allows(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
    *,
    mode: str = "scalp",
    candidate_score: float = 0.0,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    state: Any = None,
    candidate: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = get_settings()
    if not settings.moneyness_selection_enabled:
        return True, "ok", {}

    spot = float(snap.spot or 0)
    if spot <= 0:
        return True, "ok", {}

    symbol = snap.symbol.upper()
    atm = float(snap.atmStrike or atm_strike(spot, symbol))
    money = classify_moneyness(side, strike, spot, symbol=symbol, atm=atm)
    depth = _depth_steps(side, strike, spot, symbol, atm)
    preferred = resolve_preferred_moneyness(
        mode, snap, candidate_score=candidate_score, side=side, snapshots=snapshots,
    )

    meta = {
        "moneyness": money,
        "preferredMoneyness": preferred,
        "strikeStepsFromAtm": depth,
        "atmStrike": atm,
    }

    mode_key = (settings.trade_moneyness_mode or "AUTO").upper()
    if mode_key in ("ITM", "OTM", "ATM") and money != mode_key:
        return False, f"moneyness_mode_{mode_key.lower()}_required", meta

    strict_shallow_first_lift = (
        mode == "explosion"
        and money == "OTM"
        and strict_first_lift_shallow_otm_allows(
            side, strike, snap, candidate=candidate,
        )
    )
    if strict_shallow_first_lift:
        meta["strictFirstLiftShallowOtm"] = True

    # Explosion ATM+ITM only — drop OTM entirely so near-base ATM/ITM can win
    # radar (Aug5 deep-OTM 24050 PE <₹18 drowned the 24500 base).
    if (
        mode == "explosion"
        and money == "OTM"
        and bool(getattr(settings, "moneyness_explosion_atm_itm_only", True))
        and not strict_shallow_first_lift
    ):
        return False, "moneyness_explosion_atm_itm_only", meta

    # Explosion ATM-first: OTM is a hard miss, not a soft rank penalty.
    if (
        mode == "explosion"
        and money == "OTM"
        and preferred == "ATM"
        and bool(getattr(settings, "moneyness_explosion_block_otm", True))
        and not strict_shallow_first_lift
    ):
        if _local_base_otm_bypass(
            side, depth, snap, candidate_score=candidate_score, candidate=candidate,
        ):
            meta["localBaseOtmBypass"] = True
        else:
            return False, "moneyness_explosion_atm_only_otm_blocked", meta

    if money == "OTM" and depth > settings.moneyness_max_otm_steps:
        expiry_otm_ok = False
        if mode == "explosion":
            from app.engines.expiry_day_guards import is_symbol_expiry_day

            max_depth = settings.moneyness_max_otm_steps
            if is_symbol_expiry_day(snap):
                max_depth = max(max_depth, int(getattr(settings, "expiry_explosion_max_otm_steps", 4) or 4))
            if depth <= max_depth and candidate_score >= settings.aggressive_min_explosion_score:
                expiry_otm_ok = True
        if not expiry_otm_ok and (
            mode != "explosion" or candidate_score < settings.bearish_sideways_explosion_min_score
        ):
            return False, f"moneyness_otm_too_deep_{depth}", meta

    if money == "ITM" and depth > settings.moneyness_max_itm_steps:
        from app.engines.expiry_day_guards import (
            expiry_itm_max_steps,
            expiry_itm_monitor_active,
            expiry_pm_itm_quick_active,
        )

        max_itm = int(settings.moneyness_max_itm_steps)
        if expiry_itm_monitor_active(snap):
            max_itm = max(max_itm, expiry_itm_max_steps())
            meta["expiryItmMonitor"] = True
            meta["expiryMaxItmSteps"] = max_itm
        pm_modes = ("quick_sideways", "slow_bounce")
        if depth > max_itm and not (
            mode in pm_modes and expiry_pm_itm_quick_active(snap, state, snapshots)
        ):
            return False, f"moneyness_itm_too_deep_{depth}", meta

    if settings.trade_moneyness_mode.upper() == "AUTO" and preferred != money:
        # Soft mismatch — rank penalty handles preference; hard-block only deep wrong-way OTM in chop
        if (
            preferred == "ITM"
            and money == "OTM"
            and (is_bearish_sideways(snap) or is_chop_session(snapshots or {symbol: snap}))
            and mode == "scalp"
        ):
            return False, f"moneyness_chop_requires_{preferred.lower()}", meta

    return True, "ok", meta


def moneyness_rank_adjustment(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
    *,
    mode: str = "scalp",
    candidate_score: float = 0.0,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> float:
    settings = get_settings()
    if not settings.moneyness_selection_enabled:
        return 0.0

    spot = float(snap.spot or 0)
    if spot <= 0:
        return 0.0

    atm = float(snap.atmStrike or atm_strike(spot, snap.symbol))
    money = classify_moneyness(side, strike, spot, symbol=snap.symbol, atm=atm)
    preferred = resolve_preferred_moneyness(
        mode, snap, candidate_score=candidate_score, side=side, snapshots=snapshots,
    )
    bonus = settings.moneyness_rank_bonus
    penalty = settings.moneyness_mismatch_penalty

    if money == preferred:
        return bonus
    if money == "ATM" and preferred in ("ITM", "OTM"):
        return bonus * 0.35
    if preferred == "ITM" and money == "OTM":
        return -penalty
    if preferred == "OTM" and money == "ITM" and mode == "explosion":
        return -penalty * 0.5
    return -penalty * 0.35


def heatmap_moneyness_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> list[dict[str, Any]]:
    """
    Build supplemental ITM/OTM scalp legs from the option heatmap when AUTO mode
    needs non-ATM strikes (e.g. ITM puts in bearish chop).

    On expiry, monitor most ITM CE and PE (both sides) so ATM-cluster fixation
    does not miss deep-ITM rips.
    """
    settings = get_settings()
    if not settings.moneyness_selection_enabled or not snap.heatmap:
        return []

    spot = float(snap.spot or 0)
    if spot <= 0:
        return []

    from app.engines.expiry_day_guards import (
        expiry_itm_max_steps,
        expiry_itm_monitor_active,
    )

    atm = float(snap.atmStrike or atm_strike(spot, symbol))
    expiry_itm = expiry_itm_monitor_active(snap)
    preferred = resolve_preferred_moneyness("scalp", snap, snapshots=snapshots)
    if expiry_itm:
        preferred = "ITM"
    if preferred == "ATM":
        return []

    out: list[dict[str, Any]] = []
    bias = (snap.breadth.bias or "NEUTRAL").upper()
    both_sides = expiry_itm and bool(getattr(settings, "expiry_itm_both_sides", True))
    max_depth = (
        expiry_itm_max_steps()
        if preferred == "ITM" and expiry_itm
        else (
            settings.moneyness_max_itm_steps
            if preferred == "ITM"
            else settings.moneyness_max_otm_steps
        )
    )
    limit = (
        int(getattr(settings, "expiry_itm_candidate_limit", 12) or 12)
        if expiry_itm
        else 4
    )

    for row in snap.heatmap:
        for side, ltp, ikey in (
            (Side.CALL, row.callLtp, row.callInstrumentKey),
            (Side.PUT, row.putLtp, row.putInstrumentKey),
        ):
            prem = float(ltp or 0)
            if expiry_itm:
                # ITM premiums run higher on expiry — use near-expiry ceiling.
                max_prem = float(
                    getattr(settings, "expiry_near_expiry_premium_max_inr", 300)
                    or getattr(settings, "expiry_pm_itm_premium_max_inr", 280)
                    or 280
                )
                min_prem = float(getattr(settings, "min_option_premium_inr", 25) or 25)
                if prem < min_prem or prem > max_prem:
                    continue
            elif not premium_in_band(ltp):
                continue
            money = classify_moneyness(side, row.strike, spot, symbol=symbol, atm=atm)
            if money != preferred:
                continue
            depth = _depth_steps(side, row.strike, spot, symbol, atm)
            if depth > max_depth or depth <= 0:
                continue

            # Side alignment with breadth for ITM defensive legs — skipped on
            # expiry so both CE and PE ITM stay monitored regardless of OI bias.
            if preferred == "ITM" and not both_sides:
                if side == Side.CALL and bias not in ("BULLISH", "NEUTRAL"):
                    continue
                if side == Side.PUT and bias not in ("BEARISH", "NEUTRAL"):
                    continue

            score = 52.0 + row.liquidityScore * 0.15
            if expiry_itm:
                # Prefer nearer ITM (still allow deep) so selection stays liquid.
                score += max(0.0, (max_depth - depth + 1) * 1.5)
            out.append({
                "symbol": symbol,
                "side": side,
                "strike": row.strike,
                "premium": prem,
                "moneyness": money,
                "liquidityScore": row.liquidityScore,
                "instrumentKey": ikey,
                "expiryItmMonitor": expiry_itm,
                "suggestion": SuggestedTrade(
                    id=f"mny-{symbol}-{side.value}-{int(row.strike)}",
                    symbol=symbol,
                    side=side,
                    strike=row.strike,
                    lastPremium=prem,
                    tqs=snap.tradeQualityScore,
                    strategyType=StrategyType.SCALP,
                    confidence=score,
                ),
                "score": score,
            })

    out.sort(key=lambda x: (x["liquidityScore"], x["score"]), reverse=True)
    return out[:limit]
