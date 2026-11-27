"""One final entry validation at the order wire — fresh index snapshot + live tape context.

Runs only the gates that can go stale between early ``validate_candidate`` and
``place_entry_order``: session participation / MTF intent and live index-leg alignment.
Premium tape checks stay in ``execution_order_preflight_blocked`` and execution chart.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


def _sync_candidate_snap(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]],
) -> None:
    if not snapshots:
        return
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    fresh = snapshots.get(sym)
    if fresh is not None:
        try:
            candidate.snap = fresh
        except Exception:
            pass


def order_time_entry_blocked(
    candidate: Any,
    state: AutoTraderState,
    snapshots: Optional[dict[str, SymbolSnapshot]],
    *,
    premium_chart: Any = None,
    is_live: bool = False,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Last structural pass before broker/paper entry.

    Returns (blocked, reason, metadata) for entryContext / funnel.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"orderTimeEntryPass": True, "checks": {}}
    if not bool(getattr(settings, "order_time_entry_pass_enabled", True)):
        return False, "ok", meta

    if snapshots:
        _sync_candidate_snap(candidate, snapshots)

    if bool(getattr(settings, "order_time_entry_pass_session_intent", True)):
        if snapshots:
            from app.engines.session_intent_authority import session_intent_blocks_entry

            si_blocked, si_reason, si_meta = session_intent_blocks_entry(
                candidate, state, snapshots, settings=settings,
            )
            meta["checks"]["sessionIntent"] = {
                "blocked": si_blocked,
                "reason": si_reason,
                **(si_meta if isinstance(si_meta, dict) else {}),
            }
            if si_blocked:
                return True, f"order_time_{si_reason}", meta

    if is_live and bool(
        getattr(settings, "order_time_entry_pass_live_index_leg", True)
    ):
        if snapshots:
            from app.engines.live_entry_integrity import live_index_leg_hard_blocks_entry

            leg_blocked, leg_reason, leg_meta = live_index_leg_hard_blocks_entry(
                candidate, state, snapshots, settings=settings,
            )
            meta["checks"]["liveIndexLeg"] = {
                "blocked": leg_blocked,
                "reason": leg_reason,
                **(leg_meta if isinstance(leg_meta, dict) else {}),
            }
            if leg_blocked:
                return True, f"order_time_{leg_reason}", meta

    if premium_chart is not None:
        meta["checks"]["premiumChartSynced"] = True

    return False, "ok", meta