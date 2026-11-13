"""Prefer index-leg aligned #676 book strikes over off-book explosion chase."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def _side_u(raw: Any) -> str:
    val = str(getattr(raw, "value", raw) or "").upper()
    if val in {"CALL", "CE", "C"}:
        return "CALL"
    if val in {"PUT", "PE", "P"}:
        return "PUT"
    return val


def _local_base_from_candidate(candidate: Any) -> float:
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        pre = getattr(candidate, "pretrade_meta", None) or {}
        if isinstance(pre, dict):
            ranking = pre.get("causalRanking") or {}
            if isinstance(ranking, dict):
                ev = ranking.get("evidence") or {}
                if isinstance(ev, dict):
                    alert = ev
    if not isinstance(alert, dict):
        return 0.0
    for key in (
        "localBaseMovePct",
        "ictBaseRelativeMovePct",
        "offLowMovePct",
        "offHighMovePct",
    ):
        try:
            val = float(alert.get(key) or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            return val
    return 0.0


def _strike_match(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < 0.51


def index_aligned_book_rank_adjustment(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
) -> float:
    """
    When dominant index leg is clear, boost strikes on the HUD aligned book;
    penalize (or disqualify) same-side chase strikes not on that book.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_aligned_book_selector_enabled", True)):
        return 0.0
    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        index_trend_features_active,
        side_aligns_with_dominant_trend,
    )

    if not index_trend_features_active(settings):
        return 0.0

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return 0.0
    side_u = _side_u(getattr(candidate, "side", ""))
    try:
        strike = float(getattr(candidate, "strike", 0) or 0)
    except (TypeError, ValueError):
        strike = 0.0
    if strike <= 0 or side_u not in ("CALL", "PUT"):
        return 0.0

    dominant, _meta = index_session_dominant_trend(
        sym, snap, state, settings=settings, track_flip=False,
    )
    if dominant == "NEUTRAL" or not side_aligns_with_dominant_trend(side_u, dominant):
        return 0.0

    aligned_side = "CALL" if dominant == "RALLY" else "PUT"
    if side_u != aligned_side:
        return 0.0

    from app.engines.index_session_narrative import aligned_explosion_book_picks

    limit = int(getattr(settings, "index_aligned_book_picks_limit", 5) or 5)
    picks = aligned_explosion_book_picks(sym, snap, aligned_side, limit=limit)
    if not picks:
        return 0.0

    near_base_cap = float(
        getattr(settings, "index_aligned_book_near_base_max_pct", 28.0) or 28.0
    )
    book_has_pad = any(bool(p.get("nearBase676")) for p in picks)
    if not book_has_pad:
        return 0.0

    pick_idx = next(
        (i for i, p in enumerate(picks) if _strike_match(strike, float(p.get("strike") or 0))),
        None,
    )
    on_book_bonus = float(getattr(settings, "index_aligned_book_on_pick_bonus", 32.0) or 32.0)
    top_pick_extra = float(
        getattr(settings, "index_aligned_book_top_pick_extra", 14.0) or 14.0
    )
    near_base_extra = float(
        getattr(settings, "index_aligned_book_near_base_extra", 10.0) or 10.0
    )

    if pick_idx is not None:
        adj = on_book_bonus
        if pick_idx == 0:
            adj += top_pick_extra
        if bool(picks[pick_idx].get("nearBase676")):
            adj += near_base_extra
        return adj

    try:
        cand_score = float(getattr(candidate, "score", 0) or 0)
    except (TypeError, ValueError):
        cand_score = 0.0
    top_book_score = max(
        (float(p.get("explosionScore") or 0) for p in picks),
        default=0.0,
    )
    gap_bypass = float(
        getattr(settings, "index_aligned_book_elite_score_gap_bypass", 55.0) or 55.0
    )
    if cand_score > 0 and top_book_score > 0 and cand_score >= top_book_score + gap_bypass:
        return 0.0

    off_penalty = float(
        getattr(settings, "index_aligned_book_off_pick_penalty", 140.0) or 140.0
    )
    chase_extra = float(
        getattr(settings, "index_aligned_book_chase_penalty", 25.0) or 25.0
    )
    local_base = _local_base_from_candidate(candidate)
    if local_base <= 0 or local_base > near_base_cap:
        off_penalty += chase_extra

    hard = bool(getattr(settings, "index_aligned_book_hard_require_enabled", True))
    if hard:
        off_penalty += float(
            getattr(settings, "index_aligned_book_disqualify_penalty", 120.0) or 120.0
        )
    return -off_penalty
