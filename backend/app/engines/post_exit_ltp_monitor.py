"""Track contract LTP after each exit to quantify early-exit cost vs tape."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.engines.nx_exit_audit import _highest_n_multiple
from app.engines.snapshot_fast import resolve_trade_premium
from app.models.schemas import PaperTrade, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

_lock = Lock()
_active: dict[str, "PostExitWatch"] = {}
_recent: deque[dict[str, Any]] = deque(maxlen=12)


@dataclass
class PostExitWatch:
    trade_id: str
    symbol: str
    side: str
    strike: float
    entry_premium: float
    exit_premium: float
    exit_reason: str
    lots: int
    closed_at: datetime
    monitor_until: datetime
    session_date: str
    while_open_max_ltp: float
    instrument_key: Optional[str] = None
    post_exit_peak_ltp: float = 0.0
    post_exit_peak_at: Optional[datetime] = None
    ticks: int = 0
    tape_scans: int = 0
    last_tape_scan_mono: float = 0.0
    peak_from_tape: bool = False
    finalized: bool = False

    def monitor_payload(self, *, settings: Settings) -> dict[str, Any]:
        entry = float(self.entry_premium or 0)
        exit_p = float(self.exit_premium or 0)
        peak = float(self.post_exit_peak_ltp or 0)
        max_n = int(getattr(settings, "trade_entry_multiple_capture_max_n", 20) or 20)
        while_n = _highest_n_multiple(entry, self.while_open_max_ltp, max_n=max_n)
        post_n = _highest_n_multiple(entry, peak, max_n=max_n) if peak > 0 else 0
        missed_pts = round(peak - exit_p, 2) if peak > exit_p + 1e-6 else 0.0
        min_pts = float(
            getattr(settings, "post_exit_ltp_monitor_early_min_points", 5.0) or 5.0
        )
        missed_n = max(0, post_n - while_n)
        early = bool(
            missed_pts >= min_pts
            or (missed_n >= int(getattr(settings, "post_exit_ltp_monitor_early_min_missed_n", 1) or 1)
                and post_n >= 2)
        )
        from app.engines.capital_allocator import lot_multiplier

        lot_mult = int(lot_multiplier(self.symbol) or 1)
        opp_inr = round(missed_pts * self.lots * lot_mult, 2) if missed_pts > 0 else 0.0
        return {
            "tradeId": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "strike": self.strike,
            "exitReason": self.exit_reason,
            "entryPremium": round(entry, 2),
            "exitPremium": round(exit_p, 2),
            "whileOpenMaxLtp": round(self.while_open_max_ltp, 2),
            "whileOpenMaxN": while_n,
            "postExitPeakLtp": round(peak, 2) if peak else None,
            "postExitPeakN": post_n,
            "missedPointsAfterExit": missed_pts,
            "opportunityInrFromExit": opp_inr,
            "earlyExitLikely": early,
            "closedAt": self.closed_at.isoformat(),
            "peakAt": self.post_exit_peak_at.isoformat() if self.post_exit_peak_at else None,
            "monitorTicks": self.ticks,
            "tapeScans": self.tape_scans,
            "peakFromTape": self.peak_from_tape,
            "finalizedAt": datetime.now(IST).isoformat(),
        }


def _trade_like(watch: PostExitWatch) -> dict[str, Any]:
    return {
        "symbol": watch.symbol,
        "side": watch.side,
        "strike": watch.strike,
        "entryPremium": watch.entry_premium,
    }


def _note_peak(watch: PostExitWatch, ltp: float, when: datetime, *, from_tape: bool = False) -> None:
    if ltp > watch.post_exit_peak_ltp + 1e-6:
        watch.post_exit_peak_ltp = ltp
        watch.post_exit_peak_at = when
        if from_tape:
            watch.peak_from_tape = True


def _resolve_live_ltp(
    watch: PostExitWatch,
    snap: Optional[SymbolSnapshot],
    *,
    settings: Settings,
) -> Optional[float]:
    if not snap:
        return None
    side = Side.PUT if watch.side == "PUT" else Side.CALL
    ws_age = float(
        getattr(settings, "post_exit_ltp_ws_max_age_seconds", 45.0) or 45.0
    )
    return resolve_trade_premium(
        snap,
        watch.strike,
        side,
        watch.instrument_key,
        max_age_seconds=ws_age,
    )


def _scan_tape_peak_locked(watch: PostExitWatch, *, settings: Settings, until: datetime) -> None:
    from app.engines.nx_exit_audit import tape_contract_peak_after_close

    tail = int(getattr(settings, "post_exit_ltp_tape_tail_bytes", 8_388_608) or 0)
    peak = tape_contract_peak_after_close(
        watch.session_date,
        _trade_like(watch),
        watch.closed_at,
        until=min(until, watch.monitor_until),
        max_bytes=tail if tail > 0 else 0,
    )
    watch.tape_scans += 1
    watch.last_tape_scan_mono = time.monotonic()
    if peak > 0:
        _note_peak(watch, peak, until, from_tape=True)


def register_post_exit_watch(trade: PaperTrade, *, exit_premium: Optional[float] = None) -> None:
    settings = get_settings()
    if not bool(getattr(settings, "post_exit_ltp_monitor_enabled", True)):
        return
    if trade.status != "CLOSED" or not trade.closedAt:
        return
    closed = trade.closedAt
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=IST)
    else:
        closed = closed.astimezone(IST)
    dur = int(getattr(settings, "post_exit_ltp_monitor_seconds", 5400) or 5400)
    dur = max(60, min(dur, 6 * 3600))
    ctx = trade.entryContext or {}
    while_peak = max(
        float(trade.maxLtp or 0),
        float(ctx.get("maxLtp") or 0),
        float(trade.entryPremium or 0) + float(trade.bestPnlPoints or 0),
    )
    side = trade.side.value if hasattr(trade.side, "value") else str(trade.side)
    exit_p = float(exit_premium if exit_premium is not None else trade.currentPremium or 0)
    instrument_key = str(ctx.get("instrumentKey") or "") or None
    watch = PostExitWatch(
        trade_id=str(trade.id),
        symbol=str(trade.symbol).upper(),
        side=str(side).upper(),
        strike=float(trade.strike),
        entry_premium=float(trade.entryPremium or 0),
        exit_premium=exit_p,
        exit_reason=str(trade.exitReason or ""),
        lots=int(trade.lots or 0),
        closed_at=closed,
        monitor_until=closed + timedelta(seconds=dur),
        session_date=trade.sessionDate or closed.strftime("%Y-%m-%d"),
        while_open_max_ltp=while_peak,
        instrument_key=instrument_key,
        post_exit_peak_ltp=exit_p,
        post_exit_peak_at=closed,
    )
    with _lock:
        _active[watch.trade_id] = watch
    logger.info(
        "Post-exit LTP watch started trade=%s %s %s %.0f until %s",
        watch.trade_id,
        watch.symbol,
        watch.side,
        watch.strike,
        watch.monitor_until.strftime("%H:%M"),
    )


def tick_post_exit_monitors(snapshots: dict[str, SymbolSnapshot]) -> list[dict[str, Any]]:
    """Update peaks from live snapshots; finalize expired watches."""
    settings = get_settings()
    if not bool(getattr(settings, "post_exit_ltp_monitor_enabled", True)):
        return []
    now = datetime.now(IST)
    finalized: list[dict[str, Any]] = []
    scan_iv = float(
        getattr(settings, "post_exit_ltp_tape_scan_seconds", 30.0) or 30.0
    )
    scan_iv = max(5.0, min(scan_iv, 300.0))
    mono = time.monotonic()
    with _lock:
        for trade_id, watch in list(_active.items()):
            if watch.finalized:
                continue
            snap = snapshots.get(watch.symbol)
            ltp = _resolve_live_ltp(watch, snap, settings=settings)
            if ltp is not None:
                _note_peak(watch, ltp, now)
                watch.ticks += 1
            elif (
                mono - watch.last_tape_scan_mono >= scan_iv
                or watch.last_tape_scan_mono <= 0
            ):
                try:
                    _scan_tape_peak_locked(watch, settings=settings, until=now)
                except Exception as exc:
                    logger.debug("Post-exit tape scan failed trade=%s: %s", trade_id, exc)
            if now >= watch.monitor_until:
                _scan_tape_peak_locked(watch, settings=settings, until=now)
                finalized.append(_finalize_watch_locked(watch, settings=settings))
    return finalized


def flush_post_exit_monitors_if_session_closed() -> list[dict[str, Any]]:
    """Finalize active watches when the cash session is over (no more tick-fast path)."""
    from app.services.upstox import get_market_phase

    phase = get_market_phase()
    if phase in ("LIVE_MARKET", "POST_MARKET"):
        return []
    return finalize_all_post_exit_monitors()


def finalize_all_post_exit_monitors() -> list[dict[str, Any]]:
    """Force-finalize every active watch (restart / session-end safety)."""
    settings = get_settings()
    now = datetime.now(IST)
    finalized: list[dict[str, Any]] = []
    with _lock:
        for watch in list(_active.values()):
            if watch.finalized:
                continue
            try:
                _scan_tape_peak_locked(watch, settings=settings, until=now)
            except Exception as exc:
                logger.debug("Post-exit tape finalize scan failed trade=%s: %s", watch.trade_id, exc)
            finalized.append(_finalize_watch_locked(watch, settings=settings))
    return finalized


def _finalize_watch_locked(watch: PostExitWatch, *, settings: Settings) -> dict[str, Any]:
    watch.finalized = True
    payload = watch.monitor_payload(settings=settings)
    _active.pop(watch.trade_id, None)
    _recent.appendleft(payload)
    try:
        from app.services import trade_store

        trade_store.merge_closed_trade_post_exit_monitor(
            watch.trade_id,
            watch.session_date,
            payload,
        )
        trade_store.record_post_exit_monitor_report(payload)
    except Exception as exc:
        logger.warning("Post-exit monitor persist failed trade=%s: %s", watch.trade_id, exc)
    if payload.get("earlyExitLikely"):
        try:
            from app.services.radar_learning import record_funnel_event

            record_funnel_event({
                "event": "POST_EXIT_EARLY_EXIT",
                "tradeId": watch.trade_id,
                "symbol": watch.symbol,
                "side": watch.side,
                "strike": watch.strike,
                "exitReason": watch.exit_reason,
                "missedPointsAfterExit": payload.get("missedPointsAfterExit"),
                "postExitPeakLtp": payload.get("postExitPeakLtp"),
                "opportunityInrFromExit": payload.get("opportunityInrFromExit"),
            })
        except Exception:
            pass
        logger.warning(
            "Early exit flag trade=%s reason=%s missed=%.1fpt peak=%.2f",
            watch.trade_id,
            watch.exit_reason,
            float(payload.get("missedPointsAfterExit") or 0),
            float(payload.get("postExitPeakLtp") or 0),
        )
    return payload


def post_exit_monitor_hud() -> dict[str, Any]:
    settings = get_settings()
    with _lock:
        active = [
            {
                "tradeId": w.trade_id,
                "symbol": w.symbol,
                "side": w.side,
                "strike": w.strike,
                "exitReason": w.exit_reason,
                "exitPremium": round(w.exit_premium, 2),
                "postExitPeakLtp": round(w.post_exit_peak_ltp, 2),
                "monitorUntil": w.monitor_until.isoformat(),
                "ticks": w.ticks,
            }
            for w in _active.values()
        ]
        recent = list(_recent)
    return {
        "enabled": bool(getattr(settings, "post_exit_ltp_monitor_enabled", True)),
        "monitorSeconds": int(getattr(settings, "post_exit_ltp_monitor_seconds", 5400) or 5400),
        "active": active,
        "recent": recent,
    }