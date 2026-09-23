"""Symbol-aware option premium bands — SENSEX/BANKNIFTY LTPs run ~3× NIFTY near-base."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings


def _symbol_u(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def symbol_premium_scale(symbol: Any, settings: Any | None = None) -> float:
    """Multiplier vs NIFTY defaults (SENSEX/BANKNIFTY ≈ 3×)."""
    s = settings or get_settings()
    sym = _symbol_u(symbol)
    if sym == "SENSEX":
        return max(
            1.0,
            float(getattr(s, "symbol_premium_scale_sensex", 3.0) or 3.0),
        )
    if sym == "BANKNIFTY":
        return max(
            1.0,
            float(getattr(s, "symbol_premium_scale_banknifty", 3.0) or 3.0),
        )
    return max(
        1.0,
        float(getattr(s, "symbol_premium_scale_nifty", 1.0) or 1.0),
    )


def _scaled_setting(
    settings: Any,
    symbol: Any,
    setting_name: str,
    default: float,
) -> float:
    base = float(getattr(settings, setting_name, default) or default)
    return base * symbol_premium_scale(symbol, settings)


def best_trade_cheap_entry_max_premium(symbol: Any, settings: Any | None = None) -> float:
    s = settings or get_settings()
    return _scaled_setting(
        s, symbol, "best_trade_cheap_entry_max_premium_inr", 85.0,
    )


def best_trade_cheap_base_premium_band(
    symbol: Any,
    settings: Any | None = None,
) -> tuple[float, float]:
    s = settings or get_settings()
    lo = _scaled_setting(s, symbol, "best_trade_cheap_base_min_premium_inr", 18.0)
    hi = _scaled_setting(s, symbol, "best_trade_cheap_base_max_premium_inr", 80.0)
    return lo, hi


def best_trade_deep_itm_min_premium(symbol: Any, settings: Any | None = None) -> float:
    s = settings or get_settings()
    return _scaled_setting(s, symbol, "best_trade_deep_itm_min_premium_inr", 120.0)


def best_trade_deep_chase_min_premium(symbol: Any, settings: Any | None = None) -> float:
    s = settings or get_settings()
    return _scaled_setting(s, symbol, "best_trade_deep_chase_min_premium_inr", 120.0)


_PAD_MAX_SETTINGS_NO_SYMBOL_SCALE = frozenset({
    # Already widened for SENSEX ITM afternoon — do not multiply again.
    "slow_grind_consolidation_base_max_premium_inr",
    # Armed-trough / sudden-lift cap stays ₹220; ITM SENSEX routes via consolidation.
    "slow_grind_sudden_lift_max_premium_inr",
})


def local_base_pad_premium_band(
    symbol: Any,
    settings: Any | None = None,
    *,
    max_premium_setting: str = "local_base_pad_capture_max_premium_inr",
    max_default: float = 220.0,
) -> tuple[float, float]:
    s = settings or get_settings()
    min_prem = _scaled_setting(
        s, symbol, "local_base_pad_capture_min_premium_inr", 18.0,
    )
    base_max = float(getattr(s, max_premium_setting, max_default) or max_default)
    if max_premium_setting in _PAD_MAX_SETTINGS_NO_SYMBOL_SCALE:
        max_prem = base_max
    else:
        max_prem = base_max * symbol_premium_scale(symbol, s)
    return min_prem, max_prem


def premium_in_symbol_cheap_base_band(
    premium: float,
    symbol: Any,
    settings: Any | None = None,
) -> bool:
    if premium <= 0:
        return False
    lo, hi = best_trade_cheap_base_premium_band(symbol, settings)
    return lo <= premium <= hi + 1e-6


def premium_above_nifty_cheap_entry_band(
    premium: float,
    symbol: Any,
    settings: Any | None = None,
) -> bool:
    """True when LTP is above unscaled NIFTY cheap ceiling but normal for this symbol."""
    s = settings or get_settings()
    nifty_ceiling = float(
        getattr(s, "best_trade_cheap_entry_max_premium_inr", 85.0) or 85.0
    )
    sym_max = best_trade_cheap_entry_max_premium(symbol, s)
    if premium <= nifty_ceiling + 1e-6:
        return False
    return premium <= sym_max + 1e-6


def _structural_base_evidence(evidence: Mapping[str, Any]) -> bool:
    local = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
        float(evidence.get("offLowMovePct") or 0),
        float(evidence.get("offHighMovePct") or 0),
    )
    from app.config import get_settings

    max_local = float(
        getattr(
            get_settings(),
            "large_ltp_base_cold_velocity_max_local_pct",
            22.0,
        )
        or 22.0
    )
    if local > max_local + 1e-6:
        return False
    return bool(
        evidence.get("ictBaseArmed")
        or evidence.get("armedBaseLaunch")
        or evidence.get("ictFlatThenVertical")
        or evidence.get("flatThenVertical")
        or evidence.get("ictFirstLift")
        or evidence.get("firstLift")
        or evidence.get("ictArmedBaseLaunch")
        or evidence.get("buildingRipReady")
        or evidence.get("ictBuildingRipReady")
    )


def large_ltp_base_cold_velocity_waiver(
    *,
    premium: float,
    symbol: Any,
    evidence: Mapping[str, Any] | None,
    volume_awakening: bool = False,
    settings: Any | None = None,
) -> bool:
    """
    Waive cold first_lift v3 when LTP is in the symbol's near-base band (not NIFTY ₹85).

    SENSEX ₹150–260 at armed pad often shows v3<1.5 pre-vertical — same as NIFTY ₹50–80.
    """
    s = settings or get_settings()
    if not bool(getattr(s, "large_ltp_base_cold_velocity_waiver_enabled", True)):
        return False
    if premium <= 0:
        return False
    sym = _symbol_u(symbol)
    if not sym:
        return False
    evidence = evidence if isinstance(evidence, Mapping) else {}
    if not _structural_base_evidence(evidence):
        return False
    if not volume_awakening and not bool(
        evidence.get("ictVolumeAwakening") or evidence.get("volumeAwaken")
    ):
        quality = float(
            evidence.get("flatVerticalQuality")
            or evidence.get("ictFlatVerticalQuality")
            or 0
        )
        min_q = float(
            getattr(s, "large_ltp_base_cold_velocity_min_flat_quality", 65.0) or 65.0
        )
        if quality + 1e-9 < min_q:
            return False
    nifty_ceiling = float(
        getattr(s, "best_trade_cheap_entry_max_premium_inr", 85.0) or 85.0
    )
    if premium <= nifty_ceiling + 1e-6:
        return False
    sym_ceiling = best_trade_cheap_entry_max_premium(sym, s)
    if premium > sym_ceiling + 1e-6:
        return False
    pad_lo, pad_hi = local_base_pad_premium_band(sym, s)
    if premium < pad_lo or premium > pad_hi + 1e-6:
        return False
    return True


def symbol_from_snap(snap: Any) -> str:
    if snap is None:
        return ""
    return _symbol_u(getattr(snap, "symbol", "") or "")
