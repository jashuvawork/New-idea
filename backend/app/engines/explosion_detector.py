"""Explosion detector — captures premium velocity moments like NIFTY CE +67% runs."""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.engines.premium_filter import premium_in_band
from app.models.schemas import Side

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Rolling premium history: symbol -> strike_key -> deque of (timestamp, premium, volume)
_history: dict[str, dict[str, deque]] = {}
# Session open premium: symbol:side:strike -> first seen premium today
_session_open: dict[str, float] = {}
# Intraday peak premium — survives pullbacks so faded rips still show as signals
_session_peak: dict[str, float] = {}
# Hold BUILDING+ tier briefly after velocity fades (vertical 1-min candle gaps)
_tier_sticky: dict[str, tuple[str, datetime]] = {}
_session_date: Optional[str] = None
MAX_HISTORY = 40  # ~2 min at 3s poll
_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def _roll_session() -> None:
    global _session_date, _session_open, _session_peak, _tier_sticky
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _session_open.clear()
        _session_peak.clear()
        _tier_sticky.clear()


def _open_key(symbol: str, strike: float, side: Side) -> str:
    return f"{symbol.upper()}:{_strike_key(strike, side)}"


def _session_open_move_pct(symbol: str, strike: float, side: Side, premium: float) -> float:
    """Premium % change since first tick today — catches 60→160 open rips."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    if key not in _session_open and premium > 0:
        _session_open[key] = premium
        _session_peak[key] = premium
        return 0.0
    open_prem = _session_open.get(key, 0)
    if open_prem <= 0:
        return 0.0
    peak = _session_peak.get(key, premium)
    if premium > peak:
        _session_peak[key] = premium
    return ((premium - open_prem) / open_prem) * 100


def _session_peak_move_pct(symbol: str, strike: float, side: Side, premium: float) -> float:
    """Peak premium vs session open — keeps rip visible after pullback."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    if key not in _session_open and premium > 0:
        _session_open[key] = premium
        _session_peak[key] = premium
        return 0.0
    open_prem = _session_open.get(key, 0)
    if open_prem <= 0:
        return 0.0
    peak = max(_session_peak.get(key, premium), premium)
    _session_peak[key] = peak
    return ((peak - open_prem) / open_prem) * 100


def _apply_sticky_tier(strike_key: str, tier: str) -> str:
    """Retain BUILDING+ for ~90s so fast vertical candles are not lost between polls."""
    now = datetime.now(IST)
    sticky = _tier_sticky.get(strike_key)
    if sticky:
        sticky_tier, until = sticky
        if now < until and _TIER_RANK.get(sticky_tier, 0) > _TIER_RANK.get(tier, 0):
            tier = sticky_tier
    if _TIER_RANK.get(tier, 0) >= _TIER_RANK["BUILDING"]:
        hold_s = 90 if tier in ("EXPLODING", "ELITE") else 45
        prev = _tier_sticky.get(strike_key)
        best = tier
        if prev and now < prev[1] and _TIER_RANK.get(prev[0], 0) > _TIER_RANK.get(tier, 0):
            best = prev[0]
        _tier_sticky[strike_key] = (best, now + timedelta(seconds=hold_s))
        tier = best
    return tier


def _effective_session_move(open_move: float, peak_move: float) -> float:
    """Use peak move when price faded but intraday rip was material."""
    if peak_move <= open_move:
        return open_move
    if peak_move >= 15 and open_move < peak_move * 0.45:
        return peak_move
    return max(open_move, peak_move * 0.65)


@dataclass
class ExplosionEvent:
    symbol: str
    side: Side
    strike: float
    premium: float
    velocity_3s: float  # % change last poll
    velocity_9s: float  # % change last 3 polls
    velocity_15s: float  # % change last 5 polls
    volume_surge: float  # ratio vs prior avg
    explosion_score: float  # 0-100 composite
    tier: str  # WATCH | BUILDING | EXPLODING | ELITE
    reason: str
    daily_move_pct: float = 0.0
    peak_move_pct: float = 0.0


def _strike_key(strike: float, side: Side) -> str:
    return f"{side.value}:{strike}"


def _record(symbol: str, strike: float, side: Side, premium: float, volume: float = 0) -> None:
    if not premium or premium <= 0:
        return
    if symbol not in _history:
        _history[symbol] = {}
    key = _strike_key(strike, side)
    if key not in _history[symbol]:
        _history[symbol][key] = deque(maxlen=MAX_HISTORY)
    _history[symbol][key].append((datetime.now(IST), premium, volume))


def _velocity(history: deque, polls_back: int) -> float:
    if len(history) < polls_back + 1:
        return 0.0
    current = history[-1][1]
    prior = history[-(polls_back + 1)][1]
    if not prior or prior <= 0:
        return 0.0
    return ((current - prior) / prior) * 100


def _volume_surge(history: deque) -> float:
    if len(history) < 4:
        return 1.0
    recent_vol = sum(h[2] for h in list(history)[-2:]) / 2
    prior_vol = sum(h[2] for h in list(history)[-6:-2]) / max(1, len(list(history)[-6:-2]))
    if prior_vol <= 0:
        return 1.0 if recent_vol > 0 else 1.0
    return recent_vol / prior_vol


def _volume_surge_with_chain(volume: float, history: deque, settings) -> float:
    """Blend poll history with chain volume — catches flat-then-vertical rips at 14:00."""
    hist_surge = _volume_surge(history)
    min_vol = int(getattr(settings, "explosion_volume_awaken_min", 25000) or 25000)
    if volume >= min_vol:
        if hist_surge <= 1.2:
            return max(hist_surge, 2.5)
        return max(hist_surge, 1.8)
    if volume >= min_vol * 0.4 and hist_surge >= 1.5:
        return max(hist_surge, 2.0)
    return hist_surge


def _volume_awakening(
    volume: float,
    v3: float,
    open_move: float,
    settings,
) -> bool:
    """Flat base all session then sudden volume bar — wake before full velocity builds."""
    min_vol = int(getattr(settings, "explosion_volume_awaken_min", 25000) or 25000)
    min_v3 = float(getattr(settings, "explosion_volume_awaken_min_velocity_3s", 1.0) or 1.0)
    if volume < min_vol:
        return False
    return v3 >= min_v3 or open_move >= settings.open_premium_min_move_pct


def resolve_explosion_scan_range(
    symbol: str,
    settings=None,
    *,
    tight_scan: bool | None = None,
) -> float:
    """ATM ± range for chain scan — wider on SENSEX; tighter on expiry session."""
    from app.config import get_settings

    settings = settings or get_settings()
    if tight_scan is None:
        try:
            from app.engines.expiry_day_guards import any_expiry_session_active

            tight_scan = any_expiry_session_active()
        except Exception:
            tight_scan = False

    if tight_scan:
        if symbol.upper() == "SENSEX":
            return float(getattr(settings, "explosion_sensex_worst_day_scan_range", 500))
        return float(getattr(settings, "explosion_worst_day_scan_range", 500))

    base = float(settings.explosion_scan_range)
    if symbol.upper() == "SENSEX":
        base = max(base, float(getattr(settings, "explosion_sensex_scan_range", 1500)))
    try:
        from app.engines.morning_premium_capture import in_all_day_explosion_window

        if in_all_day_explosion_window():
            base *= 1.15
    except Exception:
        pass
    return base


def _premium_ok_for_scan(premium: float, open_move: float, settings) -> bool:
    """Allow sub-min premium when session move is explosive (deep OTM rips)."""
    if premium_in_band(premium, mode="explosion"):
        return True
    min_deep = float(getattr(settings, "explosion_deep_otm_min_premium_inr", 3.0))
    if premium < min_deep:
        return False
    max_prem = settings.explosion_max_premium_inr or settings.max_option_premium_inr
    if open_move >= settings.all_day_explosion_session_move_min_pct:
        return premium <= max(max_prem, 500.0)
    if open_move >= settings.open_premium_min_move_pct:
        return premium <= max_prem
    return False


def scan_chain_explosions(
    symbol: str,
    chain: list[dict[str, Any]],
    spot: float,
    atm: float,
    *,
    expiry_day: bool = False,
) -> list[ExplosionEvent]:
    """
    Scan full chain for premium explosions.
    Matches chart pattern: sudden 3-8% moves in 1-3 min with volume spike.
    """
    from app.config import get_settings
    from app.engines.session_timing import in_open_premium_window

    settings = get_settings()
    open_window = in_open_premium_window()
    events: list[ExplosionEvent] = []
    step = 100
    scan_range = resolve_explosion_scan_range(symbol, settings)
    atm_mult = float(settings.expiry_atm_tier_velocity_mult) if expiry_day else 1.0

    chain_rows = list(chain)
    if expiry_day:
        chain_rows.sort(key=lambda r: abs(float(r.get("strike_price") or r.get("strike") or 0) - atm))

    for row in chain_rows:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(strike - atm) > scan_range:
            continue
        near_atm = expiry_day and abs(float(strike) - atm) <= step

        for side, key, alt in [
            (Side.CALL, "call_options", "CE"),
            (Side.PUT, "put_options", "PE"),
        ]:
            opt = row.get(key, {}) or row.get(alt, {})
            if not opt:
                continue

            premium = opt.get("ltp") or opt.get("last_price") or 0
            volume = opt.get("volume", 0) or 0
            if not premium or premium <= 0:
                continue

            _record(symbol, strike, side, premium, volume)
            key_h = _strike_key(strike, side)
            hist = _history.get(symbol, {}).get(key_h)
            open_move = _session_open_move_pct(symbol, strike, side, premium)
            peak_move = _session_peak_move_pct(symbol, strike, side, premium)
            session_move = _effective_session_move(open_move, peak_move)
            if not _premium_ok_for_scan(premium, max(open_move, session_move), settings):
                continue

            if not hist or len(hist) < 2:
                if not (
                    settings.open_premium_explosion_enabled
                    and open_move >= settings.open_premium_min_move_pct
                ):
                    continue
                v3 = open_move * 0.35
                v9 = open_move * 0.65
                v15 = min(open_move * 0.35, 12.0)
                vol_surge = 1.5
            else:
                v3 = _velocity(hist, 1)
                v9 = _velocity(hist, 3)
                v15 = _velocity(hist, 5)
                vol_surge = _volume_surge_with_chain(volume, hist, settings)
                if open_window and open_move >= settings.open_premium_min_move_pct:
                    v3 = max(v3, open_move * 0.25)
                    v9 = max(v9, open_move * 0.65)
                    v15 = max(v15, min(open_move * 0.35, float(getattr(settings, "explosion_exhaustion_v15_pct", 18.0) or 18.0) - 0.5))

            # Composite explosion score
            score = (
                min(40, max(0, v3) * 8)
                + min(30, max(0, v9) * 5)
                + min(20, max(0, v15) * 3)
                + min(10, (vol_surge - 1) * 10)
            )
            if session_move >= settings.open_premium_min_move_pct:
                score = min(100, score + min(30, session_move * 0.35))
            elif peak_move >= 20:
                score = min(100, score + min(18, peak_move * 0.22))

            # Tier classification — relaxed thresholds at open for premium-led rips
            tier = "WATCH"
            v3_build = 1.5 if open_window else 2.0
            v9_build = 2.5 if open_window else 3.5
            v3_explode = 2.8 if open_window else 3.5
            v9_explode = 4.0 if open_window else 5.0
            if near_atm:
                v3_build *= atm_mult
                v9_build *= atm_mult
                v3_explode *= atm_mult
                v9_explode *= atm_mult
            if session_move >= settings.all_day_explosion_session_move_min_pct:
                v3_build = min(v3_build, 1.8)
                v3_explode = min(v3_explode, 2.5)
                v9_explode = min(v9_explode, 3.5)
            if v3 >= v3_build or v9 >= v9_build:
                tier = "BUILDING"
            if v3 >= v3_explode or v9 >= v9_explode or (v3 >= 2.0 and vol_surge >= 1.8):
                tier = "EXPLODING"
            if v3 >= 5.0 or v9 >= 8.0 or (v3 >= 4.0 and vol_surge >= 2.0):
                tier = "ELITE"
            if session_move >= settings.open_premium_min_move_pct:
                _tier_rank = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}

                def _tier_at_least(current: str, minimum: str) -> str:
                    return minimum if _tier_rank.get(current, 0) < _tier_rank.get(minimum, 0) else current

                if session_move >= 80:
                    tier = "ELITE"
                elif session_move >= 40:
                    tier = _tier_at_least(tier, "EXPLODING")
                elif session_move >= 25:
                    tier = _tier_at_least(tier, "BUILDING")
                reason_parts_open = [f"open+{session_move:.0f}%"]
                if peak_move > session_move + 5:
                    reason_parts_open.append(f"peak+{peak_move:.0f}%")
            else:
                reason_parts_open = []

            awakened = _volume_awakening(volume, v3, max(open_move, session_move), settings)
            if awakened:
                vol_surge = max(vol_surge, 2.0)
                score = min(100, score + 12)
                if tier == "WATCH":
                    tier = "BUILDING"
                if expiry_day and near_atm and v3 >= 1.5:
                    tier = "EXPLODING" if _TIER_RANK.get(tier, 0) < _TIER_RANK["EXPLODING"] else tier
                elif session_move >= settings.open_premium_min_move_pct:
                    tier = "EXPLODING" if tier == "BUILDING" else tier
                reason_parts_open.append(f"volAwaken×{volume // 1000}k")

            tier = _apply_sticky_tier(f"{symbol}:{key_h}", tier)

            if tier == "WATCH" and score < 25 and not awakened:
                if not (peak_move >= 20 and v3 >= 1.2):
                    continue

            # Reward ATM proximity; penalize deep OTM (delta + IV crush risk)
            from app.engines.moneyness import strike_step

            strike_inc = strike_step(symbol)
            dist_steps = abs(strike - atm) / strike_inc if strike_inc else 0
            atm_bonus = 0.0
            if dist_steps <= 1:
                atm_bonus = float(getattr(settings, "explosion_atm_proximity_bonus_max", 8.0))
            elif dist_steps <= 2:
                atm_bonus = float(getattr(settings, "explosion_atm_proximity_bonus_max", 8.0)) * 0.5
            otm_penalty = 0.0
            if (side == Side.CALL and strike > atm) or (side == Side.PUT and strike < atm):
                otm_penalty = min(
                    30.0,
                    dist_steps * float(getattr(settings, "explosion_otm_depth_penalty_per_step", 3.0)),
                )
            score = min(100, max(0, score + atm_bonus - otm_penalty))

            reason_parts = []
            if v3 >= 2:
                reason_parts.append(f"+{v3:.1f}%/3s")
            if v9 >= 3:
                reason_parts.append(f"+{v9:.1f}%/9s")
            if vol_surge >= 1.5:
                reason_parts.append(f"vol×{vol_surge:.1f}")
            reason_parts.extend(reason_parts_open)

            events.append(ExplosionEvent(
                symbol=symbol,
                side=side,
                strike=strike,
                premium=premium,
                velocity_3s=round(v3, 2),
                velocity_9s=round(v9, 2),
                velocity_15s=round(v15, 2),
                volume_surge=round(vol_surge, 2),
                explosion_score=round(score, 1),
                tier=tier,
                reason=" ".join(reason_parts) or "momentum building",
                daily_move_pct=round(session_move, 2),
                peak_move_pct=round(peak_move, 2),
            ))

    events.sort(key=lambda e: ({"ELITE": 4, "EXPLODING": 3, "BUILDING": 2, "WATCH": 1}[e.tier], e.explosion_score), reverse=True)
    return events


def event_to_dict(e: ExplosionEvent) -> dict[str, Any]:
    from app.engines.morning_premium_capture import (
        is_afternoon_capture_event,
        is_all_day_explosion_event,
        is_morning_capture_event,
        is_premium_capture_event,
    )

    morning = is_morning_capture_event(e)
    afternoon = is_afternoon_capture_event(e)
    all_day = is_all_day_explosion_event(e)
    capture = is_premium_capture_event(e)
    return {
        "symbol": e.symbol,
        "side": e.side.value,
        "strike": e.strike,
        "premium": e.premium,
        "velocity3s": e.velocity_3s,
        "velocity9s": e.velocity_9s,
        "velocity15s": e.velocity_15s,
        "volumeSurge": e.volume_surge,
        "explosionScore": e.explosion_score,
        "tier": e.tier,
        "reason": e.reason,
        "dailyMovePct": e.daily_move_pct,
        "peakMovePct": e.peak_move_pct,
        "openPremiumMove": e.daily_move_pct,
        "volumeAwaken": "volAwaken" in (e.reason or ""),
        "tradeable": e.tier in ("EXPLODING", "ELITE") or capture,
        "morningCapture": morning,
        "afternoonCapture": afternoon,
        "allDayExplosion": all_day,
        "premiumCapture": capture,
    }
