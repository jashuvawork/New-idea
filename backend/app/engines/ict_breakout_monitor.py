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
    base_premium: float = 0.0
    base_relative_move_pct: float = 0.0
    local_swing_base: bool = False

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
            "basePremium": round(self.base_premium, 2),
            "baseRelativeMovePct": round(self.base_relative_move_pct, 1),
            "localSwingBase": self.local_swing_base,
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


def _detect_flat_base(history: list[tuple[datetime, float, float]], settings) -> tuple[bool, float, float]:
    """Flat consolidation — low variance in premium before breakout.

    Excludes the last 3–4 polls (breakout candles) so the rip itself does not
    destroy the flat-base signal (e.g. 26–28 base then 32/38/45).

    Returns (is_flat, max_dev_pct, base_level) — base_level is the consolidation
    premium the breakout launched from (used for base-relative move measurement).
    """
    if len(history) < 6:
        return False, 0.0, 0.0
    # Drop breakout tail; keep at least 4 base samples.
    trim = 4 if len(history) >= 10 else 3
    base = [h[1] for h in list(history)[:-trim]]
    if len(base) < 4:
        return False, 0.0, 0.0
    avg = sum(base) / len(base)
    if avg <= 0:
        return False, 0.0, 0.0
    max_dev = max(abs(p - avg) / avg * 100 for p in base)
    # Also accept a short rolling window of 5–6 bars with low range.
    if max_dev > settings.ict_flat_base_max_range_pct and len(base) >= 6:
        window = base[-6:]
        wavg = sum(window) / len(window)
        if wavg > 0:
            wdev = max(abs(p - wavg) / wavg * 100 for p in window)
            if wdev <= settings.ict_flat_base_max_range_pct:
                return True, wdev, wavg
    return max_dev <= settings.ict_flat_base_max_range_pct, max_dev, avg


def _detect_local_swing_base(
    history: list[tuple[datetime, float, float]],
    premium: float,
    settings,
) -> tuple[bool, float, float]:
    """Local swing low after a dump — Jul23 SENSEX 76400 PE 14:35 (110→42→45).

    Flat-base detection fails on violent V-bottoms. When recent polls show a
    meaningful dump into a low, measure the new leg from that local low instead
    of the day open / earlier peak.

    Returns (found, local_low, base_relative_move_pct).
    """
    if premium <= 0 or len(history) < 4:
        return False, 0.0, 0.0
    lookback = int(getattr(settings, "ict_local_base_lookback_polls", 16) or 16)
    lookback = max(4, lookback)
    window = list(history)[-lookback:]
    premiums = [float(h[1]) for h in window if float(h[1] or 0) > 0]
    if len(premiums) < 4:
        return False, 0.0, 0.0
    local_low = min(premiums)
    local_high = max(premiums)
    if local_low <= 0:
        return False, 0.0, 0.0
    dump_pct = (local_high - local_low) / local_low * 100.0
    min_dump = float(getattr(settings, "ict_local_base_min_dump_pct", 25.0) or 25.0)
    if dump_pct < min_dump:
        return False, 0.0, 0.0
    # Low should be recent (in the back half of the window) — not a stale morning print.
    low_idx = min(i for i, p in enumerate(premiums) if p <= local_low * 1.001)
    if low_idx < max(0, len(premiums) // 3):
        # Low only at the start of the window with a grind up = prior leg, not a fresh V.
        # Still accept when the current premium has pulled back near that low again.
        near_low = premium <= local_low * 1.35
        if not near_low:
            return False, 0.0, 0.0
    base_rel = (premium - local_low) / local_low * 100.0
    if base_rel < 0:
        base_rel = 0.0
    return True, local_low, base_rel


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
    flat, flat_dev, flat_base = _detect_flat_base(history, settings)
    swing_found, swing_low, swing_rel = _detect_local_swing_base(history, premium, settings)
    # Prefer local swing low after a dump (V-bottom) over flat-base average; otherwise
    # use consolidation base. Day-open % is intentionally not used here.
    local_swing_base = False
    base_level = 0.0
    base_rel_move = 0.0
    if swing_found and swing_low > 0:
        local_swing_base = True
        base_level = swing_low
        base_rel_move = swing_rel
    elif flat and flat_base > 0 and premium > 0:
        base_level = flat_base
        base_rel_move = (premium - flat_base) / flat_base * 100.0
    surge_awaken = volume_surge >= float(
        getattr(settings, "ict_volume_surge_awaken_min", 3.0) or 3.0
    )
    vol_awaken = (
        volume >= settings.explosion_volume_awaken_min
        or "volAwaken" in (reason or "")
        or surge_awaken
    )
    displacement = velocity_3s >= settings.ict_displacement_min_velocity_3s
    early_min = float(getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0)
    early_v3 = float(getattr(settings, "ict_early_vertical_min_velocity_3s", 2.0) or 2.0)
    # Structure / early-window heat: prefer local-base move when we have one.
    structure_move = base_rel_move if base_rel_move > 0 else move
    vertical = move >= settings.ict_vertical_min_session_move_pct
    # Early breakout: flat OR local V-base + heat + ≥28% from that base.
    early_break = (
        (flat or local_swing_base)
        and structure_move >= early_min
        and (
            displacement
            or vol_awaken
            or fvg
            or velocity_3s >= early_v3
        )
    )
    flat_then_vertical = (flat and vertical) or early_break
    mega = move >= settings.ict_mega_rip_min_session_move_pct

    if fvg:
        score += settings.ict_fvg_score_bonus
        reasons.append(f"premium_fvg_{gap_pct:.0f}%")
    if local_swing_base:
        reasons.append(f"local_swing_base_{base_level:.1f}")
    if flat and vertical:
        score += settings.ict_flat_vertical_score_bonus
        reasons.append(f"flat_then_vertical_{flat_dev:.1f}%base")
    elif early_break:
        score += float(getattr(settings, "ict_early_breakout_score_bonus", 16.0) or 16.0)
        src = "local" if local_swing_base and not flat else "flat"
        reasons.append(f"early_{src}_break_{structure_move:.0f}%")
    elif flat and displacement:
        score += settings.ict_flat_vertical_score_bonus * 0.7
        reasons.append("flat_base_breaking")
    if displacement:
        score += 8.0
        reasons.append(f"displacement_v3_{velocity_3s:.1f}")
    if vol_awaken:
        score += 10.0
        reasons.append("volume_awakening" if not surge_awaken else f"volume_surge_{volume_surge:.1f}x")
    if vertical or early_break:
        score += min(25, move * 0.08)
        reasons.append(f"session_rip_{move:.0f}%")
    if mega:
        score += settings.ict_mega_rip_score_bonus
        reasons.append(f"mega_rip_{move:.0f}%")
    if tier in ("EXPLODING", "ELITE"):
        score += 6.0
        reasons.append(f"tier_{tier.lower()}")
    elif tier == "BUILDING" and (early_break or flat_then_vertical):
        score += 4.0
        reasons.append("tier_building_breakout")

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

    # Displacement alone must not activate ICT on tiny session moves (Jul20 +1% noise).
    early_floor = float(getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0)
    immature_floor = float(
        getattr(settings, "explosion_immature_min_session_move_pct", 22.0) or 22.0
    )
    displacement_only_ok = displacement and move >= immature_floor and (flat or vol_awaken or fvg)
    active = (
        mega
        or early_break
        or (fvg and (vertical or early_break or move >= early_floor))
        or flat_then_vertical
        or (
            score >= settings.ict_breakout_min_score
            and (flat_then_vertical or fvg or mega or displacement_only_ok or move >= early_floor)
        )
    )
    pattern = "mega_rip" if mega else (
        "flat_then_vertical" if flat_then_vertical else (
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
        flat_then_vertical=flat_then_vertical,
        displacement=displacement,
        volume_awakening=vol_awaken,
        mega_rip=mega,
        session_move_pct=move,
        velocity_3s=velocity_3s,
        volume_surge=volume_surge,
        base_premium=base_level,
        base_relative_move_pct=base_rel_move,
        local_swing_base=local_swing_base,
    )


def analyze_explosion_event_ict(event: Any, snap: Optional[SymbolSnapshot] = None) -> ICTBreakoutSignal:
    volume = float(getattr(event, "volume", 0) or 0)
    # Event path used to drop absolute volume (always 0) → ICT never saw abs awaken.
    # Fall back to detector history carry-forward when the event field is empty.
    if volume <= 0:
        try:
            from app.engines.explosion_detector import _history, _last_known_volume, _strike_key

            sym = str(getattr(event, "symbol", "") or "")
            side = getattr(event, "side", Side.CALL)
            strike = float(getattr(event, "strike", 0) or 0)
            hist = (_history.get(sym) or {}).get(_strike_key(strike, side))
            if hist:
                volume = _last_known_volume(hist)
        except Exception:
            volume = 0.0
    return analyze_ict_breakout(
        symbol=str(getattr(event, "symbol", "") or ""),
        side=getattr(event, "side", Side.CALL),
        strike=float(getattr(event, "strike", 0) or 0),
        premium=float(getattr(event, "premium", 0) or 0),
        session_move_pct=float(getattr(event, "daily_move_pct", 0) or 0),
        peak_move_pct=float(getattr(event, "peak_move_pct", 0) or 0),
        velocity_3s=float(getattr(event, "velocity_3s", 0) or 0),
        velocity_9s=float(getattr(event, "velocity_9s", 0) or 0),
        volume=volume,
        volume_surge=float(getattr(event, "volume_surge", 0) or 0),
        tier=str(getattr(event, "tier", "") or ""),
        reason=str(getattr(event, "reason", "") or ""),
        snap=snap,
    )


def late_fade_chase_blocked(event: Any, ict: Optional[ICTBreakoutSignal] = None) -> tuple[bool, str]:
    """Block chasing rips that already peaked hard with cooling live velocity (PF killer)."""
    settings = get_settings()
    if not getattr(settings, "ict_late_chase_block_enabled", True):
        return False, ""
    peak = float(getattr(event, "peak_move_pct", 0) or 0)
    daily = float(getattr(event, "daily_move_pct", 0) or 0)
    move = max(peak, daily, float(ict.session_move_pct) if ict else 0.0)
    v3 = float(getattr(event, "velocity_3s", 0) or 0)
    min_peak = float(getattr(settings, "ict_late_chase_min_peak_pct", 75.0) or 75.0)
    max_v3 = float(getattr(settings, "ict_late_chase_max_live_velocity_3s", 1.0) or 1.0)
    early_max = float(getattr(settings, "explosion_early_window_max_move_pct", 55.0) or 55.0)
    local_max = float(
        getattr(settings, "explosion_local_base_chase_max_move_pct", 70.0) or 70.0
    )
    # Fresh local-base leg (flat or V-bottom) still inside the tradeable window —
    # day peak % must not late-fade-block the reclaim (76400 PE at 14:35).
    if (
        ict is not None
        and getattr(settings, "explosion_chase_use_local_base", True)
        and float(getattr(ict, "base_relative_move_pct", 0) or 0) > 0
    ):
        base_rel = float(ict.base_relative_move_pct or 0)
        if base_rel < local_max:
            return False, ""
    # Early flat→vertical still in the capture window may keep a live displacement pass.
    if (
        ict
        and ict.flat_then_vertical
        and move <= early_max
        and (ict.volume_awakening or ict.displacement)
        and v3 >= max_v3
    ):
        return False, ""
    if move >= min_peak and v3 <= max_v3:
        return True, f"ict_late_fade_chase_peak_{move:.0f}%_v3_{v3:.1f}"
    return False, ""


def good_day_ict_capture_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    event: Any = None,
    ict: Optional[ICTBreakoutSignal] = None,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[bool, dict[str, Any]]:
    """ICT capture — AGGRESSIVE max-lots path + all-day early flat→vertical on NORMAL days."""
    settings = get_settings()
    meta: dict[str, Any] = {}

    from app.engines.dual_mode_strategy import resolve_trading_session_mode

    mode, mode_meta = resolve_trading_session_mode(
        state, snapshots, day_mode=day_mode, confidence_tier=confidence_tier,
    )
    meta["tradingMode"] = mode
    meta.update(mode_meta or {})

    if ict is None and event is not None:
        sym = str(getattr(event, "symbol", "") or "").upper()
        snap = snapshots.get(sym)
        ict = analyze_explosion_event_ict(event, snap)

    if ict is None:
        return False, meta

    meta["ict"] = ict.to_dict()

    # Aggressive good-day path (unchanged intent).
    if settings.ict_good_day_capture_enabled and mode == "AGGRESSIVE":
        if ict.mega_rip or (ict.active and ict.score >= settings.ict_good_day_min_score):
            meta["maxProfitCapture"] = True
            meta["capturePath"] = "good_day_aggressive"
            return True, meta
        if ict.flat_then_vertical and ict.session_move_pct >= float(
            getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0
        ):
            meta["maxProfitCapture"] = True
            meta["capturePath"] = "good_day_flat_vertical"
            return True, meta

    early_ok = (
        ict.active
        and ict.flat_then_vertical
        and (
            ict.volume_awakening
            or ict.displacement
            or ict.premium_fvg
            or ict.score >= float(getattr(settings, "ict_all_day_capture_min_score", 30.0) or 30.0)
        )
    )

    # All-day path — NORMAL / AGGRESSIVE: catch 26→70 CE and 12→392 PE style early.
    if getattr(settings, "ict_all_day_capture_enabled", True) and mode != "DEFENSIVE":
        if early_ok or ict.mega_rip:
            # Always mark max-profit so trail skips tiny hard TPs (not only on AGGRESSIVE).
            meta["maxProfitCapture"] = True
            meta["allDayIctCapture"] = True
            meta["capturePath"] = "all_day_flat_vertical"
            meta["lotMultiplier"] = (
                1.0 if mode == "AGGRESSIVE"
                else float(getattr(settings, "ict_all_day_lot_multiplier", 0.85) or 0.85)
            )
            return True, meta

    # DEFENSIVE / worst days — still take clean base→vertical rips (not chase).
    if (
        mode == "DEFENSIVE"
        and getattr(settings, "ict_defensive_base_rip_enabled", True)
        and early_ok
        and not ict.mega_rip
    ):
        max_move = float(getattr(settings, "ict_defensive_base_rip_max_move_pct", 55.0) or 55.0)
        if ict.session_move_pct <= max_move and (ict.volume_awakening or ict.displacement):
            meta["maxProfitCapture"] = True
            meta["allDayIctCapture"] = True
            meta["defensiveBaseRip"] = True
            meta["capturePath"] = "defensive_base_flat_vertical"
            meta["lotMultiplier"] = float(
                getattr(settings, "ict_defensive_base_rip_lot_multiplier", 0.55) or 0.55
            )
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


def _ict_max_profit_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    return bool(
        ctx.get("maxProfitCapture")
        or ctx.get("goodDayIctCapture")
        or ctx.get("allDayIctCapture")
        or ctx.get("ictMegaRip")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("defensiveBaseRip")
    )


def ict_no_progress_seconds(trade: Any, settings=None) -> int:
    """Extended hold for ICT mega rips — ride 8→393 style moves."""
    settings = settings or get_settings()
    ctx = getattr(trade, "entryContext", None) or {}
    if _ict_max_profit_trade(trade) or ctx.get("ictMegaRip") or ctx.get("goodDayIctCapture"):
        return settings.ict_mega_rip_no_progress_seconds
    if ctx.get("ictBreakout"):
        return settings.ict_breakout_no_progress_seconds
    return settings.explosion_no_progress_seconds


def ict_trail_arm_multiplier(trade: Any) -> float:
    ctx = getattr(trade, "entryContext", None) or {}
    settings = get_settings()
    if _ict_max_profit_trade(trade) or ctx.get("ictMegaRip") or ctx.get("goodDayIctCapture"):
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
