"""Open slide + rally-off-low near-base capture (Sep 9–17 class, CE/PE symmetric).

Sep29: open PUT slide and CE recovery off session low were detected late or blocked as
non-tradeable OTM / ftv_elite_top_only_requires_atm_itm / tight elite local-base cap
while symmetric rally unlock was already armed.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.best_trade_policy import _number
from app.models.schemas import Side, SymbolSnapshot


def _enabled(settings: Any = None) -> bool:
    settings = settings or get_settings()
    return bool(getattr(settings, "near_base_session_capture_enabled", True))


def evidence_cheap_base_pad(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    """₹18–80-style pad at session extreme (OTM/ATM), within cheap-base local bands."""
    settings = settings or get_settings()
    if not _enabled(settings):
        return False
    if not bool(getattr(settings, "best_trade_cheap_base_rank_priority_enabled", True)):
        return False
    sym = str(evidence.get("symbol") or "").upper()
    premium = _number(evidence.get("premium"))
    from app.engines.symbol_premium_bands import best_trade_cheap_base_premium_band

    prem_lo, prem_hi = best_trade_cheap_base_premium_band(sym, settings)
    if not (prem_lo <= premium <= prem_hi):
        return False
    pad = max(
        _number(evidence.get("localBaseMovePct")),
        _number(evidence.get("ictBaseRelativeMovePct")),
        _number(evidence.get("offLowMovePct")),
    )
    max_pad = float(getattr(settings, "best_trade_cheap_base_max_local_pct", 22.0) or 22.0)
    if pad > max_pad + 1e-6 and pad > 0.05:
        return False
    off_low = _number(evidence.get("offLowMovePct"))
    max_off = float(
        getattr(settings, "best_trade_cheap_base_max_off_extreme_pct", 35.0) or 35.0
    )
    if off_low > max_off + 1e-6:
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING", "WATCH"):
        return False
    return bool(
        evidence.get("volumeAwaken")
        or evidence.get("ictVolumeAwakening")
        or evidence.get("ictBaseArmed")
        or evidence.get("ictArmedBaseLaunch")
        or evidence.get("ictFirstLift")
        or evidence.get("ictVRipReady")
        or evidence.get("ictFlatThenVertical")
        or evidence.get("indexConfirmedLocalBase")
        or evidence.get("ictIndexConfirmedLocalBase")
    )


def session_capture_local_base_cap_pct(
    side: str,
    *,
    settings: Any = None,
    evidence: Mapping[str, Any] | None = None,
    ranking: Mapping[str, Any] | None = None,
    assessment: Mapping[str, Any] | None = None,
    state: Any = None,
    snap: Any = None,
) -> float | None:
    """Widen elite local-base window for open slide / rally-off-low capture paths."""
    settings = settings or get_settings()
    if not _enabled(settings) or evidence is None:
        return None
    general = float(getattr(settings, "elite_trade_max_local_base_pct", 20.0) or 20.0)
    widen = float(
        getattr(settings, "near_base_session_capture_max_local_pct", 28.0) or 28.0
    )
    cheap_cap = float(getattr(settings, "best_trade_cheap_base_max_local_pct", 22.0) or 22.0)
    cap = max(general, widen, cheap_cap)

    side_u = str(side or "").upper()
    if evidence_cheap_base_pad(evidence, settings=settings):
        return cap
    if bool(
        evidence.get("indexConfirmedLocalBase")
        or evidence.get("ictIndexConfirmedLocalBase")
    ):
        return cap

    symbol = str(evidence.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if side_u == "CALL" and state is not None and snap is not None:
        try:
            from app.engines.pe_win_ce_mirror import (
                call_ce_base_context_armed,
                call_rally_entry_unlock_fingerprint,
            )

            armed, _, _ = call_ce_base_context_armed(
                state, snap, symbol, evidence, settings=settings,
            )
            if armed or call_rally_entry_unlock_fingerprint(
                evidence,
                ranking,
                assessment,
                state=state,
                snap=snap,
                symbol=symbol,
                settings=settings,
            ):
                return cap
        except Exception:
            pass
    if side_u == "PUT" and state is not None and snap is not None:
        try:
            from app.engines.put_slide_ce_mirror import put_slide_entry_unlock_fingerprint

            if put_slide_entry_unlock_fingerprint(
                evidence,
                ranking,
                assessment,
                state=state,
                snap=snap,
                symbol=symbol,
                settings=settings,
            ):
                return cap
        except Exception:
            pass
    return None


def ftv_session_capture_waives_atm_itm(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """Allow shallow OTM FTV when cheap-base or index-rally / slide context is active."""
    settings = settings or get_settings()
    if not _enabled(settings):
        return False
    if not bool(getattr(settings, "near_base_cheap_otm_ftv_waives_atm_itm", True)):
        return False
    if bool(evidence.get("cheapBaseOtmCapture") or evidence.get("cheapBaseSessionCapture")):
        return True
    if evidence_cheap_base_pad(evidence, settings=settings):
        return True
    if bool(
        evidence.get("indexConfirmedLocalBase")
        or evidence.get("ictIndexConfirmedLocalBase")
    ):
        tier = str(evidence.get("tier") or "").upper()
        return tier in ("ELITE", "EXPLODING", "BUILDING")
    side_u = str(evidence.get("side") or "").upper()
    if snap is not None:
        if side_u == "CALL":
            from app.engines.index_confirmed_local_base import index_confirmed_local_base

            if index_confirmed_local_base(Side.CALL, snap, evidence, settings=settings):
                return True
        elif side_u == "PUT":
            from app.engines.index_confirmed_local_base import index_confirmed_local_base

            if index_confirmed_local_base(Side.PUT, snap, evidence, settings=settings):
                return True
    return False


def stamp_cheap_base_otm_tradeable(
    alert: dict[str, Any],
    *,
    snap: Optional[SymbolSnapshot],
    settings: Any = None,
) -> bool:
    """Keep shallow OTM on radar/tradeable during open slide or rally-off-low."""
    settings = settings or get_settings()
    if not _enabled(settings) or snap is None:
        return False
    probe = dict(alert)
    probe.setdefault("symbol", getattr(snap, "symbol", ""))
    if not evidence_cheap_base_pad(probe, settings=settings):
        return False
    alert["cheapBaseOtmCapture"] = True
    alert["cheapBaseSessionCapture"] = True
    alert["tradeable"] = True
    return True


def otm_tradeable_preserved(alert: Mapping[str, Any], *, settings: Any = None) -> bool:
    if bool(alert.get("earlyRadarPadCapture") or alert.get("shallowOtmLocalBaseTradeable")):
        return True
    if bool(alert.get("cheapBaseOtmCapture") or alert.get("cheapBaseSessionCapture")):
        return True
    if bool(
        alert.get("indexConfirmedLocalBase")
        or alert.get("ictIndexConfirmedLocalBase")
    ):
        return True
    return False
