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
# Hold peak explosion score briefly — velocity is bursty so raw score oscillates
# (27→71→36 during one sustained rip). Peak-hold stops the score≥gate check from
# flickering below the cutoff mid-move (missed SENSEX 76500 PE Jul23).
_score_sticky: dict[str, tuple[float, datetime]] = {}
_session_date: Optional[str] = None
MAX_HISTORY = 240
PREMIUM_POLL_WINDOW_SECONDS = 120
# Medium-horizon local base: the recent swing-low / support the current leg launched
# from. The 2-min poll history + full-session low can't see it — the session low is the
# far morning dip (overstates the move as a chase), and ICT flat-base needs a tight base.
# This trailing-window low (~30 min, excluding the last breakout seconds) is the true
# "local base" for entry/chase timing (Aug5 24500 PE: 72 vs ~66 local base = ~9%, not
# ~80% off the ~40 session low).
_local_base_hist: dict[str, deque] = {}
LOCAL_BASE_HIST_MAXLEN = 1200  # ~60 min at 3s
LOCAL_BASE_WINDOW_SECONDS = 1800  # 30 min lookback for the local swing low
LOCAL_BASE_EXCLUDE_RECENT_SECONDS = 45  # drop the live breakout tail so base != the rip
LOCAL_BASE_SAMPLE_MIN_SECONDS = 1.5
_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def _roll_session(now: Optional[datetime] = None) -> None:
    global _session_date, _session_open, _session_low, _session_peak, _tier_sticky, _peak_velocity
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    today = current.astimezone(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _history.clear()
        _session_open.clear()
        _session_low.clear()
        _session_peak.clear()
        _tier_sticky.clear()
        _score_sticky.clear()
        _peak_velocity.clear()
        _local_base_hist.clear()


def reset_detector_state_for_tests() -> None:
    """Clear module globals so pytest order does not leak session premiums across tests."""
    global _history, _session_date
    _history.clear()
    _session_open.clear()
    _session_low.clear()
    _session_peak.clear()
    _tier_sticky.clear()
    _score_sticky.clear()
    _peak_velocity.clear()
    _local_base_hist.clear()
    # Keep today's session date so seeded lows are not wiped by the next _roll_session().
    _session_date = datetime.now(IST).strftime("%Y-%m-%d")


def _open_key(symbol: str, strike: float, side: Side) -> str:
    return f"{symbol.upper()}:{_strike_key(strike, side)}"


def _hist_min_premium(hist: Optional[deque]) -> Optional[float]:
    if not hist:
        return None
    vals = [h[1] for h in hist if h[1] and h[1] > 0]
    return min(vals) if vals else None


def session_move_min_baseline(settings: Any = None) -> float:
    """Minimum premium allowed as open/low baseline (blocks fake +8873% ticks)."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    return float(getattr(settings, "session_move_min_baseline_premium", 5.0) or 5.0)


def _is_meaningful_premium(premium: float, settings: Any = None) -> bool:
    return float(premium or 0) >= session_move_min_baseline(settings)


def _hist_min_meaningful_premium(hist: Optional[deque], settings: Any = None) -> Optional[float]:
    floor = session_move_min_baseline(settings)
    if not hist:
        return None
    vals = [float(p) for _, p, *_ in hist if float(p or 0) >= floor]
    return min(vals) if vals else None


def _hist_earliest_premium(hist: Optional[deque], *, meaningful_only: bool = False) -> Optional[float]:
    if not hist:
        return None
    floor = session_move_min_baseline() if meaningful_only else 0.0
    for _, prem, _ in hist:
        if prem and prem > 0 and float(prem) >= floor:
            return float(prem)
    return None


def _retrofit_baseline_from_spike(
    key: str,
    premium: float,
    hist: Optional[deque],
    v3: float,
    vol_surge: float = 1.0,
) -> None:
    """Lower session open when a single poll shows a vertical spike — fixes 36% vs 68% peak."""
    from app.config import get_settings

    settings = get_settings()
    if premium <= 0:
        return

    earliest = _hist_earliest_premium(hist, meaningful_only=True)
    if earliest is not None:
        open_prem = _session_open.get(key)
        if open_prem is None or earliest < open_prem:
            _session_open[key] = earliest

    spike_min = float(getattr(settings, "spike_velocity_baseline_min_pct", 12.0) or 12.0)
    if hist and len(hist) >= 2 and v3 >= spike_min:
        prior = float(hist[-2][1] or 0)
        if _is_meaningful_premium(prior, settings) and prior < premium:
            open_prem = _session_open.get(key, premium)
            if prior < open_prem:
                _session_open[key] = prior
            low = _session_low.get(key, prior)
            if prior < low:
                _session_low[key] = prior

    if not getattr(settings, "volume_spike_baseline_enabled", True):
        return
    min_surge = float(getattr(settings, "volume_spike_baseline_min_surge", 3.5) or 3.5)
    if vol_surge < min_surge:
        return
    hist_min = _hist_min_meaningful_premium(hist, settings)
    if hist_min is None or hist_min <= 0:
        return
    open_prem = _session_open.get(key, premium)
    if hist_min < open_prem:
        _session_open[key] = hist_min
    low = _session_low.get(key, hist_min)
    if hist_min < low:
        _session_low[key] = hist_min

def _update_session_low(key: str, premium: float, hist: Optional[deque] = None) -> None:
    from app.config import get_settings

    settings = get_settings()
    if not _is_meaningful_premium(premium, settings):
        # Still allow hist to supply a meaningful low; ignore micro-tick prints.
        hist_min = _hist_min_meaningful_premium(hist, settings)
        if hist_min is not None:
            low = _session_low.get(key)
            if low is None or hist_min < low:
                _session_low[key] = hist_min
        return
    low = _session_low.get(key)
    if low is None or premium < low:
        _session_low[key] = premium
    hist_min = _hist_min_meaningful_premium(hist, settings)
    if hist_min is not None:
        low = _session_low.get(key, hist_min)
        if hist_min < low:
            _session_low[key] = hist_min


def _effective_session_baseline(key: str, premium: float, hist: Optional[deque] = None) -> float:
    """Use intraday low as open baseline when first tick arrived mid-rip."""
    from app.config import get_settings

    settings = get_settings()
    floor = session_move_min_baseline(settings)
    open_prem = _session_open.get(key, premium)
    if open_prem < floor:
        hist_min = _hist_min_meaningful_premium(hist, settings)
        if hist_min is not None:
            open_prem = hist_min
            _session_open[key] = hist_min
        elif _is_meaningful_premium(premium, settings):
            open_prem = premium
            _session_open[key] = premium
        else:
            return 0.0
    _update_session_low(key, premium, hist)
    low = _session_low.get(key, open_prem)
    if low < floor:
        low = open_prem
    if not getattr(settings, "session_open_use_intraday_low", True):
        return open_prem
    if low >= open_prem:
        return open_prem
    drop_pct = ((open_prem - low) / open_prem) * 100
    threshold = float(getattr(settings, "session_open_low_backfill_pct", 8.0) or 8.0)
    if drop_pct >= threshold:
        return low
    return open_prem


def session_low_relative_move_pct(
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
) -> float:
    """% above today's meaningful session low — V-bottom / reclaim timing metric."""
    _roll_session()
    if not _is_meaningful_premium(premium):
        return 0.0
    if side is None or not symbol:
        return 0.0
    side_val = side if isinstance(side, Side) else Side(str(side).upper())
    key = _open_key(symbol, strike, side_val)
    low = float(_session_low.get(key) or 0)
    if not _is_meaningful_premium(low):
        return 0.0
    return ((float(premium) - low) / low) * 100.0


def get_session_low_premium(symbol: str, strike: float, side: Side | str) -> float:
    _roll_session()
    if side is None or not symbol:
        return 0.0
    side_val = side if isinstance(side, Side) else Side(str(side).upper())
    key = _open_key(symbol, strike, side_val)
    low = float(_session_low.get(key) or 0)
    return low if _is_meaningful_premium(low) else 0.0


def prior_close_from_option_leg(opt: dict[str, Any] | None) -> float:
    """Extract previous-session close / day open from a normalized option leg."""
    if not isinstance(opt, dict):
        return 0.0
    ohlc = opt.get("ohlc") or opt.get("OHLC") or {}
    for key in (
        "prev_close",
        "prevClose",
        "close",
        "previous_close",
        "day_close",
    ):
        raw = opt.get(key)
        if raw is None:
            raw = ohlc.get(key) if isinstance(ohlc, dict) else None
        try:
            val = float(raw or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            return val
    for key in ("open", "day_open"):
        raw = opt.get(key)
        if raw is None:
            raw = ohlc.get("open") if isinstance(ohlc, dict) else None
        try:
            val = float(raw or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            return val
    return 0.0


def day_extremes_from_option_leg(opt: dict[str, Any] | None) -> tuple[float, float]:
    """Extract session day low/high from a normalized option leg (chain OHLC).

    Sparse LTP polls miss V-bottom troughs and spike peaks (Aug12 SENSEX 77800 PE
    ~120→238). Chain day low/high survive those gaps.
    """
    if not isinstance(opt, dict):
        return 0.0, 0.0
    ohlc = opt.get("ohlc") or opt.get("OHLC") or {}
    low = 0.0
    high = 0.0
    for key in ("day_low", "low", "dayLow"):
        raw = opt.get(key)
        if raw is None and isinstance(ohlc, dict):
            raw = ohlc.get("low") if key != "dayLow" else ohlc.get("low")
        try:
            val = float(raw or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            low = val
            break
    for key in ("day_high", "high", "dayHigh"):
        raw = opt.get(key)
        if raw is None and isinstance(ohlc, dict):
            raw = ohlc.get("high")
        try:
            val = float(raw or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            high = val
            break
    return low, high


def apply_day_extremes_baseline(
    key: str,
    premium: float,
    day_low: float,
    day_high: float,
) -> bool:
    """Deepen session low / raise session peak from chain day OHLC extremes.

    Never raises the low or lowers the peak. Ignores micro-tick extremes.
    """
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "session_day_ohlc_extremes_enabled", True)):
        return False
    changed = False
    floor = session_move_min_baseline(settings)
    # Sanity: day extreme must be near the live premium band (reject bad chain ticks).
    max_dev = float(getattr(settings, "session_day_ohlc_max_dev_mult", 8.0) or 8.0)
    prem = float(premium or 0)

    if day_low >= floor and (prem <= 0 or day_low <= prem * max_dev):
        # Also reject absurd lows far below live premium (stale/wrong contract).
        if prem <= 0 or day_low >= prem / max_dev:
            cur_low = _session_low.get(key)
            if cur_low is None or day_low < cur_low:
                _session_low[key] = float(day_low)
                changed = True
            # If open was seeded mid-rip above the true trough, backfill open toward low
            # when the dump is meaningful (same spirit as session_open_use_intraday_low).
            open_prem = _session_open.get(key)
            if open_prem is not None and day_low < open_prem:
                drop_pct = ((open_prem - day_low) / open_prem) * 100.0
                threshold = float(getattr(settings, "session_open_low_backfill_pct", 8.0) or 8.0)
                if drop_pct >= threshold:
                    _session_open[key] = float(day_low)
                    changed = True

    if day_high >= floor and (prem <= 0 or day_high >= prem / max_dev):
        if prem <= 0 or day_high <= prem * max_dev:
            cur_peak = _session_peak.get(key)
            if cur_peak is None or day_high > cur_peak:
                _session_peak[key] = float(day_high)
                changed = True
    return changed


def apply_prior_close_baseline(
    key: str,
    premium: float,
    prior_close: float,
) -> bool:
    """
    Seed/lower session baseline from option prev-close on open-gap rips.

    First LTP after a gap (90→270) must not become the baseline — that under-reports
    session move as ~0–8% and hides ELITE ITM CE/PE.
    """
    from app.config import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "open_gap_prev_close_baseline_enabled", True)):
        return False
    if prior_close <= 0 or premium <= 0:
        return False
    # Micro prev-close seeds invent fake mega-rips (₹0.28 → ₹25 = +8873%).
    if not _is_meaningful_premium(prior_close, settings):
        return False
    min_gap = float(getattr(settings, "open_gap_baseline_min_gap_pct", 15.0) or 15.0)
    gap_pct = ((premium - prior_close) / prior_close) * 100.0
    if gap_pct < min_gap:
        return False

    cur = _session_open.get(key)
    changed = False
    if cur is None or prior_close < cur:
        _session_open[key] = prior_close
        changed = True
    low = _session_low.get(key, prior_close)
    candidates = [low, prior_close]
    if _is_meaningful_premium(premium, settings):
        candidates.append(premium)
    _session_low[key] = min(candidates)
    peak = _session_peak.get(key, premium)
    _session_peak[key] = max(peak, premium)
    return changed


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
    *,
    v3: float = 0.0,
    vol_surge: float = 1.0,
    prior_close: float = 0.0,
    day_low: float = 0.0,
    day_high: float = 0.0,
) -> float:
    """Premium % change since session baseline — catches 60→160 open rips."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    seeded = apply_prior_close_baseline(key, premium, prior_close)
    apply_day_extremes_baseline(key, premium, day_low, day_high)
    if key not in _session_open and premium > 0:
        # Never seed open/low from illiquid micro-ticks.
        if not _is_meaningful_premium(premium):
            return 0.0
        _session_open[key] = premium
        _session_peak[key] = premium
        _session_low[key] = premium
        # Re-apply day extremes after first seed so a mid-rip first LTP still
        # deepens to the chain trough / raises to the chain peak.
        apply_day_extremes_baseline(key, premium, day_low, day_high)
        # First sample with no prior-close seed → 0% until next tick unless
        # day-low backfilled the open (then report live vs trough immediately).
        baseline = float(_session_open.get(key) or premium)
        if baseline > 0 and premium > baseline:
            peak = max(_session_peak.get(key, premium), premium)
            _session_peak[key] = peak
            return ((premium - baseline) / baseline) * 100
        return 0.0
    if seeded and prior_close > 0 and _is_meaningful_premium(prior_close):
        # Immediate open-gap read on first poll that carries prev-close.
        baseline = float(_session_open.get(key) or prior_close)
        peak = max(_session_peak.get(key, premium), premium)
        _session_peak[key] = peak
        return ((premium - baseline) / baseline) * 100
    _retrofit_baseline_from_spike(key, premium, hist, v3, vol_surge)
    apply_day_extremes_baseline(key, premium, day_low, day_high)
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
    *,
    v3: float = 0.0,
    vol_surge: float = 1.0,
    prior_close: float = 0.0,
    day_low: float = 0.0,
    day_high: float = 0.0,
) -> float:
    """Peak premium vs session baseline — keeps rip visible after pullback."""
    _roll_session()
    key = _open_key(symbol, strike, side)
    seeded = apply_prior_close_baseline(key, premium, prior_close)
    apply_day_extremes_baseline(key, premium, day_low, day_high)
    if key not in _session_open and premium > 0:
        if not _is_meaningful_premium(premium):
            return 0.0
        _session_open[key] = premium
        _session_peak[key] = premium
        _session_low[key] = premium
        apply_day_extremes_baseline(key, premium, day_low, day_high)
        baseline = float(_session_open.get(key) or premium)
        peak = max(_session_peak.get(key, premium), premium)
        _session_peak[key] = peak
        if baseline > 0 and peak > baseline:
            return ((peak - baseline) / baseline) * 100
        return 0.0
    if seeded and prior_close > 0 and _is_meaningful_premium(prior_close):
        baseline = float(_session_open.get(key) or prior_close)
        peak = max(_session_peak.get(key, premium), premium)
        _session_peak[key] = peak
        return ((peak - baseline) / baseline) * 100
    _retrofit_baseline_from_spike(key, premium, hist, v3, vol_surge)
    apply_day_extremes_baseline(key, premium, day_low, day_high)
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


def _apply_sticky_score(strike_key: str, score: float, tier: str) -> float:
    """Peak-hold explosion score for a short window so bursty velocity doesn't
    flicker it below entry gates during a sustained rip. Holds for BUILDING+
    (early ICT window) and EXPLODING/ELITE; decays after the window."""
    from app.config import get_settings

    settings = get_settings()
    if not getattr(settings, "explosion_score_sticky_enabled", True):
        return score
    hold_s = float(getattr(settings, "explosion_score_sticky_seconds", 45.0) or 45.0)
    now = datetime.now(IST)
    prev = _score_sticky.get(strike_key)
    held = score
    if prev and now < prev[1]:
        held = max(score, prev[0])
    # Retain for BUILDING+ so early ICT flat→vertical doesn't flicker below gates.
    if _TIER_RANK.get(str(tier or "").upper(), 0) >= _TIER_RANK["BUILDING"] or held > score:
        _score_sticky[strike_key] = (held, now + timedelta(seconds=hold_s))
    return round(held, 1)


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
    # Absolute chain volume at detection (0 when unknown). Forwarded to ICT analyze.
    volume: float = 0.0


def _strike_key(strike: float, side: Side) -> str:
    # Normalize so 24400 and 24400.0 share one history key.
    return f"{side.value}:{float(strike)}"


def _last_known_volume(history: deque) -> float:
    for _, _, prev_vol in reversed(history):
        if prev_vol and float(prev_vol) > 0:
            return float(prev_vol)
    return 0.0


def _record(symbol: str, strike: float, side: Side, premium: float, volume: float = 0) -> None:
    if not premium or premium <= 0:
        return
    symbol = symbol.upper()
    # Roll before reading/appending history so the first tick of a new session cannot
    # calculate "3s" velocity against yesterday's final premium.
    _roll_session()
    if symbol not in _history:
        _history[symbol] = {}
    key = _strike_key(strike, side)
    if key not in _history[symbol]:
        _history[symbol][key] = deque(maxlen=MAX_HISTORY)
    hist = _history[symbol][key]
    # WS heatmap rescans pass volume=0 (no bar volume). Do NOT zero the series —
    # that collapses volume_surge and drops ICT volume_awakening mid-rip (Jul23).
    vol = float(volume or 0)
    if vol <= 0 and hist:
        vol = _last_known_volume(hist)
    now = datetime.now(IST)
    hist.append((now, premium, vol))
    _record_local_base(key_for_symbol(symbol, key), now, premium)


def key_for_symbol(symbol: str, strike_key: str) -> str:
    return f"{symbol.upper()}:{strike_key}"


def _record_local_base(full_key: str, ts: datetime, premium: float) -> None:
    """Append to the medium-horizon local-base history and evict stale entries."""
    if not premium or premium <= 0:
        return
    dq = _local_base_hist.get(full_key)
    if dq is None:
        dq = deque(maxlen=LOCAL_BASE_HIST_MAXLEN)
        _local_base_hist[full_key] = dq
    elapsed = (ts - dq[-1][0]).total_seconds() if dq else LOCAL_BASE_SAMPLE_MIN_SECONDS
    if dq and 0 <= elapsed < LOCAL_BASE_SAMPLE_MIN_SECONDS:
        dq[-1] = (ts, min(float(dq[-1][1]), float(premium)))
    else:
        dq.append((ts, float(premium)))
    cutoff = ts - timedelta(seconds=LOCAL_BASE_WINDOW_SECONDS + 300)
    while dq and dq[0][0] < cutoff:
        dq.popleft()


def local_base_premium(
    symbol: str,
    strike: float,
    side: Side | str,
    *,
    window_seconds: Optional[int] = None,
    exclude_recent_seconds: Optional[int] = None,
) -> float:
    """Recent swing-low / support the current leg launched from (local base).

    Trailing-window minimum over ~30 min, excluding the last breakout seconds so the
    base is the consolidation, not the rip itself. This is the local pad for entry/chase
    timing — far more accurate than the full-session low on a choppy base.
    """
    if side is None or not symbol:
        return 0.0
    side_val = side if isinstance(side, Side) else Side(str(side).upper())
    full_key = _open_key(symbol, strike, side_val)
    dq = _local_base_hist.get(full_key)
    if not dq:
        return 0.0
    window = int(window_seconds or LOCAL_BASE_WINDOW_SECONDS)
    excl = int(
        exclude_recent_seconds
        if exclude_recent_seconds is not None
        else LOCAL_BASE_EXCLUDE_RECENT_SECONDS
    )
    now = dq[-1][0]
    lo_cut = now - timedelta(seconds=window)
    hi_cut = now - timedelta(seconds=excl)
    vals = [p for (ts, p) in dq if lo_cut <= ts <= hi_cut and _is_meaningful_premium(p)]
    if not vals:
        # The only samples are in the live breakout tail, so the launch pad is unknown.
        # Treating the rip itself as its base understates chase distance.
        return 0.0
    return min(vals) if vals else 0.0


def post_close_base_reacceleration(
    symbol: str,
    strike: float,
    side: Side | str,
    *,
    closed_at: datetime,
    current_premium: float,
    velocity_3s: float,
    min_base_samples: int = 3,
    min_base_span_seconds: float = 6.0,
    base_cluster_tolerance_pct: float = 5.0,
    min_reacceleration_pct: float = 8.0,
    min_velocity_3s: float = 1.5,
) -> tuple[bool, dict[str, float | int | bool]]:
    """Prove a fresh post-close base and renewed acceleration from detector history."""
    side_val = side if isinstance(side, Side) else Side(str(side).upper())
    samples = list(_local_base_hist.get(_open_key(symbol, strike, side_val)) or ())
    if closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=IST)
    fresh = [
        (ts if ts.tzinfo else ts.replace(tzinfo=IST), float(premium))
        for ts, premium in samples
        if (ts if ts.tzinfo else ts.replace(tzinfo=IST)) > closed_at
        and float(premium or 0) > 0
    ]
    meta: dict[str, float | int | bool] = {
        "freshSamples": len(fresh),
        "newBaseReacceleration": False,
    }
    if len(fresh) < max(2, int(min_base_samples)):
        return False, meta

    base = min(premium for _, premium in fresh)
    tolerance = base * (1.0 + max(0.0, base_cluster_tolerance_pct) / 100.0)
    base_samples = [(ts, premium) for ts, premium in fresh if premium <= tolerance]
    base_span = (
        (base_samples[-1][0] - base_samples[0][0]).total_seconds()
        if len(base_samples) >= 2
        else 0.0
    )
    reacceleration = (
        (float(current_premium or 0) - base) / base * 100.0
        if base > 0
        else 0.0
    )
    proven = bool(
        len(base_samples) >= max(2, int(min_base_samples))
        and base_span >= max(0.0, float(min_base_span_seconds))
        and reacceleration >= max(0.0, float(min_reacceleration_pct))
        and float(velocity_3s or 0) >= float(min_velocity_3s)
    )
    meta.update(
        {
            "basePremium": round(base, 2),
            "baseSamples": len(base_samples),
            "baseSpanSeconds": round(base_span, 1),
            "reaccelerationPct": round(reacceleration, 2),
            "velocity3s": round(float(velocity_3s or 0), 3),
            "newBaseReacceleration": proven,
        }
    )
    return proven, meta


def local_base_relative_move_pct(
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
    *,
    window_seconds: Optional[int] = None,
    exclude_recent_seconds: Optional[int] = None,
) -> float:
    """% the premium is above its recent local base (swing low)."""
    if not _is_meaningful_premium(premium):
        return 0.0
    base = local_base_premium(
        symbol, strike, side,
        window_seconds=window_seconds, exclude_recent_seconds=exclude_recent_seconds,
    )
    if not _is_meaningful_premium(base) or premium <= base:
        return 0.0
    return ((float(premium) - base) / base) * 100.0


def _velocity(history: deque, polls_back: int) -> float:
    if len(history) < 2 or polls_back <= 0:
        return 0.0
    current_row = history[-1]
    try:
        target = current_row[0] - timedelta(seconds=float(polls_back * 3))
        prior_row = next(
            row for row in reversed(list(history)[:-1])
            if row[0] <= target
        )
    except (AttributeError, TypeError, StopIteration):
        return 0.0
    current = current_row[1]
    prior = prior_row[1]
    if not prior or prior <= 0:
        return 0.0
    # Poll-count velocity is only valid while samples are fresh. After a feed/network
    # pause, treating a multi-minute move as 3s/9s heat creates false explosions.
    try:
        elapsed = (current_row[0] - prior_row[0]).total_seconds()
    except (AttributeError, TypeError):
        return 0.0
    max_elapsed = max(12.0, float(polls_back * 6 + 6))
    if elapsed < 0 or elapsed > max_elapsed:
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
    min_v3 = float(
        getattr(settings, "explosion_volume_awaken_min_velocity_3s", 1.0) or 1.0
    )
    live_v3 = _velocity(history, 1)
    # Option-chain volume is cumulative for the day. High absolute volume alone is not
    # a new surge; require either measurable premium heat or expansion in poll history.
    chain_volume_live = live_v3 >= min_v3 or hist_surge > 1.2
    if volume >= min_vol and chain_volume_live:
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
    """
    ATM ± range for chain scan — wider on SENSEX.

    On expiry with ITM monitor enabled, keep a wide enough band to cover most
    ITM CE/PE (not the old worst-day 500pt clamp that missed deep ITM rips).
    Worst-day tight scan only applies when expiry ITM monitor is off.
    """
    from app.config import get_settings

    settings = settings or get_settings()
    if tight_scan is None:
        try:
            from app.engines.expiry_day_guards import any_expiry_session_active

            tight_scan = any_expiry_session_active()
        except Exception:
            tight_scan = False

    if tight_scan:
        itm_monitor = bool(getattr(settings, "expiry_itm_monitor_enabled", True))
        if itm_monitor:
            try:
                from app.engines.expiry_day_guards import resolve_expiry_itm_scan_range

                return resolve_expiry_itm_scan_range(symbol)
            except Exception:
                if symbol.upper() == "SENSEX":
                    return float(getattr(settings, "expiry_sensex_itm_scan_range", 1200) or 1200)
                return float(getattr(settings, "expiry_itm_scan_range", 800) or 800)
        if symbol.upper() == "SENSEX":
            return float(getattr(settings, "explosion_sensex_worst_day_scan_range", 500) or 500)
        return float(getattr(settings, "explosion_worst_day_scan_range", 500) or 500)

    base = float(getattr(settings, "explosion_scan_range", 800) or 800)
    if symbol.upper() == "SENSEX":
        sensex_range = float(getattr(settings, "explosion_sensex_scan_range", 1500) or 1500)
        base = max(base, sensex_range)
    try:
        from app.engines.morning_premium_capture import in_all_day_explosion_window

        if in_all_day_explosion_window():
            base *= 1.15
    except Exception:
        pass
    return base


def _premium_ok_for_scan(premium: float, open_move: float, settings) -> bool:
    """Allow sub-min premium when session move is explosive (deep OTM rips).

    When ATM+ITM-only scan is on, never bypass the main premium band — cheap
    deep-OTM noise must not dominate radar over near-base ATM/ITM.
    """
    if premium_in_band(premium, mode="explosion"):
        return True
    if bool(getattr(settings, "explosion_scan_atm_itm_only", True)):
        return False
    min_deep = float(getattr(settings, "explosion_deep_otm_min_premium_inr", 18.0))
    if premium < min_deep:
        return False
    max_prem = settings.explosion_max_premium_inr or settings.max_option_premium_inr
    if open_move >= settings.all_day_explosion_session_move_min_pct:
        return premium <= max(max_prem, 500.0)
    if open_move >= settings.open_premium_min_move_pct:
        return premium <= max_prem
    return False


def _shallow_otm_monitor_eligible(
    side: Side,
    strike: float,
    spot: float,
    atm: float,
    premium: float,
    volume: float,
    symbol: str,
    settings: Any,
) -> bool:
    """Retain liquid tape one listed strike beyond the configured ATM band."""
    from app.engines.moneyness import classify_moneyness, strike_step

    if classify_moneyness(side, strike, spot, symbol=symbol, atm=atm) != "OTM":
        return False
    step = strike_step(symbol)
    tolerance = float(
        getattr(settings, "moneyness_atm_tolerance_points", step) or step
    )
    max_steps = int(
        getattr(settings, "explosion_shallow_otm_history_steps", 1) or 1
    )
    if abs(float(strike) - float(atm)) > tolerance + step * max(0, max_steps):
        return False
    if not premium_in_band(premium, mode="explosion"):
        return False
    min_volume = float(
        getattr(settings, "explosion_shallow_otm_history_min_volume", 25000) or 25000
    )
    # WS heatmap overlays do not carry volume. Zero therefore means unknown, not
    # illiquid; an explicit REST volume below the floor remains excluded.
    return float(volume or 0) <= 0 or float(volume) >= min_volume


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
    symbol = symbol.upper()
    open_window = in_open_premium_window()
    events: list[ExplosionEvent] = []
    step = 100
    scan_range = resolve_explosion_scan_range(symbol, settings)
    atm_mult = float(settings.expiry_atm_tier_velocity_mult) if expiry_day else 1.0

    chain_rows = list(chain)
    if expiry_day:
        chain_rows.sort(key=lambda r: abs(float(r.get("strike_price") or r.get("strike") or 0) - atm))

    atm_itm_only = bool(getattr(settings, "explosion_scan_atm_itm_only", True))

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

            if atm_itm_only and spot and atm:
                from app.engines.moneyness import classify_moneyness

                money = classify_moneyness(
                    side, float(strike), float(spot), symbol=symbol, atm=float(atm),
                )
                if money == "OTM" and not _shallow_otm_monitor_eligible(
                    side,
                    float(strike),
                    float(spot),
                    float(atm),
                    float(premium),
                    float(volume),
                    symbol,
                    settings,
                ):
                    continue

            prior_close = prior_close_from_option_leg(opt)
            day_low, day_high = day_extremes_from_option_leg(opt)

            _record(symbol, strike, side, premium, volume)
            key_h = _strike_key(strike, side)
            hist = _history.get(symbol, {}).get(key_h)
            vel_key = _open_key(symbol, strike, side)
            # WS heatmap rows carry volume=0 (unknown). _record preserves the latest
            # authoritative REST volume in history; use that same effective value for
            # volume awakening and ICT so price heat and volume proof coexist.
            effective_volume = _last_known_volume(hist) if hist else float(volume or 0)

            if not hist or len(hist) < 2:
                v3_probe = 0.0
                vol_surge_probe = 1.0
            else:
                v3_probe = _velocity(hist, 1)
                vol_surge_probe = _volume_surge_with_chain(
                    effective_volume, hist, settings,
                )

            open_move = _session_open_move_pct(
                symbol, strike, side, premium, hist,
                v3=v3_probe, vol_surge=vol_surge_probe,
                prior_close=prior_close,
                day_low=day_low,
                day_high=day_high,
            )
            peak_move = _session_peak_move_pct(
                symbol, strike, side, premium, hist,
                v3=v3_probe, vol_surge=vol_surge_probe,
                prior_close=prior_close,
                day_low=day_low,
                day_high=day_high,
            )
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
                vol_surge = _volume_surge_with_chain(
                    effective_volume, hist, settings,
                )
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
            # Tier is monotonic — velocity votes UPGRADE only, never downgrade a
            # higher tier already set by peak-move (previously BUILDING/EXPLODING here
            # clobbered a peak-move ELITE/EXPLODING).
            if (v3 >= v3_build or v9 >= v9_build) and _TIER_RANK.get(tier, 0) < _TIER_RANK["BUILDING"]:
                tier = "BUILDING"
            if (
                (v3 >= v3_explode or v9 >= v9_explode or (v3 >= 2.0 and vol_surge >= 1.8))
                and _TIER_RANK.get(tier, 0) < _TIER_RANK["EXPLODING"]
            ):
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

            awakened = _volume_awakening(
                effective_volume, v3, max(open_move, session_move), settings,
            )
            if awakened:
                vol_surge = max(vol_surge, 2.0)
                score = min(100, score + 12)
                if tier == "WATCH":
                    tier = "BUILDING"
                if expiry_day and near_atm and v3 >= 1.5:
                    tier = "EXPLODING" if _TIER_RANK.get(tier, 0) < _TIER_RANK["EXPLODING"] else tier
                elif session_move >= settings.open_premium_min_move_pct:
                    tier = "EXPLODING" if tier == "BUILDING" else tier
                reason_parts_open.append(
                    f"volAwaken×{effective_volume // 1000:.0f}k"
                )

            tier = _apply_sticky_tier(f"{symbol}:{key_h}", tier)

            if tier == "WATCH" and score < 25 and not awakened:
                keep_first_lift = False
                if bool(getattr(settings, "ict_first_lift_appear_enabled", True)):
                    # The ICT first-lift threshold is intentionally softer than BUILDING.
                    # Probe before dropping WATCH so a slow 15% lift off a real flat/V base
                    # reaches radar; selection still requires its normal score/tier/chart
                    # gates before this can become an order.
                    try:
                        from app.engines.ict_breakout_monitor import analyze_ict_breakout

                        keep_first_lift = analyze_ict_breakout(
                            symbol=symbol,
                            side=side,
                            strike=float(strike),
                            premium=float(premium),
                            session_move_pct=float(session_move),
                            peak_move_pct=float(peak_move),
                            velocity_3s=float(v3),
                            velocity_9s=float(v9),
                            volume_surge=float(vol_surge),
                            volume=float(effective_volume or 0),
                            tier=tier,
                            reason=" ".join(reason_parts_open),
                        ).first_lift
                    except Exception:
                        keep_first_lift = False
                if not keep_first_lift and not (peak_move >= 20 and v3 >= 1.2):
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
            # Peak-hold to stop the score flickering below entry gates mid-rip.
            score = _apply_sticky_score(f"{symbol}:{key_h}", score, tier)

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
                volume=float(effective_volume or 0),
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
        # HeatmapStrike carries OI, not bar volume. OI is cumulative open positions —
        # NOT trade volume — so using it for volume_surge produced garbage/false surges.
        # WS overlay has no reliable volume → pass 0 so volume_surge stays neutral (1.0);
        # the authoritative full REST rebuild supplies real volume.
        chain.append({
            "strike_price": row.strike,
            "strike": row.strike,
            "call_options": {
                "ltp": row.callLtp,
                "last_price": row.callLtp,
                "volume": 0,
            },
            "put_options": {
                "ltp": row.putLtp,
                "last_price": row.putLtp,
                "volume": 0,
            },
        })
    return scan_chain_explosions(
        snap.symbol, chain, float(snap.spot), atm, expiry_day=expiry_day,
    )


def refresh_snapshot_explosion_alerts(snap: Any, *, expiry_day: bool = False) -> None:
    """Update explosionAlerts on a cached snapshot using fresh WS LTPs."""
    events = scan_snapshot_explosions(snap, expiry_day=expiry_day)
    alerts = [event_to_dict(e, snap) for e in events[:15]]
    snap.explosionAlerts = alerts
    snap.topExplosion = alerts[0] if alerts else None


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
    from app.engines.bullish_local_base import bullish_local_base_prediction

    bullish_base = bullish_local_base_prediction(snap, e, ict)
    move = max(float(e.daily_move_pct or 0), float(e.peak_move_pct or 0), float(ict.session_move_pct or 0))
    from app.config import get_settings as _gs

    _settings = _gs()
    immature_floor = float(
        getattr(_settings, "explosion_immature_min_session_move_pct", 28.0) or 28.0
    )
    # Pad floor — arm tradeable at the real base (₹40), not after the rip (₹160).
    pad_floor = float(
        getattr(_settings, "ict_structured_early_min_move_pct", 15.0) or 15.0
    )
    pad_ceil = float(
        getattr(_settings, "ict_structured_early_max_move_pct", 65.0) or 65.0
    )
    from app.engines.explosion_entry_guards import effective_local_base_move_pct

    pad_move = effective_local_base_move_pct(e, ict)
    off_low_move = session_low_relative_move_pct(e.symbol, e.strike, e.side, e.premium)
    structure_pad = max(float(pad_move or 0), float(off_low_move or 0))
    vol_awaken = (
        "volAwaken" in (e.reason or "")
        or ict.volume_awakening
        or float(e.volume_surge or 0) >= 3.0
    )
    # EXPLODING/ELITE still need a real rip — tiny displacement spikes are not tradeable.
    tradeable = (e.tier in ("EXPLODING", "ELITE") and move >= immature_floor) or capture
    # First print inside the near-base pad is tradeable even before the 28% immature floor.
    if e.tier in ("EXPLODING", "ELITE") and pad_floor <= pad_move <= pad_ceil:
        tradeable = True
    if ict.mega_rip or (ict.active and (ict.flat_then_vertical or ict.premium_fvg)):
        tradeable = True
    # First lift off the lowest local base (15–40%) must appear as tradeable immediately —
    # do not wait for day-move / chase tiers (Aug14 FTV only showed after ~47%).
    first_lift = bool(getattr(ict, "first_lift", False))
    if first_lift:
        tradeable = True
    # BUILDING + early flat break must be tradeable (26→45 before EXPLODING).
    if e.tier == "BUILDING" and ict.active and ict.flat_then_vertical:
        tradeable = True
    # First confirmed CE/PE turn may occur at 8-15% off the local pad, before the normal
    # structured floor. The predictor requires the actual base, index turn, premium
    # acceleration and volume (+ ICT confirms), so expose it to radar and revalidate.
    if bullish_base.get("active"):
        tradeable = True
    # BUILDING + volume awakening inside the early pad — Aug12 SENSEX 77800 PE
    # stayed not_tradeable while volumeAwaken=true (ICT watch after missed trough).
    if (
        e.tier == "BUILDING"
        and vol_awaken
        and pad_floor <= structure_pad <= pad_ceil
    ):
        tradeable = True
    # Near-base ATM/ITM top explosions must be tradeable even when day-move < floor
    # (Aug5 24500 PE ~10–65% off local base while session % still immature).
    if not tradeable and e.tier in ("ELITE", "EXPLODING"):
        try:
            from app.engines.elite_never_block import top_explosion_must_take_active

            alert_probe = {
                "tier": e.tier,
                "side": e.side.value if hasattr(e.side, "value") else str(e.side),
                "strike": e.strike,
                "premium": e.premium,
                "explosionScore": e.explosion_score,
                "dailyMovePct": e.daily_move_pct,
                "peakMovePct": e.peak_move_pct,
                "ictBaseRelativeMovePct": float(getattr(ict, "base_relative_move_pct", 0) or 0),
                "ictFlatThenVertical": bool(getattr(ict, "flat_then_vertical", False)),
                "ictBreakout": bool(getattr(ict, "active", False)),
                "tradeable": True,
            }
            if top_explosion_must_take_active(
                event=e, alert=alert_probe, snap=snap, ict=ict,
            ):
                tradeable = True
        except Exception:
            pass
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
        "offLowMovePct": round(
            session_low_relative_move_pct(e.symbol, e.strike, e.side, e.premium),
            1,
        ),
        "localBaseMovePct": round(float(pad_move or 0), 1),
        "volumeAwaken": vol_awaken,
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
        "ictFirstLift": first_lift,
        "ictVolumeAwakening": ict.volume_awakening,
        "ictDisplacement": ict.displacement,
        "ictLocalSwingBase": ict.local_swing_base,
        "ictBaseRelativeMovePct": round(ict.base_relative_move_pct, 1),
        "ictBasePremium": round(ict.base_premium, 2),
        "flatVerticalQuality": round(
            float(getattr(ict, "flat_vertical_quality", 0) or 0),
            1,
        ),
        "flatVerticalGrade": str(getattr(ict, "flat_vertical_grade", "") or ""),
        "bullishLocalBasePrediction": bullish_base,
        "bullishLocalBaseActive": bool(bullish_base.get("active")),
        "bullishLocalBaseConfidence": float(bullish_base.get("confidence") or 0),
        "localBaseReversalPrediction": bullish_base,
        "localBaseReversalActive": bool(bullish_base.get("active")),
        "localBaseReversalConfidence": float(bullish_base.get("confidence") or 0),
        "localBaseReversalSide": bullish_base.get("side") or e.side.value,
        "momentType": (
            "first_lift_local_base"
            if first_lift
            else (ict.pattern if ict.active else ("volume_awaken" if vol_awaken else e.tier))
        ),
        "ictReasons": ict.reasons,
    }
