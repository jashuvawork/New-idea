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


def moneyness_allows(
    side: Side | str,
    strike: float,
    snap: SymbolSnapshot,
    *,
    mode: str = "scalp",
    candidate_score: float = 0.0,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    state: Any = None,
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
        from app.engines.expiry_day_guards import expiry_pm_itm_quick_active

        pm_modes = ("quick_sideways", "slow_bounce")
        if not (mode in pm_modes and expiry_pm_itm_quick_active(snap, state, snapshots)):
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
    """
    settings = get_settings()
    if not settings.moneyness_selection_enabled or not snap.heatmap:
        return []

    spot = float(snap.spot or 0)
    if spot <= 0:
        return []

    atm = float(snap.atmStrike or atm_strike(spot, symbol))
    preferred = resolve_preferred_moneyness("scalp", snap, snapshots=snapshots)
    if preferred == "ATM":
        return []

    out: list[dict[str, Any]] = []
    bias = (snap.breadth.bias or "NEUTRAL").upper()

    for row in snap.heatmap:
        for side, ltp, ikey in (
            (Side.CALL, row.callLtp, row.callInstrumentKey),
            (Side.PUT, row.putLtp, row.putInstrumentKey),
        ):
            if not premium_in_band(ltp):
                continue
            money = classify_moneyness(side, row.strike, spot, symbol=symbol, atm=atm)
            if money != preferred:
                continue
            depth = _depth_steps(side, row.strike, spot, symbol, atm)
            max_depth = (
                settings.moneyness_max_itm_steps
                if preferred == "ITM"
                else settings.moneyness_max_otm_steps
            )
            if depth > max_depth or depth <= 0:
                continue

            # Side alignment with breadth for ITM defensive legs
            if preferred == "ITM":
                if side == Side.CALL and bias not in ("BULLISH", "NEUTRAL"):
                    continue
                if side == Side.PUT and bias not in ("BEARISH", "NEUTRAL"):
                    continue

            score = 52.0 + row.liquidityScore * 0.15
            out.append({
                "symbol": symbol,
                "side": side,
                "strike": row.strike,
                "premium": float(ltp),
                "moneyness": money,
                "liquidityScore": row.liquidityScore,
                "instrumentKey": ikey,
                "suggestion": SuggestedTrade(
                    id=f"mny-{symbol}-{side.value}-{int(row.strike)}",
                    symbol=symbol,
                    side=side,
                    strike=row.strike,
                    lastPremium=float(ltp),
                    tqs=snap.tradeQualityScore,
                    strategyType=StrategyType.SCALP,
                    confidence=score,
                ),
                "score": score,
            })

    out.sort(key=lambda x: (x["liquidityScore"], x["score"]), reverse=True)
    return out[:4]
