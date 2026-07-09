"""Missed trade explainer — per-alert gate-by-gate analysis for radar vs execution gaps."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.engines.bad_day_routing import (
    _extreme_explosion_bypass,
    bad_day_min_rank_floor,
    check_bad_day_candidate,
)
from app.engines.chop_day_guards import chop_guard_summary, is_chop_session
from app.engines.daily_18pct_strategy import compute_trading_limits
from app.engines.expiry_day_guards import expiry_guard_summary
from app.engines.morning_premium_capture import in_all_day_explosion_window
from app.engines.premium_filter import premium_in_band
from app.engines.pretrade_validator import collect_session_trades, validate_candidate
from app.engines.spot_direction import chart_blocks_side, side_aligned_with_chart
from app.engines.trade_selector import EntryCandidate, find_best_entry
from app.engines.worst_day_guard import session_entry_policy, worst_day_allows_candidate
from app.models.schemas import AutoTraderState, Side, StrategyType, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _candidate_from_alert(symbol: str, snap: SymbolSnapshot, alert: dict) -> EntryCandidate:
    from app.engines.explosion_detector import ExplosionEvent

    side = Side(str(alert.get("side") or "CALL").upper())
    event = ExplosionEvent(
        symbol=symbol,
        side=side,
        strike=float(alert.get("strike") or 0),
        premium=float(alert.get("premium") or 0),
        velocity_3s=float(alert.get("velocity3s") or 0),
        velocity_9s=float(alert.get("velocity9s") or 0),
        velocity_15s=float(alert.get("velocity15s") or 0),
        volume_surge=float(alert.get("volumeSurge") or 0),
        explosion_score=float(alert.get("explosionScore") or 0),
        tier=str(alert.get("tier") or "WATCH"),
        reason=str(alert.get("reason") or ""),
        daily_move_pct=float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
    )
    score = float(alert.get("explosionScore") or 0)
    return EntryCandidate(
        symbol=symbol,
        snap=snap,
        mode="explosion",
        score=score,
        side=side,
        strike=float(alert.get("strike") or 0),
        premium=float(alert.get("premium") or 0),
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=score,
        tqs=float(snap.tradeQualityScore or 0),
        tier=str(alert.get("tier") or ""),
        explosion_event=event,
        alert=alert,
    )


def _effective_rank_floor(
    candidate: EntryCandidate,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[float, list[str]]:
    """Mirror find_best_entry rank floor stacking."""
    settings = get_settings()
    notes: list[str] = []
    chop = is_chop_session(snapshots)
    from app.engines.pretrade_validator import last_n_elevated_min_rank
    from app.engines.chop_day_guards import min_rank_for_entry

    floor = min_rank_for_entry(chop, snapshots)
    notes.append(f"chop_floor={floor:.0f}")

    ln_floor = last_n_elevated_min_rank(state)
    if ln_floor > floor:
        floor = ln_floor
        notes.append(f"last_n_floor={ln_floor:.0f}")

    bd_floor = bad_day_min_rank_floor(state, snapshots)
    if bd_floor > floor:
        floor = bd_floor
        notes.append(f"bad_day_floor={bd_floor:.0f}")

    if settings.best_trades_only_enabled:
        floor = max(floor, settings.best_trades_min_rank_score)
        notes.append(f"best_trades={settings.best_trades_min_rank_score:.0f}")

    policy, _ = session_entry_policy(state, snapshots)
    if policy == "BREAKOUT_ONLY":
        floor = max(floor, settings.worst_day_breakout_min_rank)
        notes.append(f"worst_day_breakout={settings.worst_day_breakout_min_rank:.0f}")

    daily_move = float(
        (candidate.alert or {}).get("dailyMovePct")
        or (candidate.alert or {}).get("openPremiumMove")
        or 0,
    )
    if candidate.mode == "explosion":
        if daily_move >= settings.all_day_explosion_extreme_move_min_pct:
            reduced = min(floor, settings.all_day_explosion_min_score)
            if reduced < floor:
                floor = reduced
                notes.append(f"extreme_move_floor={reduced:.0f}")
        elif daily_move >= settings.all_day_explosion_session_move_min_pct and in_all_day_explosion_window():
            reduced = min(floor, settings.all_day_explosion_min_score + 4)
            if reduced < floor:
                floor = reduced
                notes.append(f"session_move_floor={reduced:.0f}")

    from app.engines.chart_exit_levels import chart_trade_confidence

    chart_conf, _ = chart_trade_confidence(candidate.snap, candidate.side)
    if chart_conf >= settings.all_day_min_chart_confidence:
        reduced = min(floor, settings.all_day_min_rank_score)
        if reduced < floor:
            floor = reduced
            notes.append(f"chart_quality_floor={reduced:.0f}")

    return floor, notes


def _sort_score(candidate: EntryCandidate) -> float:
    bonus = 20 if candidate.mode == "explosion" else 0
    return candidate.score + bonus


def _gate_checks(
    symbol: str,
    snap: SymbolSnapshot,
    alert: dict,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    settings = get_settings()
    gates: list[dict[str, Any]] = []
    blockers: list[str] = []
    candidate = _candidate_from_alert(symbol, snap, alert)

    tier = str(alert.get("tier") or "")
    score = float(alert.get("explosionScore") or 0)
    daily_move = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
    peak_move = float(alert.get("peakMovePct") or daily_move)
    if peak_move > daily_move:
        daily_move = max(daily_move, peak_move * 0.65)
    prem = alert.get("premium")

    # 1 — Radar visibility
    gates.append({"gate": "radar", "passed": True, "detail": f"{tier} on explosion radar"})

    # 2 — Tradeable tier
    tradeable = bool(alert.get("tradeable"))
    if not tradeable:
        blockers.append("not_tradeable_tier")
        gates.append({
            "gate": "tradeable_tier",
            "passed": False,
            "detail": "WATCH/BUILDING needs velocity or volume awakening",
            "fix": "Wait for EXPLODING tier or enable volume awakening",
        })
    else:
        gates.append({"gate": "tradeable_tier", "passed": True, "detail": tier})

    # 3 — Premium band
    if not premium_in_band(prem, mode="explosion"):
        blockers.append("premium_out_of_band")
        gates.append({"gate": "premium_band", "passed": False, "detail": f"premium ₹{prem}", "fix": "Sub-min bypass on extreme session move"})
    else:
        gates.append({"gate": "premium_band", "passed": True, "detail": f"₹{prem}"})

    # 4 — Explosion score
    min_score = settings.aggressive_min_explosion_score
    if daily_move >= settings.all_day_explosion_session_move_min_pct:
        min_score = min(min_score, settings.all_day_explosion_min_score)
    if score < min_score:
        blockers.append(f"score_{score:.0f}<{min_score:.0f}")
        gates.append({"gate": "explosion_score", "passed": False, "detail": f"{score:.0f} < {min_score:.0f}", "fix": "Wait for velocity spike"})
    else:
        gates.append({"gate": "explosion_score", "passed": True, "detail": f"{score:.0f} ≥ {min_score:.0f}"})

    # 5 — Symbol TQS
    if snap.tradeQualityScore < 25 and score < settings.aggressive_min_explosion_score + 10:
        blockers.append("symbol_tqs_low")
        gates.append({"gate": "symbol_tqs", "passed": False, "detail": f"TQS {snap.tradeQualityScore:.0f}"})
    else:
        gates.append({"gate": "symbol_tqs", "passed": True, "detail": f"TQS {snap.tradeQualityScore:.0f}"})

    # 6 — Chart alignment
    chart = snap.spotChart
    side_val = candidate.side.value
    chart_dir = (chart.direction or "NEUTRAL").upper() if chart else "NEUTRAL"
    breadth_bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    from app.engines.aligned_explosion_bypass import expiry_chart_bypass_for_candidate
    from app.engines.morning_premium_capture import (
        _market_opposes_side,
        premium_led_explosion_bypass,
    )

    premium_bypass = (
        premium_led_explosion_bypass(candidate.explosion_event, chart, breadth_bias)
        if candidate.explosion_event
        else False
    )
    expiry_chart_bypass = expiry_chart_bypass_for_candidate(candidate, snap)
    blocked, chart_reason = chart_blocks_side(
        candidate.side, chart, trade_score=score, momentum_surge=daily_move >= 40,
        premium_led_bypass=premium_bypass,
        expiry_explosion_bypass=expiry_chart_bypass,
    )
    if blocked:
        blockers.append(chart_reason)
        gates.append({
            "gate": "chart_alignment",
            "passed": False,
            "detail": f"chart {chart_dir} vs {side_val}",
            "fix": "MTF reconcile or elite premium-led bypass (score ≥90)",
        })
    else:
        gates.append({"gate": "chart_alignment", "passed": True, "detail": f"chart {chart_dir}"})

    # 6b — Breadth alignment
    from app.engines.rally_capture import breadth_blocks_explosion_side

    br_blocked, br_reason = breadth_blocks_explosion_side(candidate.side, breadth_bias, tier)
    market_opposes = _market_opposes_side(candidate.side, breadth_bias, chart)
    if br_blocked and not premium_bypass:
        blockers.append(br_reason)
        gates.append({
            "gate": "breadth_alignment",
            "passed": False,
            "detail": f"breadth {breadth_bias} vs {side_val}",
            "fix": "Trade CALL on bullish / PUT on bearish — or ELITE score ≥90 for counter-trend",
        })
    else:
        gates.append({
            "gate": "breadth_alignment",
            "passed": True,
            "detail": f"breadth {breadth_bias}" + (" (premium-led bypass)" if premium_bypass else ""),
        })

    if market_opposes and not premium_bypass:
        blockers.append("market_opposes_side")
        gates.append({
            "gate": "market_direction",
            "passed": False,
            "detail": f"{breadth_bias} breadth / {chart_dir} chart vs {side_val}",
            "fix": "Need ELITE tier + explosion score ≥90 for counter-trend rip",
        })
    else:
        gates.append({
            "gate": "market_direction",
            "passed": True,
            "detail": "aligned or elite counter-trend bypass",
        })

    # 7 — Would enter candidate pool (tier filter for explosions)
    in_pool = tradeable and score >= min_score and premium_in_band(prem, mode="explosion")
    if tier not in ("ELITE", "EXPLODING") and in_pool:
        from app.engines.morning_premium_capture import is_premium_capture_alert

        if not is_premium_capture_alert(alert, chart):
            in_pool = False
            blockers.append("building_outside_capture_window")
            gates.append({
                "gate": "capture_window",
                "passed": False,
                "detail": f"{tier} outside capture/all-day window",
                "fix": "Enable all-day explosion or wait for EXPLODING",
            })
    if in_pool and "building_outside_capture_window" not in blockers:
        gates.append({"gate": "capture_window", "passed": True, "detail": "in explosion candidate pool"})

    if not in_pool:
        return {
            "symbol": symbol,
            "side": side_val,
            "strike": alert.get("strike"),
            "tier": tier,
            "score": score,
            "dailyMovePct": daily_move,
            "premium": prem,
            "wouldPass": False,
            "primaryBlocker": blockers[0] if blockers else "not_in_candidate_pool",
            "blockers": blockers,
            "gates": gates,
            "sortScore": _sort_score(candidate),
            "rankFloor": None,
            "rankFloorNotes": [],
            "fix": _fix_for_blockers(blockers),
        }

    # 8 — Pretrade validator
    ok, reason, _ = validate_candidate(candidate, state, snapshots=snapshots)
    gates.append({
        "gate": "pretrade",
        "passed": ok,
        "detail": reason if not ok else "passed",
        "fix": "Check interval, daily cap, directional lock" if not ok else None,
    })
    if not ok:
        blockers.append(reason)

    # 9 — Worst day
    policy, policy_meta = session_entry_policy(state, snapshots)
    if _extreme_explosion_bypass(candidate) and policy == "BREAKOUT_ONLY":
        gates.append({
            "gate": "worst_day",
            "passed": True,
            "detail": f"extreme move bypass ({daily_move:.0f}%)",
        })
    else:
        wd_ok, wd_reason, _ = worst_day_allows_candidate(candidate, state, snapshots, policy=policy)
        gates.append({
            "gate": "worst_day",
            "passed": wd_ok,
            "detail": f"{policy}: {wd_reason}" if not wd_ok else f"{policy} ok",
            "fix": f"Need rank ≥{settings.worst_day_breakout_min_rank}, {settings.worst_day_breakout_tiers_csv}" if not wd_ok else None,
        })
        if not wd_ok:
            blockers.append(wd_reason)

    # 10 — Bad day routing
    if _extreme_explosion_bypass(candidate):
        gates.append({"gate": "bad_day", "passed": True, "detail": "extreme session move bypass"})
    else:
        bd_ok, bd_reason, bd_meta = check_bad_day_candidate(candidate, state, snapshots)
        gates.append({
            "gate": "bad_day",
            "passed": bd_ok,
            "detail": bd_reason if not bd_ok else "ok",
            "fix": f"Need rank ≥{bd_meta.get('badDayMinRank', 72)}" if not bd_ok else None,
        })
        if not bd_ok:
            blockers.append(bd_reason)

    # 11 — Rank floor
    floor, floor_notes = _effective_rank_floor(candidate, state, snapshots)
    sort_sc = _sort_score(candidate)
    rank_ok = sort_sc >= floor
    from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

    expiry_trade_ok, expiry_trade_reason = expiry_aligned_explosion_trade_allowed(candidate, snap)
    if not rank_ok and expiry_trade_ok:
        rank_ok = True
        floor_notes = list(floor_notes) + [f"expiry_aligned_rank_bypass({expiry_trade_reason})"]
    gates.append({
        "gate": "rank_floor",
        "passed": rank_ok,
        "detail": f"sort={sort_sc:.0f} vs floor={floor:.0f}",
        "fix": f"Score needs +{max(0, floor - sort_sc):.0f} or lower floor" if not rank_ok else None,
    })
    if not rank_ok:
        blockers.append(f"rank_floor_{sort_sc:.0f}<{floor:.0f}")

    # 12 — Chart at execution (informational)
    if chart and not side_aligned_with_chart(candidate.side, chart):
        gates.append({
            "gate": "execution_chart",
            "passed": False,
            "detail": "may fail execution MTF gate at order time",
            "fix": "Deploy chart reconcile fix",
        })

    would_pass = not blockers
    return {
        "symbol": symbol,
        "side": side_val,
        "strike": alert.get("strike"),
        "tier": tier,
        "score": score,
        "dailyMovePct": daily_move,
        "premium": prem,
        "velocity3s": alert.get("velocity3s"),
        "allDayExplosion": bool(alert.get("allDayExplosion")),
        "volumeAwaken": bool(alert.get("volumeAwaken")),
        "wouldPass": would_pass,
        "primaryBlocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "gates": gates,
        "sortScore": sort_sc,
        "rankFloor": floor,
        "rankFloorNotes": floor_notes,
        "fix": _fix_for_blockers(blockers),
    }


def _fix_for_blockers(blockers: list[str]) -> str:
    if not blockers:
        return "Would enter if selected as best candidate"
    b = blockers[0]
    if "rank_floor" in b:
        return "Lower rank floor or wait for higher explosion score"
    if "worst_day" in b:
        return "Relax WORST_DAY_BREAKOUT_MIN_RANK or extreme-move bypass"
    if "bad_day" in b:
        return "Pre-expiry routing — trade alternate index or elite tier"
    if "not_tradeable" in b:
        return "Volume awakening or velocity spike needed"
    if "chart" in b:
        return "Chart reconcile — MTF over 5m bounce"
    if "score" in b:
        return "Wait for tier upgrade to EXPLODING"
    return "Review pretrade gates in Auto Trading skipped list"


def build_missed_trade_report(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> dict[str, Any]:
    """Full missed-trade explainer — every significant radar alert with gate breakdown."""
    state = state or get_state()
    settings = get_settings()
    chop = chop_guard_summary(state, snapshots)
    expiry = expiry_guard_summary(state, snapshots)
    policy, policy_meta = session_entry_policy(state, snapshots)

    from app.engines.capital_allocator import _capital_base_for_stages, compute_session_pnl

    session_pnl = compute_session_pnl(state)
    capital_base = _capital_base_for_stages()

    trades_today = len(collect_session_trades(state))
    trading_limits = compute_trading_limits(
        snapshots, state, session_pnl=session_pnl, capital_base=capital_base, trades_today=trades_today,
    )

    best = find_best_entry(snapshots, state, trading_limits)
    missed: list[dict[str, Any]] = []
    passed: list[dict[str, Any]] = []

    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            tier = str(alert.get("tier") or "")
            daily_move = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
            if tier == "WATCH" and daily_move < 20 and not alert.get("allDayExplosion"):
                continue
            row = _gate_checks(sym, snap, alert, state, snapshots)
            if row.get("wouldPass"):
                passed.append(row)
            else:
                missed.append(row)

    missed.sort(key=lambda r: (-float(r.get("dailyMovePct") or 0), -float(r.get("score") or 0)))
    passed.sort(key=lambda r: -float(r.get("sortScore") or 0))

    session_blocks = [s for s in (state.skipped or []) if s.get("symbol") == "SESSION"]

    return {
        "at": datetime.now(IST).isoformat(),
        "summary": _report_summary(missed, passed, best, session_blocks, policy),
        "entryPolicy": policy,
        "policyMeta": policy_meta,
        "badDayMinRank": (chop.get("badDayRouting") or {}).get("minRankFloor"),
        "worstDayBreakoutMinRank": settings.worst_day_breakout_min_rank,
        "bestTradesMinRank": settings.best_trades_min_rank_score,
        "eliteCounterMinScore": settings.premium_led_elite_counter_min_score,
        "sessionBlocks": session_blocks[:6],
        "bestCandidate": (
            {
                "symbol": best.symbol,
                "side": best.side.value,
                "mode": best.mode,
                "score": best.score,
                "strike": best.strike,
            }
            if best
            else None
        ),
        "missed": missed[:20],
        "wouldPass": passed[:8],
        "missedCount": len(missed),
        "passCount": len(passed),
        "nearExpirySymbols": expiry.get("nearExpirySymbols") or [],
        "dataIssues": [
            {"symbol": sym, "error": snap.error}
            for sym, snap in snapshots.items()
            if not snap.dataAvailable
        ],
    }


def _report_summary(
    missed: list[dict],
    passed: list[dict],
    best: Any,
    session_blocks: list[dict],
    policy: str,
) -> str:
    parts: list[str] = []
    if session_blocks:
        parts.append(f"Session: {session_blocks[0].get('reason')}")
    parts.append(f"Policy: {policy}")
    if missed:
        top = missed[0]
        parts.append(
            f"Top miss: {top.get('symbol')} {top.get('side')} {top.get('strike')} "
            f"+{top.get('dailyMovePct', 0):.0f}% blocked by {top.get('primaryBlocker')}",
        )
    if passed and not best:
        p = passed[0]
        parts.append(f"{len(passed)} would pass gates but not selected as best")
    elif best:
        parts.append(f"Best: {best.symbol} {best.mode} score={best.score:.0f}")
    elif not missed and not passed:
        parts.append("No significant explosion alerts on radar")
    return " · ".join(parts)
