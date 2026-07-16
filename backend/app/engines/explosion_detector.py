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
# Intraday low premium — backfill baseline when first tick was mid-rip
_session_low: dict[str, float] = {}
# Intraday peak premium — survives pullbacks so faded rips still show as signals
_session_peak: dict[str, float] = {}
# Peak 3s velocity retained briefly after spike fades
_peak_velocity: dict[str, tuple[float, datetime]] = {}
# Hold BUILDING+ tier briefly after velocity fades (vertical 1-min candle gaps)
_tier_sticky: dict[str, tuple[str, datetime]] = {}
_session_date: Optional[str] = None
MAX_HISTORY = 40  # ~2 min at 3s poll
_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def _roll_session() -> None:
    global _session_date, _session_open, _session_low, _session_peak, _tier_sticky, _peak_velocity
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _session_open.clear()
        _session_low.clear()
        _session_peak.clear()
        _tier_sticky.clear()
        _peak_velocity.clear()


def _open_key(symbol: str, strike: float, side: Side) -> str:
    return f"{symbol.upper()}:{_strike_key(strike, side)}"


def _hist_min_premium(hist: Optional[deque]) -> Optional[float]:
    if not hist:
        return None
    vals = [h[1] for h in hist if h[1] and h[1] > 0]
    return min(vals) if vals else None


def _update_session_low(key: str, premium: float, hist: Optional[deque] = None) -> None:
    if premium <= 0:
        return
    low = _session_low.get(key)
    if low is None or premium < low:
        _session_low[key] = premium
    hist_min = _hist_min_premium(hist)
    if hist_min is not None:
        low = _session_low.get(key, hist_min)
        if hist_min < low:
            _session_low[key] = hist_min


def _effective_session_baseline(key: str, premium: float, hist: Optional[deque] = None) -> float:
    """Use intraday low as open baseline when first tick arrived mid-rip."""
    from app.config import get_settings

    settings = get_settings()
    open_prem = _session_open.get(key, premium)
    _update_session_low(key, premium, hist)
    low = _session_low.get(key, open_prem)
    if not getattr(settings, "session_open_use_intraday_low", True):
        return open_prem
    if low >= open_prem:
        return open_prem
    drop_pct = ((open_prem - low) / open_prem) * 100
    threshold = float(getattr(settings, "session_open_low_backfill_pct", 8.0) or 8.0)
    if drop_pct >= threshold:
        return low
    return open_prem


def _update_peak_velocity(key: str, v3: float) -> float:
    """Retain peak 3s velocity for scoring after vertical spike fades."""
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "velocity_peak_score_boost_enabled", True):
        return v3
    now = datetime.now(IST)
    prev = _peak_velocity.get(key)
    if v3 > 0 and (not prev or v3 >= prev[0]):
        _peak_velocity[key] = (v3, now)
        return v3
    if not prev:
        return v3
    age = (now - prev[1]).total_seconds()
    decay_s = float(getattr(settings, "velocity_peak_decay_seconds", 180) or 180)
    if age <= decay_s:
        return max(v3, prev[0])
    faded = prev[0] * max(0.25, 1.0 - (age - decay_s) / decay_s)
    return max(v3, faded)


def _session_open_move_pct(
    symbol: str,
    strike: float,
    side: Side,
    premium: float,
    hist: Optional[deque] = None,
) -> float:
    """Premium % change since session baseline — catches 60→160 open rips."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    if key not in _session_open and premium > 0:
        _session_open[key] = premium
        _session_peak[key] = premium
        _session_low[key] = premium
        return 0.0
    baseline = _effective_session_baseline(key, premium, hist)
    if baseline <= 0:
        return 0.0
    peak = _session_peak.get(key, premium)
    if premium > peak:
        _session_peak[key] = premium
    return ((premium - baseline) / baseline) * 100


def _session_peak_move_pct(
    symbol: str,
    strike: float,
    side: Side,
    premium: float,
    hist: Optional[deque] = None,
) -> float:
    """Peak premium vs session baseline — keeps rip visible after pullback."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    if key not in _session_open and premium > 0:
        _session_open[key] = premium
        _session_peak[key] = premium
        _session_low[key] = premium
        return 0.0
    baseline = _effective_session_baseline(key, premium, hist)
    if baseline <= 0:
        return 0.0
    peak = max(_session_peak.get(key, premium), premium)
    _session_peak[key] = peak
    return ((peak - baseline) / baseline) * 100


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


def retained_peak_velocity_3s(symbol: str, strike: float, side: Side) -> float:
    """Public accessor — peak 3s velocity retained after vertical spike fades."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    prev = _peak_velocity.get(key)
    if not prev:
        return 0.0
    from app.config import get_settings

    settings = get_settings()
    now = datetime.now(IST)
    age = (now - prev[1]).total_seconds()
    decay_s = float(getattr(settings, "velocity_peak_decay_seconds", 180) or 180)
    if age <= decay_s:
        return float(prev[0])
    return float(prev[0]) * max(0.25, 1.0 - (age - decay_s) / decay_s)


def effective_breakout_velocities(
    event: Any,
) -> tuple[float, float, dict[str, Any]]:
    """
  Live vs retained peak velocities for worst-day breakout gate.
    Uses peak velocity when session peak rip qualifies and live v3 faded.
    """
    from app.config import get_settings

    settings = get_settings()
    meta: dict[str, Any] = {}
    if event is None:
        return 0.0, 0.0, meta

    vel3 = float(getattr(event, "velocity_3s", 0) or 0)
    vel9 = float(getattr(event, "velocity_9s", 0) or 0)
    peak_move = float(getattr(event, "peak_move_pct", 0) or 0)
    peak_v3 = retained_peak_velocity_3s(
        str(getattr(event, "symbol", "") or ""),
        float(getattr(event, "strike", 0) or 0),
        getattr(event, "side", Side.CALL),
    )
    meta.update({
        "liveVelocity3s": vel3,
        "liveVelocity9s": vel9,
        "peakVelocity3s": peak_v3,
        "peakMovePct": peak_move,
    })

    min_peak = float(getattr(settings, "peak_move_explosion_min_pct", 35.0) or 35.0)
    min_vel = float(settings.worst_day_breakout_min_velocity_3s)
    if (
        getattr(settings, "worst_day_breakout_peak_velocity_bypass_enabled", True)
        and peak_move >= min_peak
        and peak_v3 >= min_vel
    ):
        eff3 = max(vel3, peak_v3)
        eff9 = max(vel9, peak_v3 * 1.1)
        meta["peakVelocityBypass"] = True
        meta["effectiveVelocity3s"] = eff3
        meta["effectiveVelocity9s"] = eff9
        return eff3, eff9, meta

    meta["effectiveVelocity3s"] = vel3
    meta["effectiveVelocity9s"] = vel9
    return vel3, vel9, meta


def peak_move_tier_ok(tier: str) -> bool:
    from app.config import get_settings

    settings = get_settings()
    min_tier = str(getattr(settings, "peak_move_explosion_min_tier", "ELITE") or "ELITE").upper()
    return _TIER_RANK.get(str(tier or "").upper(), 0) >= _TIER_RANK.get(min_tier, 4)


def apply_peak_move_score_boost(score: float, peak_move: float, tier: str) -> float:
    """Boost composite score when session peak rip was large but velocity cooled."""
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "peak_move_explosion_bypass_enabled", True):
        return score
    if peak_move < float(getattr(settings, "peak_move_explosion_min_pct", 35.0) or 35.0):
        return score
    if not peak_move_tier_ok(tier):
        return score
    floor = float(getattr(settings, "peak_move_explosion_score_floor", 38.0) or 38.0)
    per_pct = float(getattr(settings, "peak_move_explosion_score_boost_per_pct", 0.12) or 0.12)
    boosted = max(floor, peak_move * per_pct)
    return max(score, min(100.0, boosted))


def apply_velocity_peak_score_boost(
    score: float,
    *,
    v3: float,
    peak_v3: float,
    tier: str,
    peak_move: float = 0.0,
) -> float:
    """Boost score using retained spike velocity when live v3 has faded."""
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "velocity_peak_score_boost_enabled", True):
        return score
    min_v3 = float(getattr(settings, "velocity_peak_min_3s", 2.5) or 2.5)
    if peak_v3 < min_v3:
        return score
    if _TIER_RANK.get(str(tier or "").upper(), 0) < _TIER_RANK["BUILDING"]:
        return score
    blend = float(getattr(settings, "velocity_peak_score_blend", 0.55) or 0.55)
    vel_bonus = min(40.0, max(0.0, peak_v3) * 8.0) * blend
    if peak_move >= float(getattr(settings, "peak_move_explosion_min_pct", 35.0) or 35.0):
        vel_bonus += min(12.0, peak_move * 0.08)
    boosted = score + vel_bonus
    floor = float(getattr(settings, "velocity_peak_score_floor", 42.0) or 42.0)
    return max(score, min(100.0, max(boosted, floor)))


def effective_explosion_min_score(
    *,
    tier: str,
    peak_move_pct: float = 0.0,
    daily_move_pct: float = 0.0,
) -> float:
    """Lower min score when a material session peak rip qualifies for bypass."""
    from app.config import get_settings

    settings = get_settings()
    base = float(settings.aggressive_min_explosion_score)
    if daily_move_pct >= settings.all_day_explosion_session_move_min_pct:
        base = min(base, float(settings.all_day_explosion_min_score))
    if not getattr(settings, "peak_move_explosion_bypass_enabled", True):
        return base
    if peak_move_pct < float(getattr(settings, "peak_move_explosion_min_pct", 35.0) or 35.0):
        return base
    if not peak_move_tier_ok(tier):
        return base
    return min(base, float(getattr(settings, "peak_move_explosion_score_floor", 38.0) or 38.0))


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
            vel_key = _open_key(symbol, strike, side)
            open_move = _session_open_move_pct(symbol, strike, side, premium, hist)
            peak_move = _session_peak_move_pct(symbol, strike, side, premium, hist)
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
                peak_v3 = _update_peak_velocity(vel_key, v3)
                v3_score = max(v3, peak_v3)
            else:
                v3 = _velocity(hist, 1)
                v9 = _velocity(hist, 3)
                v15 = _velocity(hist, 5)
                peak_v3 = _update_peak_velocity(vel_key, v3)
                v3_score = max(v3, peak_v3)
                vol_surge = _volume_surge_with_chain(volume, hist, settings)
                if open_window and open_move >= settings.open_premium_min_move_pct:
                    v3 = max(v3, open_move * 0.25)
                    v9 = max(v9, open_move * 0.65)
                    v15 = max(v15, min(open_move * 0.35, float(getattr(settings, "explosion_exhaustion_v15_pct", 18.0) or 18.0) - 0.5))
                    v3_score = max(v3_score, v3)

            # Composite explosion score — peak velocity retained after fade
            score = (
                min(40, max(0, v3_score) * 8)
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
            peak_min = float(getattr(settings, "peak_move_explosion_min_pct", 35.0) or 35.0)
            if peak_move >= peak_min:
                if peak_move >= 80:
                    tier = "ELITE" if _TIER_RANK.get(tier, 0) < _TIER_RANK["ELITE"] else tier
                elif _TIER_RANK.get(tier, 0) < _TIER_RANK["EXPLODING"]:
                    tier = "EXPLODING"
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
            score = apply_velocity_peak_score_boost(
                score, v3=v3, peak_v3=peak_v3, tier=tier, peak_move=peak_move,
            )
            score = apply_peak_move_score_boost(score, peak_move, tier)

            reason_parts = []
            if v3 >= 2:
                reason_parts.append(f"+{v3:.1f}%/3s")
            if peak_v3 >= 2.5 and peak_v3 > v3 + 0.5:
                reason_parts.append(f"peakV3={peak_v3:.1f}%")
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


def scan_snapshot_explosions(
    snap: Any,
    *,
    expiry_day: bool = False,
) -> list[ExplosionEvent]:
    """Rescan explosions from WS-overlaid heatmap — runs between full REST rebuilds."""
    if not snap or not getattr(snap, "heatmap", None) or not float(getattr(snap, "spot", 0) or 0):
        return []
    atm = float(getattr(snap, "atmStrike", None) or snap.spot)
    chain: list[dict[str, Any]] = []
    for row in snap.heatmap:
        chain.append({
            "strike_price": row.strike,
            "strike": row.strike,
            "call_options": {
                "ltp": row.callLtp,
                "last_price": row.callLtp,
                "volume": int(getattr(row, "callOi", 0) or 0),
            },
            "put_options": {
                "ltp": row.putLtp,
                "last_price": row.putLtp,
                "volume": int(getattr(row, "putOi", 0) or 0),
            },
        })
    return scan_chain_explosions(
        snap.symbol, chain, float(snap.spot), atm, expiry_day=expiry_day,
    )


def refresh_snapshot_explosion_alerts(snap: Any, *, expiry_day: bool = False) -> None:
    """Update explosionAlerts on a cached snapshot using fresh WS LTPs."""
    events = scan_snapshot_explosions(snap, expiry_day=expiry_day)
    snap.explosionAlerts = [event_to_dict(e, snap) for e in events[:15]]


def event_to_dict(e: ExplosionEvent, snap: Optional[Any] = None) -> dict[str, Any]:
    from app.engines.ict_breakout_monitor import analyze_explosion_event_ict
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
    ict = analyze_explosion_event_ict(e, snap)
    tradeable = e.tier in ("EXPLODING", "ELITE") or capture
    if ict.mega_rip or (ict.active and (ict.flat_then_vertical or ict.premium_fvg)):
        tradeable = True
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
        "tradeable": tradeable,
        "morningCapture": morning,
        "afternoonCapture": afternoon,
        "allDayExplosion": all_day,
        "premiumCapture": capture,
        "ictBreakout": ict.active,
        "ictPattern": ict.pattern,
        "ictScore": round(ict.score, 1),
        "ictMegaRip": ict.mega_rip,
        "ictPremiumFvg": ict.premium_fvg,
        "ictFlatThenVertical": ict.flat_then_vertical,
        "ictReasons": ict.reasons,
    }
