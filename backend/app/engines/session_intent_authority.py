"""Session Intent — single participation authority (session leg + breadth + 5m/15m/1h MTF).

Prevents counter-side mid-pad entries when structural slide/rally and HTF charts agree,
while leaving near-base aligned captures and trend-breakout paths intact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")
from app.engines.chop_day_guards import resolve_chop_day_mode_from_state
from app.engines.day_mode_counter_trap import breadth_confirms_day_bias, counter_day_mode_side
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot, TimeframeChartRead

ParticipationSide = Literal["CALL", "PUT", "BOTH", "NONE"]
SessionLeg = Literal["RALLY", "SLIDE", "NEUTRAL"]


def _side_u(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _allowed_symbols(sym: str, settings: Any) -> bool:
    raw = str(
        getattr(settings, "session_intent_symbols_csv", "NIFTY,SENSEX") or "NIFTY,SENSEX"
    )
    return sym.upper() in {s.strip().upper() for s in raw.split(",") if s.strip()}


def authority_active(settings: Any = None) -> bool:
    settings = settings or get_settings()
    return bool(getattr(settings, "session_intent_authority_enabled", True))


def _tf_read_from_dict(label: str, data: Any) -> TimeframeChartRead | None:
    if not isinstance(data, dict):
        return None
    try:
        return TimeframeChartRead(label=label, **{k: data[k] for k in data if k in TimeframeChartRead.model_fields})
    except Exception:
        return TimeframeChartRead(
            label=label,
            direction=str(data.get("direction") or "NEUTRAL").upper(),
            momentumPct=float(data.get("momentumPct") or 0),
            trendStrength=float(data.get("trendStrength") or 0),
            emaBias=str(data.get("emaBias") or "NEUTRAL").upper(),
        )


def _synthetic_3m_from_5m(read_5m: TimeframeChartRead | None, spot: float) -> TimeframeChartRead | None:
    """Approximate 3m tactical read when only 5m spotChart exists (faster than 5m for slide fade)."""
    if read_5m is None:
        return None
    mom = float(read_5m.momentumPct or 0)
    mom3 = float(read_5m.momentum3Pct or mom * 0.6)
    direction = str(read_5m.direction or "NEUTRAL").upper()
    # Sharpen: short bounce on slide day often shows bullish 5m while 3m-equivalent mom is flat/bearish
    if direction == "BULLISH" and mom3 < 0.02 and mom < 0.06:
        direction = "NEUTRAL"
    if mom3 < -0.02:
        direction = "BEARISH"
    strength = max(8.0, float(read_5m.trendStrength or 0) * 0.85)
    return TimeframeChartRead(
        label="3m",
        direction=direction,
        momentumPct=mom3,
        momentum3Pct=mom3,
        trendStrength=strength,
        emaBias=read_5m.emaBias,
        price=spot,
    )


def mtf_reads_from_snapshot(snap: SymbolSnapshot) -> dict[str, TimeframeChartRead]:
    """5m / 15m / 1h (+ 1m, 4h when present) from live snapshot chartAnalysis — no tape."""
    reads: dict[str, TimeframeChartRead] = {}
    ca = getattr(snap, "chartAnalysis", None)
    if ca is not None and getattr(ca, "timeframes", None):
        for label, data in (ca.timeframes or {}).items():
            read = _tf_read_from_dict(str(label), data)
            if read is not None:
                reads[str(label)] = read
    chart = snap.spotChart
    spot = float(getattr(snap, "spot", 0) or 0)
    if chart and "5m" not in reads:
        reads["5m"] = TimeframeChartRead(
            label="5m",
            direction=str(getattr(chart, "direction", None) or "NEUTRAL").upper(),
            momentumPct=float(getattr(chart, "momentum5Pct", 0) or 0),
            momentum3Pct=float(getattr(chart, "momentum3Pct", 0) or 0),
            trendStrength=float(getattr(chart, "trendStrength", 0) or 0),
            emaBias=str(getattr(chart, "emaBias", None) or "NEUTRAL").upper(),
        )
    if "3m" not in reads:
        c1 = reads.get("1m")
        if c1 is not None:
            reads["3m"] = TimeframeChartRead(
                label="3m",
                direction=c1.direction,
                momentumPct=float(c1.momentum3Pct or c1.momentumPct or 0),
                momentum3Pct=float(c1.momentum3Pct or 0),
                trendStrength=float(c1.trendStrength or 0) * 0.9,
                emaBias=c1.emaBias,
            )
        else:
            syn = _synthetic_3m_from_5m(reads.get("5m"), spot)
            if syn is not None:
                reads["3m"] = syn
    return reads


def _timeframe_opposes_side(read: TimeframeChartRead | None, side_u: str) -> bool:
    if read is None:
        return False
    d = str(read.direction or "NEUTRAL").upper()
    strength = float(read.trendStrength or 0)
    if side_u == "CALL":
        return d == "BEARISH" and strength >= 12
    if side_u == "PUT":
        return d == "BULLISH" and strength >= 12
    return False


def _timeframe_aligns_side(read: TimeframeChartRead | None, side_u: str) -> bool:
    if read is None:
        return False
    d = str(read.direction or "NEUTRAL").upper()
    mom = float(read.momentumPct or 0)
    if side_u == "CALL":
        return d != "BEARISH" and mom >= -0.05
    if side_u == "PUT":
        return d != "BULLISH" and mom <= 0.05
    return False


def mtf_summary_for_side(side: Side | str, snap: SymbolSnapshot, *, settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    side_u = _side_u(side)
    reads = mtf_reads_from_snapshot(snap)
    labels = [
        s.strip()
        for s in str(
            getattr(settings, "session_intent_mtf_anchor_labels_csv", "5m,15m,1h") or "5m,15m,1h"
        ).split(",")
        if s.strip()
    ]
    htf_labels = [
        s.strip()
        for s in str(
            getattr(settings, "session_intent_mtf_htf_labels_csv", "15m,1h") or "15m,1h"
        ).split(",")
        if s.strip()
    ]
    per_tf: dict[str, Any] = {}
    for lb in labels:
        r = reads.get(lb)
        per_tf[lb] = {
            "direction": r.direction if r else None,
            "momentumPct": round(float(r.momentumPct or 0), 3) if r else None,
            "opposes": _timeframe_opposes_side(r, side_u),
            "aligns": _timeframe_aligns_side(r, side_u),
        }
    htf_oppose = sum(1 for lb in htf_labels if _timeframe_opposes_side(reads.get(lb), side_u))
    htf_align = sum(1 for lb in htf_labels if _timeframe_aligns_side(reads.get(lb), side_u))
    tactical_label = str(
        getattr(settings, "session_intent_tactical_timeframe", "3m") or "3m"
    ).strip().lower()
    tactical_read = reads.get(tactical_label) or reads.get("5m") or reads.get("3m")
    tactical_5m = reads.get("5m")
    tactical_opposes = _timeframe_opposes_side(tactical_read, side_u)
    tactical5_opposes = _timeframe_opposes_side(tactical_5m, side_u)
    return {
        "side": side_u,
        "tacticalLabel": tactical_label,
        "timeframes": per_tf,
        "htfOpposeCount": htf_oppose,
        "htfAlignCount": htf_align,
        "tacticalOpposes": tactical_opposes,
        "tactical5mOpposes": tactical5_opposes,
    }


def _local_pad_from_candidate(candidate: Any) -> float:
    alert = getattr(candidate, "alert", None)
    alert = alert if isinstance(alert, dict) else {}
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    for src in (alert, ranking, pretrade if isinstance(pretrade, dict) else {}):
        local = float(
            src.get("localBaseMovePct")
            or src.get("ictBaseRelativeMovePct")
            or src.get("offLowMovePct")
            or 0
        )
        if local > 0:
            return local
    ev = getattr(candidate, "explosion_event", None)
    if ev is not None:
        return max(
            float(getattr(ev, "local_base_move_pct", 0) or 0),
            float(getattr(ev, "daily_move_pct", 0) or 0),
        )
    return 0.0


def resolve_session_intent(
    sym: str,
    snap: SymbolSnapshot,
    state: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """Authoritative session playbook for one index symbol."""
    settings = settings or get_settings()
    state = state or AutoTraderState()
    meta: dict[str, Any] = {"symbol": sym.upper()}

    if not authority_active(settings):
        return {"enabled": False, **meta}

    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        side_aligns_with_dominant_trend,
    )

    leg, trend_meta = index_session_dominant_trend(sym, snap, state, settings=settings)
    meta.update(trend_meta)
    meta["sessionLeg"] = leg

    br = snap.breadth
    breadth_bias = str(getattr(br, "bias", "") or "NEUTRAL").upper() if br else "NEUTRAL"
    meta["breadthBias"] = breadth_bias

    day_mode = resolve_chop_day_mode_from_state(state)
    meta["dayMode"] = day_mode

    participation: ParticipationSide = "BOTH"
    if leg == "RALLY":
        participation = "CALL"
    elif leg == "SLIDE":
        participation = "PUT"

    confidence = "MEDIUM"
    if leg != "NEUTRAL" and br and bool(getattr(br, "aligned", False)):
        if leg == "SLIDE" and breadth_bias == "BEARISH":
            confidence = "HIGH"
        elif leg == "RALLY" and breadth_bias == "BULLISH":
            confidence = "HIGH"
    if counter_day_mode_side(day_mode, "CALL" if leg == "SLIDE" else "PUT"):
        if breadth_confirms_day_bias(snap, day_mode):
            confidence = "HIGH"
    meta["confidence"] = confidence

    allow_counter = leg == "NEUTRAL" or confidence != "HIGH"
    meta["allowCounterSide"] = allow_counter
    meta["participationSide"] = participation

    call_mtf = mtf_summary_for_side("CALL", snap, settings=settings)
    put_mtf = mtf_summary_for_side("PUT", snap, settings=settings)
    meta["mtf"] = {"CALL": call_mtf, "PUT": put_mtf}
    meta["sideAlignsCall"] = side_aligns_with_dominant_trend("CALL", leg)
    meta["sideAlignsPut"] = side_aligns_with_dominant_trend("PUT", leg)
    return {"enabled": True, **meta}


def session_intent_summary(
    snapshots: dict[str, SymbolSnapshot],
    state: Any = None,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not authority_active(settings):
        return {"enabled": False, "symbols": {}}
    symbols: dict[str, Any] = {}
    for sym, snap in snapshots.items():
        if not snap or not _allowed_symbols(str(sym), settings):
            continue
        symbols[str(sym).upper()] = resolve_session_intent(sym, snap, state, settings=settings)
    return {"enabled": True, "symbols": symbols}


def _side_counter_to_participation(side_u: str, intent: dict[str, Any]) -> bool:
    part = str(intent.get("participationSide") or "BOTH").upper()
    if part == "BOTH" or part == "NONE":
        return part == "BOTH"
    return side_u != part


def session_intent_suppresses_premium_led_bypass(
    side: Side | str,
    snap: SymbolSnapshot,
    state: Any = None,
    *,
    local_pad: float = 0.0,
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    if not authority_active(settings):
        return False
    sym = str(getattr(snap, "symbol", "") or "").upper()
    if not _allowed_symbols(sym, settings):
        return False
    intent = resolve_session_intent(sym, snap, state, settings=settings)
    if not intent.get("enabled"):
        return False
    side_u = _side_u(side)
    if not _side_counter_to_participation(side_u, intent):
        return False
    if intent.get("allowCounterSide"):
        pad_cap = float(
            getattr(settings, "session_intent_counter_near_base_max_pct", 8.0) or 8.0
        )
        if local_pad <= pad_cap + 1e-6:
            return False
    mtf = (intent.get("mtf") or {}).get(side_u) or {}
    min_htf = int(getattr(settings, "session_intent_mtf_min_htf_oppose_counter", 1) or 1)
    if int(mtf.get("htfOpposeCount") or 0) >= min_htf:
        return True
    if intent.get("confidence") == "HIGH":
        max_pad = float(
            getattr(settings, "session_intent_counter_max_local_pad_pct", 12.0) or 12.0
        )
        if local_pad >= max_pad - 1e-6:
            return True
    return False


def _post_win_afternoon_band_active(state: Any, *, settings: Any = None) -> tuple[bool, dict[str, Any]]:
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "session_post_win_afternoon_hard_block_enabled", True)):
        return False, meta
    now = datetime.now(IST)
    sh = int(getattr(settings, "session_post_win_afternoon_start_hour", 11) or 11)
    sm = int(getattr(settings, "session_post_win_afternoon_start_minute", 30) or 30)
    if now.hour < sh or (now.hour == sh and now.minute < sm):
        return False, meta
    from app.engines.explosion_entry_guards import _post_session_win

    post_win, pw = _post_session_win(state)
    if not post_win:
        return False, meta
    min_win = float(getattr(settings, "chop_post_win_afternoon_min_win_inr", 2000.0) or 2000.0)
    if float(pw.get("lastPnlInr") or 0) < min_win:
        return False, meta
    meta.update(pw)
    meta["postWinAfternoonBand"] = True
    return True, meta


def session_intent_blocks_entry(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Hard block counter-participation entries when session leg + HTF MTF agree."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not authority_active(settings):
        return False, "ok", meta

    side_u = _side_u(getattr(candidate, "side", None))
    if side_u not in ("CALL", "PUT"):
        return False, "ok", meta

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    if not _allowed_symbols(sym, settings):
        return False, "ok", meta

    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return False, "ok", meta

    from app.engines.index_tick_helpers import index_trend_breakout

    bo = index_trend_breakout(sym, side_u, snap)
    if bo.get("breakout"):
        meta["sessionIntentBreakout"] = bo
        return False, "ok", meta

    intent = resolve_session_intent(sym, snap, state, settings=settings)
    meta["sessionIntent"] = intent
    if not intent.get("enabled"):
        return False, "ok", meta

    pm_band, pm_meta = _post_win_afternoon_band_active(state, settings=settings)
    if pm_band and not _side_counter_to_participation(side_u, intent):
        # Same-side re-entry after a morning win in the afternoon chop band (26 Nov stack).
        return True, "session_post_win_afternoon_same_side", {**meta, **pm_meta}

    from app.engines.session_slide_open_lane import session_call_near_day_high_blocked

    dh_blocked, dh_reason, dh_meta = session_call_near_day_high_blocked(
        candidate, state, snapshots, settings=settings,
    )
    meta.update(dh_meta)
    if dh_blocked:
        return True, dh_reason, meta

    if not _side_counter_to_participation(side_u, intent):
        return False, "ok", meta

    if intent.get("allowCounterSide") and float(
        getattr(settings, "session_intent_soft_mode_when_allow_counter", 0.0) or 0.0
    ) > 0:
        return False, "ok", meta

    local_pad = _local_pad_from_candidate(candidate)
    meta["sessionIntentLocalPadPct"] = round(local_pad, 2)
    near_cap = float(
        getattr(settings, "session_intent_counter_near_base_max_pct", 8.0) or 8.0
    )
    if local_pad <= near_cap + 1e-6 and intent.get("confidence") != "HIGH":
        return False, "ok", meta

    mtf_side = (intent.get("mtf") or {}).get(side_u) or {}
    min_htf = int(getattr(settings, "session_intent_mtf_min_htf_oppose_counter", 1) or 1)
    htf_oppose = int(mtf_side.get("htfOpposeCount") or 0)
    max_pad = float(
        getattr(settings, "session_intent_counter_max_local_pad_pct", 12.0) or 12.0
    )

    mid_pad_block = (
        intent.get("confidence") == "HIGH"
        and local_pad >= max_pad - 1e-6
    )
    mtf_block = htf_oppose >= min_htf and local_pad > near_cap + 1e-6

    # Tactical 5m bounce must not waive when 15m+1h still oppose participation side on slide/rally
    tactical_only_bounce = (
        bool(mtf_side.get("tacticalOpposes") or mtf_side.get("tactical5mOpposes"))
        and htf_oppose >= min_htf
        and intent.get("confidence") == "HIGH"
        and local_pad > near_cap + 1e-6
    )

    if mid_pad_block or mtf_block or tactical_only_bounce:
        reason = "session_intent_counter_side_mtf"
        if mid_pad_block:
            reason = "session_intent_counter_mid_pad"
        return True, reason, meta

    return False, "ok", meta