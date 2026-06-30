"""Shared ratcheting trailing floor for scalp and explosion exits."""

from __future__ import annotations

from typing import Optional

from app.models.schemas import PaperTrade


def ratcheting_trail_floor(
    trade: PaperTrade,
    best_pts: float,
    *,
    arm_points: float,
    keep_ratio: float,
    step_points: float,
    tight_arm: float = 999.0,
    tight_points: float = 0.0,
    floor_key: str = "trailFloorPts",
    best_key: str = "trailBestPts",
) -> Optional[float]:
    """
    Ratcheting profit floor in premium points — only moves up.
    Returns None until best_pts >= arm_points.
    """
    if best_pts < arm_points:
        return None

    ratio_floor = best_pts * keep_ratio
    step_floor = best_pts - step_points
    floor_pts = max(ratio_floor, step_floor)

    if tight_arm < 900 and best_pts >= tight_arm and tight_points > 0:
        floor_pts = max(floor_pts, best_pts - tight_points)

    ctx = dict(trade.entryContext or {})
    prev = ctx.get(floor_key)
    if prev is not None:
        floor_pts = max(floor_pts, float(prev))
    ctx[floor_key] = round(floor_pts, 2)
    ctx[best_key] = round(best_pts, 2)
    trade.entryContext = ctx
    return floor_pts
