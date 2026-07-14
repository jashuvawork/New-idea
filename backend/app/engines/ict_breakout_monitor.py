"""ICT / FVG breakout monitor — flat-then-vertical premium rips like 8→393 PE moves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ICTBreakoutSignal:
    active: bool
    pattern: str
    score: float
    reasons: list[str]
    premium_fvg: bool = False
    flat_then_vertical: bool = False
    displacement: bool = False
    volume_awakening: bool = False
    mega_rip: bool = False
    session_move_pct: float = 0.0
    velocity_3s: float = 0.0
    volume_surge: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "pattern": self.pattern,
            "score": round(self.score, 1),
            "reasons": self.reasons,
            "premiumFvg": self.premium_fvg,
            "flatThenVertical": self.flat_then_vertical,
            "displacement": self.displacement,
            "volumeAwakening": self.volume_awakening,
            "megaRip": self.mega_rip,
            "sessionMovePct": round(self.session_move_pct, 1),
            "velocity3s": round(self.velocity_3s, 1),
            "volumeSurge": round(self.volume_surge, 2),
        }


def premium_poll_history(symbol: str, strike: float, side: Side | str) -> list[tuple[datetime, float, float]]:
    """Read rolling premium poll history for ICT gap detection."""
    from app.engines.explosion_detector import _history, _strike_key

    side_val = side.value if isinstance(side, Side) else str(side).upper()
    key = _strike_key(strike, Side(side_val))
    hist = _history.get(symbol.upper(), {}).get(key)
    if not hist:
        return []
    return list(hist)


def _detect_premium_fvg(history: list[tuple[datetime, float, float]], settings) -> tuple[bool, float]:
    """
    Bullish premium FVG — price gaps up between polls (ICT imbalance on option premium).
    Uses 3-bar gap: low of newest > high of oldest by min gap %.
    """
    if len(history) < 3:
        return False, 0.0
    premiums = [h[1] for h in history[-3:]]
    if premiums[0] <= 0:
        return False, 0.0
    gap_pct = ((premiums[-1] - premiums[0]) / premiums[0]) * 100
    min_gap = settings.ict_fvg_min_gap_pct
    # Classic FVG: middle bar displaced — newest low above oldest high equivalent
    if premiums[-1] > premiums[-2] > premiums[0] and gap_pct >= min_gap:
        return True, gap_pct
    if len(history) >= 2:
        p0, p1 = history[-2][1], history[-1][1]
        if p0 > 0:
            jump = ((p1 - p0) / p0) * 100
            if jump >= min_gap * 1.5:
                return True, jump
    return False, gap_pct


def _detect_flat_base(history: list[tuple[datetime, float, float]], settings) -> tuple[bool, float]:
    """Flat consolidation — low variance in premium before breakout."""
    if len(history) < 6:
        return False, 0.0
    base = [h[1] for h in list(history)[:-2]]
    if not base:
        return False, 0.0
    avg = sum(base) / len(base)
    if avg <= 0:
        return False, 0.0
    max_dev = max(abs(p - avg) / avg * 100 for p in base)
    return max_dev <= settings.ict_flat_base_max_range_pct, max_dev


def analyze_ict_breakout(
    *,
    symbol: str,
    side: Side | str,
    strike: float,
    premium: float,
    session_move_pct: float = 0.0,
    peak_move_pct: float = 0.0,
    velocity_3s: float = 0.0,
    velocity_9s: float = 0.0,
    volume_surge: float = 1.0,
    volume: float = 0.0,
    tier: str = "",
    reason: str = "",
    snap: Optional[SymbolSnapshot] = None,
) -> ICTBreakoutSignal:
    """Score flat-then-vertical / FVG / displacement patterns on option premium."""
    settings = get_settings()
    if not settings.ict_breakout_monitor_enabled:
        return ICTBreakoutSignal(False, "disabled", 0.0, [])

    move = max(session_move_pct, peak_move_pct)
    history = premium_poll_history(symbol, strike, side)
    reasons: list[str] = []
    score = 0.0

    fvg, gap_pct = _detect_premium_fvg(history, settings)
    flat, flat_dev = _detect_flat_base(history, settings)
    vol_awaken = volume >= settings.explosion_volume_awaken_min or "volAwaken" in (reason or "")
    displacement = velocity_3s >= settings.ict_displacement_min_velocity_3s
    vertical = move >= settings.ict_vertical_min_session_move_pct
    mega = move >= settings.ict_mega_rip_min_session_move_pct

    if fvg:
        score += settings.ict_fvg_score_bonus
        reasons.append(f"premium_fvg_{gap_pct:.0f}%")
    if flat and vertical:
        score += settings.ict_flat_vertical_score_bonus
        reasons.append(f"flat_then_vertical_{flat_dev:.1f}%base")
    elif flat and displacement:
        score += settings.ict_flat_vertical_score_bonus * 0.7
        reasons.append("flat_base_breaking")
    if displacement:
        score += 8.0
        reasons.append(f"displacement_v3_{velocity_3s:.1f}")
    if vol_awaken:
        score += 10.0
        reasons.append("volume_awakening")
    if vertical:
        score += min(25, move * 0.08)
        reasons.append(f"session_rip_{move:.0f}%")
    if mega:
        score += settings.ict_mega_rip_score_bonus
        reasons.append(f"mega_rip_{move:.0f}%")
    if tier in ("EXPLODING", "ELITE"):
        score += 6.0
        reasons.append(f"tier_{tier.lower()}")

    if snap and snap.spotChart:
        from app.engines.chart_advanced_analysis import analyze_smc_ict

        chart = snap.spotChart
        ohlc = getattr(chart, "ohlc5m", None) or []
        if len(ohlc) >= 5:
            opens = [float(b.get("open", b.get("o", 0))) for b in ohlc[-20:]]
            highs = [float(b.get("high", b.get("h", 0))) for b in ohlc[-20:]]
            lows = [float(b.get("low", b.get("l", 0))) for b in ohlc[-20:]]
            closes = [float(b.get("close", b.get("c", 0))) for b in ohlc[-20:]]
            if all(closes):
                smc = analyze_smc_ict(opens, highs, lows, closes, float(snap.spot or closes[-1]))
                if smc.get("displacement"):
                    score += 6.0
                    reasons.append("index_displacement")
                if smc.get("inKillZone"):
                    score += 4.0
                    reasons.append(str(smc.get("killZone") or "kill_zone"))
                if smc.get("bos"):
                    score += 5.0
                    reasons.append(str(smc["bos"]))

    active = score >= settings.ict_breakout_min_score or mega or (fvg and vertical)
    pattern = "mega_rip" if mega else (
        "flat_then_vertical" if flat and vertical else (
            "premium_fvg" if fvg else (
                "displacement" if displacement else "watch"
            )
        )
    )

    return ICTBreakoutSignal(
        active=active,
        pattern=pattern,
        score=score,
        reasons=reasons,
        premium_fvg=fvg,
        flat_then_vertical=flat and vertical,
        displacement=displacement,
        volume_awakening=vol_awaken,
        mega_rip=mega,
        session_move_pct=move,
        velocity_3s=velocity_3s,
        volume_surge=volume_surge,
    )


def analyze_explosion_event_ict(event: Any, snap: Optional[SymbolSnapshot] = None) -> ICTBreakoutSignal:
    return analyze_ict_breakout(
        symbol=str(getattr(event, "symbol", "") or ""),
        side=getattr(event, "side", Side.CALL),
        strike=float(getattr(event, "strike", 0) or 0),
        premium=float(getattr(event, "premium", 0) or 0),
        session_move_pct=float(getattr(event, "daily_move_pct", 0) or 0),
        peak_move_pct=float(getattr(event, "peak_move_pct", 0) or 0),
        velocity_3s=float(getattr(event, "velocity_3s", 0) or 0),
        velocity_9s=float(getattr(event, "velocity_9s", 0) or 0),
        volume_surge=float(getattr(event, "volume_surge", 0) or 0),
        tier=str(getattr(event, "tier", "") or ""),
        reason=str(getattr(event, "reason", "") or ""),
        snap=snap,
    )


def good_day_ict_capture_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    event: Any = None,
    ict: Optional[ICTBreakoutSignal] = None,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Good day + ICT mega rip — max lots, extended hold, full gate bypass."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not settings.ict_good_day_capture_enabled:
        return False, meta

    from app.engines.dual_mode_strategy import resolve_trading_session_mode

    mode, mode_meta = resolve_trading_session_mode(
        state, snapshots, day_mode=day_mode, confidence_tier=confidence_tier,
    )
    meta["tradingMode"] = mode
    if mode != "AGGRESSIVE":
        return False, meta

    if ict is None and event is not None:
        sym = str(getattr(event, "symbol", "") or "").upper()
        snap = snapshots.get(sym)
        ict = analyze_explosion_event_ict(event, snap)

    if ict is None:
        return False, meta

    meta["ict"] = ict.to_dict()
    if ict.mega_rip or (ict.active and ict.score >= settings.ict_good_day_min_score):
        meta["maxProfitCapture"] = True
        return True, meta
    if ict.flat_then_vertical and ict.session_move_pct >= settings.ict_vertical_min_session_move_pct:
        meta["maxProfitCapture"] = True
        return True, meta
    return False, meta


def ict_explosion_rank_bonus(ict: ICTBreakoutSignal, trading_mode: str = "NORMAL") -> float:
    if not ict.active:
        return 0.0
    settings = get_settings()
    bonus = min(settings.ict_max_rank_bonus, ict.score * 0.35)
    if trading_mode == "AGGRESSIVE":
        bonus += settings.ict_good_day_rank_bonus
    if ict.mega_rip:
        bonus += settings.ict_mega_rip_rank_bonus
    return bonus


def ict_no_progress_seconds(trade: Any, settings=None) -> int:
    """Extended hold for ICT mega rips — ride 8→393 style moves."""
    settings = settings or get_settings()
    ctx = getattr(trade, "entryContext", None) or {}
    if ctx.get("ictMegaRip") or ctx.get("goodDayIctCapture"):
        return settings.ict_mega_rip_no_progress_seconds
    if ctx.get("ictBreakout"):
        return settings.ict_breakout_no_progress_seconds
    return settings.explosion_no_progress_seconds


def ict_trail_arm_multiplier(trade: Any) -> float:
    ctx = getattr(trade, "entryContext", None) or {}
    settings = get_settings()
    if ctx.get("ictMegaRip") or ctx.get("goodDayIctCapture"):
        return settings.ict_mega_rip_trail_arm_multiplier
    if ctx.get("ictBreakout"):
        return settings.ict_breakout_trail_arm_multiplier
    return 1.0


def ict_monitor_summary(snapshots: dict[str, SymbolSnapshot]) -> dict[str, Any]:
    """Top ICT/FVG breakout signals across symbols — for live dashboard."""
    settings = get_settings()
    if not settings.ict_breakout_monitor_enabled:
        return {"enabled": False, "signals": []}

    from app.engines.explosion_detector import ExplosionEvent

    signals: list[dict[str, Any]] = []
    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            ict_active = bool(alert.get("ictBreakout"))
            ict_score = float(alert.get("ictScore") or 0)
            if not ict_active and ict_score < settings.ict_breakout_min_score * 0.5:
                continue
            event = ExplosionEvent(
                symbol=symbol,
                side=Side(alert["side"]),
                strike=float(alert.get("strike") or 0),
                premium=float(alert.get("premium") or 0),
                velocity_3s=float(alert.get("velocity3s") or 0),
                velocity_9s=float(alert.get("velocity9s") or 0),
                velocity_15s=float(alert.get("velocity15s") or 0),
                volume_surge=float(alert.get("volumeSurge") or 1),
                explosion_score=float(alert.get("explosionScore") or 0),
                tier=str(alert.get("tier") or "WATCH"),
                reason=str(alert.get("reason") or ""),
                daily_move_pct=float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
                peak_move_pct=float(alert.get("peakMovePct") or 0),
            )
            ict = analyze_explosion_event_ict(event, snap)
            if not ict.active and ict.score < settings.ict_breakout_min_score * 0.5:
                continue
            signals.append({
                "symbol": symbol,
                "side": alert.get("side"),
                "strike": alert.get("strike"),
                "premium": alert.get("premium"),
                **ict.to_dict(),
            })

    signals.sort(key=lambda s: (s.get("megaRip", False), s.get("score", 0)), reverse=True)
    return {
        "enabled": True,
        "signalCount": len(signals),
        "activeCount": sum(1 for s in signals if s.get("active")),
        "megaRipCount": sum(1 for s in signals if s.get("megaRip")),
        "topSignal": signals[0] if signals else None,
        "signals": signals[:8],
    }
