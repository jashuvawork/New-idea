"""Same-moment top-1 dedup for Elite entries — shared by live selector and EOD replay."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

RowRankKey = tuple[float, int, float, str]


def parse_moment_key(raw: Any) -> str:
    """Normalize ictBaseArmedAt (or ts) to second-precision moment key."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        else:
            dt = dt.astimezone(IST)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return text[:19]


def row_rank_key(row: dict[str, Any]) -> RowRankKey:
    return (
        float(row.get("eliteScore") or 0),
        -int(row.get("setupPriority") or 9),
        float(row.get("_rankScore") or row.get("rankScore") or 0),
        str(row.get("ts") or ""),
    )


def dedupe_same_moment_top1(
    rows: list[dict[str, Any]],
    *,
    pass_fn: Callable[[dict[str, Any]], bool] | None = None,
    moment_key_fn: Callable[[dict[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """One trade per armed-base second — keep highest EliteScore."""
    key_fn = moment_key_fn or (
        lambda row: str(row.get("momentKey") or parse_moment_key(row.get("ts")))
    )
    by_moment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if pass_fn is not None and not pass_fn(row):
            continue
        key = key_fn(row)
        if not key:
            key = str(row.get("ts") or "")[:19]
        by_moment[key].append(row)
    return [max(pool, key=row_rank_key) for pool in by_moment.values()]


def candidate_rank_key(candidate: Any) -> RowRankKey:
    meta = getattr(candidate, "pretrade_meta", None) or {}
    gate = meta.get("topMomentGate") or {}
    assessment = gate.get("eliteAssessment") or {}
    ranking = meta.get("causalRanking") or {}
    return (
        float(assessment.get("eliteScore") or 0),
        -int(assessment.get("setupPriority") or 9),
        float(ranking.get("rankScore") or 0),
        str(getattr(candidate, "symbol", "") or ""),
    )


def moment_key_from_candidate(candidate: Any) -> str:
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        armed = parse_moment_key(alert.get("ictBaseArmedAt"))
        if armed:
            return armed
    meta = getattr(candidate, "pretrade_meta", None) or {}
    ranking = meta.get("causalRanking") or {}
    evidence = ranking.get("evidence") or {}
    armed = parse_moment_key(evidence.get("ictBaseArmedAt"))
    if armed:
        return armed
    side = getattr(getattr(candidate, "side", None), "value", candidate.side)
    return (
        f"{getattr(candidate, 'symbol', '')}:{side}:"
        f"{float(getattr(candidate, 'strike', 0) or 0):g}"
    )


def dedupe_same_moment_candidates(
    candidates: list[Any],
    *,
    pass_fn: Callable[[Any], bool] | None = None,
) -> list[Any]:
    """Live selector: one candidate per armed-base second — highest EliteScore wins."""
    by_moment: dict[str, list[Any]] = defaultdict(list)
    for candidate in candidates:
        if pass_fn is not None and not pass_fn(candidate):
            continue
        by_moment[moment_key_from_candidate(candidate)].append(candidate)
    return [max(pool, key=candidate_rank_key) for pool in by_moment.values()]
