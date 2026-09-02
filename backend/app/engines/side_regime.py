"""Session side-regime & flip detector — "which side is the market on / flipping to".

The selector historically decided CE vs PE by ranking simultaneous CALL/PUT
candidates with a bag of instantaneous bonuses/penalties (breadth bias, current
dominant leg, momentum-turn bypasses). Nothing tracked, at the session level,
"the market was BEARISH → now it's turning BULLISH, prefer CALLs" — so on a
two-sided chop day it could keep leaning the stale side while the other side is
the real move (Aug31: near-base ELITE CALLs missed while PUTs led).

This module maintains ONE confirmed side-regime per symbol for the session. It
only flips after *sustained* confirmation (N consecutive confident votes over M
seconds), so a single chop spike can't flip it, but a genuine turn does — and it
exposes both the confirmed side and the in-progress flip target so the selector
can prefer the side the market is actually turning toward.

Pure state helper: ``observe_side_regime`` is called once per symbol per cycle to
update state; ``session_trade_side`` / ``side_regime_rank_delta`` drive selection.
The LIVE trigger/exit never depends on this — it only nudges side ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class _SideRegime:
    side: str = "NEUTRAL"                 # confirmed regime: CALL / PUT / NEUTRAL
    confirmed_at: Optional[datetime] = None
    pending_side: str = ""               # flip target currently being confirmed
    pending_count: int = 0
    pending_since: Optional[datetime] = None
    last_vote: str = "NEUTRAL"
    last_confidence: int = 0
    date: Optional[Any] = None


_regimes: dict[str, _SideRegime] = {}


def reset_side_regime_for_tests() -> None:
    _regimes.clear()


def _side_str(side: Any) -> str:
    from app.models.schemas import Side

    return side.value if isinstance(side, Side) else str(side or "").upper()


def _instant_side_vote(snap: Any) -> tuple[str, int, list[str]]:
    """Instantaneous market-side vote from independent signals.

    Combines index 5m chart direction+momentum, the live dominant option leg, and
    tape-confirmed index drift. Returns (side, confidence 0-3, reasons); NEUTRAL
    when signals conflict or are too weak.
    """
    settings = get_settings()
    reasons: list[str] = []
    call_votes = 0
    put_votes = 0

    # 1) Index 5m chart direction + momentum.
    chart = getattr(snap, "spotChart", None)
    if chart is not None:
        direction = str(getattr(chart, "direction", "") or "").upper()
        mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
        min_mom = float(
            getattr(settings, "side_regime_min_chart_mom5_pct", 0.05) or 0.05
        )
        if direction == "BULLISH" and mom5 >= min_mom:
            call_votes += 1
            reasons.append("chart_bull")
        elif direction == "BEARISH" and mom5 <= -min_mom:
            put_votes += 1
            reasons.append("chart_bear")

    # 2) Live dominant option leg (premium velocity/score).
    try:
        from app.engines.best_side_selection import side_velocity_metrics

        dom = str(side_velocity_metrics(snap).get("dominantSide") or "")
        if dom == "CALL":
            call_votes += 1
            reasons.append("dominant_call")
        elif dom == "PUT":
            put_votes += 1
            reasons.append("dominant_put")
    except Exception:
        pass

    # 3) Tape-confirmed sustained index drift.
    try:
        from app.engines.index_tick_helpers import recent_index_drift

        sym = str(getattr(snap, "symbol", "") or "").upper()
        if sym:
            if recent_index_drift(sym, "CALL").get("drift"):
                call_votes += 1
                reasons.append("index_drift_up")
            elif recent_index_drift(sym, "PUT").get("drift"):
                put_votes += 1
                reasons.append("index_drift_down")
    except Exception:
        pass

    if call_votes > put_votes and call_votes >= 1:
        return "CALL", call_votes, reasons
    if put_votes > call_votes and put_votes >= 1:
        return "PUT", put_votes, reasons
    return "NEUTRAL", 0, reasons


def observe_side_regime(
    symbol: Any,
    snap: Any,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Update and return the session side-regime for one symbol from a fresh snapshot."""
    settings = get_settings()
    if not bool(getattr(settings, "side_regime_enabled", True)):
        return {"side": "NEUTRAL", "flipping": False}

    sym = str(symbol or "").upper()
    now = now or datetime.now(IST)
    today = now.date()
    reg = _regimes.get(sym)
    if reg is None or reg.date != today:
        reg = _SideRegime(date=today)
        _regimes[sym] = reg

    vote, conf, reasons = _instant_side_vote(snap)
    reg.last_vote = vote
    reg.last_confidence = conf

    min_conf = int(getattr(settings, "side_regime_min_vote_confidence", 2) or 2)
    min_confirms = int(getattr(settings, "side_regime_flip_min_confirms", 3) or 3)
    min_seconds = float(
        getattr(settings, "side_regime_flip_min_seconds", 20.0) or 20.0
    )

    just_flipped = False
    confident = vote in ("CALL", "PUT") and conf >= min_conf

    if reg.side == "NEUTRAL" and confident:
        # Seed the regime the first time a confident directional vote appears.
        reg.side = vote
        reg.confirmed_at = now
        reg.pending_side = ""
        reg.pending_count = 0
        reg.pending_since = None
    elif confident and vote != reg.side:
        # Confident opposite vote → build a pending flip; commit only when sustained.
        if reg.pending_side == vote:
            reg.pending_count += 1
        else:
            reg.pending_side = vote
            reg.pending_count = 1
            reg.pending_since = now
        elapsed = (
            (now - reg.pending_since).total_seconds() if reg.pending_since else 0.0
        )
        if reg.pending_count >= min_confirms and elapsed >= min_seconds:
            reg.side = vote
            reg.confirmed_at = now
            reg.pending_side = ""
            reg.pending_count = 0
            reg.pending_since = None
            just_flipped = True
    elif vote == reg.side:
        # Vote agrees with the regime → cancel any in-progress flip.
        reg.pending_side = ""
        reg.pending_count = 0
        reg.pending_since = None

    return {
        "side": reg.side,
        "flipping": bool(reg.pending_side),
        "flipTarget": reg.pending_side or None,
        "pendingCount": reg.pending_count,
        "vote": vote,
        "voteConfidence": conf,
        "reasons": reasons,
        "justFlipped": just_flipped,
    }


def session_trade_side(symbol: Any) -> str:
    """Confirmed session regime side (CALL/PUT/NEUTRAL) for one symbol."""
    reg = _regimes.get(str(symbol or "").upper())
    return reg.side if reg else "NEUTRAL"


def side_regime_state(symbol: Any) -> dict[str, Any]:
    reg = _regimes.get(str(symbol or "").upper())
    if reg is None:
        return {"side": "NEUTRAL", "flipping": False, "flipTarget": None, "pendingCount": 0}
    return {
        "side": reg.side,
        "flipping": bool(reg.pending_side),
        "flipTarget": reg.pending_side or None,
        "pendingCount": reg.pending_count,
        "lastVote": reg.last_vote,
    }


def side_regime_rank_delta(symbol: Any, side: Any) -> float:
    """Rank nudge for a candidate side vs the confirmed session regime.

    + for the confirmed side, - for the counter side, but the counter penalty is
    replaced by a small bonus when this side is the in-progress flip target — so a
    genuine turn toward it is *helped*, not fought, while the flip is confirming.
    """
    settings = get_settings()
    if not bool(getattr(settings, "side_regime_enabled", True)):
        return 0.0
    if not bool(getattr(settings, "side_regime_influences_ranking", True)):
        return 0.0
    reg = _regimes.get(str(symbol or "").upper())
    if reg is None or reg.side == "NEUTRAL":
        return 0.0
    side_v = _side_str(side)
    if side_v == reg.side:
        return float(getattr(settings, "side_regime_rank_bonus", 15.0) or 15.0)
    if reg.pending_side and side_v == reg.pending_side:
        return float(
            getattr(settings, "side_regime_flip_target_bonus", 6.0) or 6.0
        )
    return -float(getattr(settings, "side_regime_counter_penalty", 15.0) or 15.0)
