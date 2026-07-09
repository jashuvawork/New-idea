"""Breadth-aligned explosion rip — bypass entry interval and directional lock."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.engines.symbol_cooldown import side_aligned_with_breadth
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _event_from_candidate(candidate: Any) -> Optional[ExplosionEvent]:
    event = getattr(candidate, "explosion_event", None)
    if isinstance(event, ExplosionEvent):
        return event
    alert = getattr(candidate, "alert", None) or {}
    if not alert:
        return None
    try:
        return ExplosionEvent(
            symbol=str(getattr(candidate, "symbol", alert.get("symbol", ""))),
            side=Side(_side_val(getattr(candidate, "side", alert.get("side", "CALL")))),
            strike=float(getattr(candidate, "strike", alert.get("strike", 0)) or 0),
            premium=float(getattr(candidate, "premium", alert.get("premium", 0)) or 0),
            velocity_3s=float(alert.get("velocity3s", 0) or 0),
            velocity_9s=float(alert.get("velocity9s", 0) or 0),
            velocity_15s=float(alert.get("velocity15s", 0) or 0),
            volume_surge=float(alert.get("volumeSurge", 1) or 1),
            explosion_score=float(
                getattr(candidate, "score", None) or alert.get("explosionScore", 0) or 0,
            ),
            tier=str(getattr(candidate, "tier", "") or alert.get("tier", "WATCH")),
            reason=str(alert.get("reason", "")),
            daily_move_pct=float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        )
    except Exception:
        return None


def _expiry_tier_min_score(tier: str, settings: Any) -> float:
    """ELITE/EXPLODING floors on own expiry day — looser than global rank caps."""
    base = float(settings.pre_expiry_expiry_symbol_explosion_min_rank)
    tier_u = str(tier or "").upper()
    if tier_u == "ELITE":
        return min(base, 45.0)
    if tier_u == "EXPLODING":
        return min(base, 48.0)
    return base


def is_aligned_explosion_rip(
    candidate: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """
    Breadth-aligned ELITE/EXPLODING rip — eligible for interval + directional-lock bypass.
  """
    settings = get_settings()
    if not settings.aligned_explosion_rip_bypass_enabled:
        return False, "disabled"

    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "not_explosion"

    event = _event_from_candidate(candidate)
    if event is None:
        return False, "no_event"

    tier = str(event.tier or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False, f"tier_{tier.lower()}"

    side_v = _side_val(event.side)
    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    if not side_aligned_with_breadth(side_v, bias):
        return False, "breadth_not_aligned"

    score = float(event.explosion_score or 0)
    min_score = float(settings.aligned_explosion_rip_min_score)
    daily_move = float(event.daily_move_pct or 0)
    if daily_move >= settings.all_day_explosion_session_move_min_pct:
        min_score = min(min_score, settings.all_day_explosion_min_score)
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    if is_symbol_expiry_day(snap):
        min_score = min(min_score, _expiry_tier_min_score(tier, settings))

    if score < min_score:
        return False, f"score_{score:.0f}<{min_score:.0f}"

    v3 = float(event.velocity_3s or 0)
    v9 = float(event.velocity_9s or 0)
    min_v3 = float(settings.aligned_explosion_rip_min_velocity_3s)
    min_v9 = float(settings.aligned_explosion_rip_min_velocity_9s)
    if is_symbol_expiry_day(snap):
        min_v3 = min(min_v3, 1.2)
        min_v9 = min(min_v9, 2.0)
    if v3 < min_v3 and v9 < min_v9:
        return False, "velocity_low"

    return True, "aligned_explosion_rip"


def entry_interval_gap_seconds(
    *,
    chop: bool = False,
    quick_sideways: bool = False,
    after_loss: bool = False,
    aligned_rip: bool = False,
) -> int:
    """Effective minimum seconds between entries."""
    settings = get_settings()
    if aligned_rip:
        return max(15, int(settings.aligned_explosion_rip_interval_seconds))

    gap = (
        settings.quick_sideways_min_seconds_between_entries
        if quick_sideways
        else settings.min_seconds_between_entries
    )
    if chop:
        gap = max(gap, settings.chop_session_entry_interval_seconds)
    gap = max(gap, settings.post_exit_min_seconds)
    if after_loss:
        gap = max(gap, settings.post_loss_exit_min_seconds)
    return gap


def expiry_aligned_explosion_trade_allowed(
    candidate: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """
    Breadth-aligned EXPLODING/ELITE on the symbol's own expiry day.
    Unlocks soft chart blocks + pre-expiry alternate-index routing.
    """
    settings = get_settings()
    if not settings.expiry_aligned_explosion_trade_bypass_enabled:
        return False, "disabled"
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "not_explosion"

    from app.engines.expiry_day_guards import is_symbol_expiry_day

    if not is_symbol_expiry_day(snap):
        return False, "not_expiry_day"

    tier = str(getattr(candidate, "tier", "") or "").upper()
    event = _event_from_candidate(candidate)
    if event is not None:
        tier = str(event.tier or tier).upper()
    if tier not in ("EXPLODING", "ELITE"):
        return False, f"tier_{tier.lower()}"

    side_v = _side_val(getattr(candidate, "side", ""))
    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    if not side_aligned_with_breadth(side_v, bias):
        return False, "breadth_not_aligned"

    score = float(getattr(candidate, "score", 0) or 0)
    if event is not None:
        score = max(score, float(event.explosion_score or 0))
    min_score = _expiry_tier_min_score(tier, settings)
    if score < min_score:
        return False, f"score_{score:.0f}<{min_score:.0f}"

    return True, "expiry_aligned_explosion"


def expiry_aligned_pretrade_soft_bypass(
    candidate: Any,
    snap: SymbolSnapshot,
) -> bool:
    """Waive symbol PF, similar-side PF, rank floors, and deep OTM on expiry rip."""
    ok, _ = expiry_aligned_explosion_trade_allowed(candidate, snap)
    return ok


def expiry_chart_bypass_for_candidate(
    candidate: Any,
    snap: SymbolSnapshot,
) -> bool:
    """Whether soft chart gates (declining momentum, POC) should be waived."""
    if not get_settings().expiry_aligned_explosion_chart_bypass_enabled:
        return False
    ok, _ = expiry_aligned_explosion_trade_allowed(candidate, snap)
    return ok


def expiry_chart_bypass_for_event(event: ExplosionEvent, snap: SymbolSnapshot) -> bool:
    from types import SimpleNamespace

    stub = SimpleNamespace(
        mode="explosion",
        symbol=event.symbol,
        side=event.side,
        tier=event.tier,
        score=event.explosion_score,
        explosion_event=event,
    )
    return expiry_chart_bypass_for_candidate(stub, snap)
