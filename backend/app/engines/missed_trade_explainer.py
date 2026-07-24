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
        peak_move_pct=float(alert.get("peakMovePct") or 0),
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
    from app.engines.extreme_explosion_moment import is_high_mover_elite_bypass

    chart_conf, _ = chart_trade_confidence(candidate.snap, candidate.side)
    if chart_conf >= settings.all_day_min_chart_confidence:
        reduced = min(floor, settings.all_day_min_rank_score)
        if reduced < floor:
            floor = reduced
            notes.append(f"chart_quality_floor={reduced:.0f}")

    if candidate.mode == "explosion" and is_high_mover_elite_bypass(candidate=candidate):
        notes.append("high_mover_rank_bypass")

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
    peak_for_prem = float(alert.get("peakMovePct") or daily_move or 0)
    if not premium_in_band(prem, mode="explosion", peak_move_pct=peak_for_prem):
        blockers.append("premium_out_of_band")
        gates.append({"gate": "premium_band", "passed": False, "detail": f"premium ₹{prem}", "fix": "Sub-min bypass on extreme session move"})
    else:
        gates.append({"gate": "premium_band", "passed": True, "detail": f"₹{prem}"})

    # 4 — Explosion score
    from app.engines.explosion_detector import effective_explosion_min_score

    peak_move = float(alert.get("peakMovePct") or 0)
    min_score = effective_explosion_min_score(
        tier=str(alert.get("tier") or "WATCH"),
        peak_move_pct=peak_move,
        daily_move_pct=daily_move,
    )
    if score < min_score:
        blockers.append(f"score_{score:.0f}<{min_score:.0f}")
        min_peak = float(getattr(settings, "peak_move_explosion_min_pct", 35.0) or 35.0)
        fix = f"Peak-move bypass needs session peak ≥{min_peak:.0f}%" if peak_move < min_peak else "Wait for velocity spike"
        gates.append({"gate": "explosion_score", "passed": False, "detail": f"{score:.0f} < {min_score:.0f} (peak {peak_move:.0f}%)", "fix": fix})
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
        premium_led_explosion_bypass(
            candidate.explosion_event, chart, breadth_bias, snap=snap,
        )
        if candidate.explosion_event
        else False
    )
    from app.engines.vertical_rip_bypass import (
        qualifies_for_vertical_rip_bypass,
        vertical_rip_bypass_for_snap,
    )

    vertical_bypass = (
        qualifies_for_vertical_rip_bypass(candidate.explosion_event, snap=snap)
        if candidate.explosion_event
        else vertical_rip_bypass_for_snap(candidate.side, snap, explosion_event=None)
    )
    from app.engines.local_base_chart_bypass import local_base_ichimoku_bypass_for_snap

    local_ichi_bypass = local_base_ichimoku_bypass_for_snap(
        candidate.side, snap, explosion_event=candidate.explosion_event,
    )
    expiry_chart_bypass = expiry_chart_bypass_for_candidate(candidate, snap)
    blocked, chart_reason = chart_blocks_side(
        candidate.side, chart, trade_score=score, momentum_surge=daily_move >= 40,
        premium_led_bypass=premium_bypass or vertical_bypass or local_ichi_bypass,
        expiry_explosion_bypass=expiry_chart_bypass,
    )
    if blocked:
        blockers.append(chart_reason)
        gates.append({
            "gate": "chart_alignment",
            "passed": False,
            "detail": f"chart {chart_dir} vs {side_val}",
            "fix": "Local-base + Ichimoku bypass, MTF reconcile, or elite premium-led",
        })
    else:
        detail = f"chart {chart_dir}"
        if local_ichi_bypass:
            detail += " (local_base_ichimoku_bypass)"
        gates.append({"gate": "chart_alignment", "passed": True, "detail": detail})

    # 6b — Breadth alignment
    from app.engines.aligned_side_guard import (
        breadth_hard_blocks_side,
        chart_mtf_breadth_bypass_active,
    )
    from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass
    from app.engines.rally_capture import breadth_blocks_explosion_side

    all_in = is_extreme_explosion_all_in_bypass(candidate=candidate, alert=alert)
    if all_in:
        gates.append({
            "gate": "extreme_all_in_bypass",
            "passed": True,
            "detail": f"{tier} {daily_move:.0f}% session rip — ALL-IN bypass active",
        })
    elif vertical_bypass:
        gates.append({
            "gate": "vertical_rip_bypass",
            "passed": True,
            "detail": f"{tier} peak rip — chart/breadth bypass active",
        })

    bypassed, bypass_reason = chart_mtf_breadth_bypass_active(
        candidate.side, breadth_bias, snap, score=score,
    )
    hard_blocked, hard_reason = breadth_hard_blocks_side(
        candidate.side,
        breadth_bias,
        event=candidate.explosion_event,
        candidate=candidate,
        alert=alert,
        snap=snap,
    )
    br_blocked, br_reason = breadth_blocks_explosion_side(
        candidate.side,
        breadth_bias,
        tier,
        event=candidate.explosion_event,
        snap=snap,
        alert=alert if isinstance(alert, dict) else None,
    )
    market_opposes = _market_opposes_side(
        candidate.side,
        breadth_bias,
        chart,
        snap=snap,
        event=candidate.explosion_event,
        alert=alert if isinstance(alert, dict) else None,
    )
    if bypassed and not all_in and not vertical_bypass:
        gates.append({
            "gate": "breadth_hard_block",
            "passed": True,
            "detail": f"chart+MTF override — OI breadth {breadth_bias} lags live price",
            "fix": bypass_reason,
        })
    elif hard_blocked and not all_in and not vertical_bypass:
        blockers.append(hard_reason)
        gates.append({
            "gate": "breadth_hard_block",
            "passed": False,
            "detail": f"breadth {breadth_bias} vs {side_val}",
            "fix": "Hard block — trade CALL on bullish / PUT on bearish breadth only",
        })
    elif br_blocked and not premium_bypass and not vertical_bypass:
        blockers.append(br_reason)
        gates.append({
            "gate": "breadth_alignment",
            "passed": False,
            "detail": f"breadth {breadth_bias} vs {side_val}",
            "fix": "Trade CALL on bullish / PUT on bearish breadth",
        })
    else:
        gates.append({
            "gate": "breadth_alignment",
            "passed": True,
            "detail": f"breadth {breadth_bias}" + (" (premium-led bypass)" if premium_bypass else ""),
        })

    if hard_blocked and not all_in and not bypassed:
        blockers.append("market_opposes_side")
        gates.append({
            "gate": "market_direction",
            "passed": False,
            "detail": f"{breadth_bias} breadth vs {side_val}",
            "fix": "Counter-breadth blocked — no ELITE bypass on directional breadth",
        })
    elif market_opposes and not premium_bypass:
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

    # 8b — Instrument cooldown (same strike re-entry after loss)
    from app.engines.trade_selector import _reentry_blocked
    from app.engines.extreme_explosion_moment import is_high_mover_elite_bypass

    high_mover = is_high_mover_elite_bypass(candidate=candidate, alert=alert)
    reentry_blocked, reentry_reason = _reentry_blocked(
        symbol,
        candidate.side,
        float(alert.get("strike") or 0),
        snap,
        explosion_event=candidate.explosion_event,
    )
    if reentry_blocked and not high_mover:
        blockers.append(reentry_reason)
        gates.append({
            "gate": "instrument_cooldown",
            "passed": False,
            "detail": reentry_reason,
            "fix": "Wait for cooldown or ELITE 95%+ session rip bypasses re-entry block",
        })
    elif reentry_blocked and high_mover:
        gates.append({
            "gate": "instrument_cooldown",
            "passed": True,
            "detail": f"{reentry_reason} bypassed — high-mover ELITE rip",
        })
    else:
        gates.append({"gate": "instrument_cooldown", "passed": True, "detail": "ok"})

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
    from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

    expiry_trade_ok, expiry_trade_reason = expiry_aligned_explosion_trade_allowed(candidate, snap)
    if _extreme_explosion_bypass(candidate):
        gates.append({"gate": "bad_day", "passed": True, "detail": "extreme session move bypass"})
    elif expiry_trade_ok:
        gates.append({"gate": "bad_day", "passed": True, "detail": f"expiry_aligned ({expiry_trade_reason})"})
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
    if not rank_ok and expiry_trade_ok:
        rank_ok = True
        floor_notes = list(floor_notes) + [f"expiry_aligned_rank_bypass({expiry_trade_reason})"]
    if not rank_ok and high_mover:
        rank_ok = True
        floor_notes = list(floor_notes) + ["high_mover_rank_bypass"]
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

    from app.engines.explosion_entry_guards import (
        detect_fake_explosion_trap,
        extended_session_chase_blocked,
        immature_explosion_blocked,
        live_explosion_confirmation_blocked,
    )
    from app.engines.ict_breakout_monitor import (
        analyze_explosion_event_ict,
        late_fade_chase_blocked,
    )

    ict = (
        analyze_explosion_event_ict(candidate.explosion_event, snap)
        if candidate.explosion_event
        else None
    )
    if candidate.explosion_event:
        immature_blocked, immature_reason = immature_explosion_blocked(
            candidate.explosion_event, ict=ict,
        )
        if immature_blocked:
            blockers.append(immature_reason)
            gates.append({
                "gate": "immature_explosion",
                "passed": False,
                "detail": immature_reason,
                "fix": "Wait for ≥22% session rip or confirmed flat→vertical — skip displacement noise",
            })
        else:
            gates.append({
                "gate": "immature_explosion",
                "passed": True,
                "detail": "session move mature enough",
            })
        live_blocked, live_reason = live_explosion_confirmation_blocked(
            candidate.explosion_event, ict=ict, snap=snap,
        )
        if live_blocked:
            blockers.append(live_reason)
            gates.append({
                "gate": "live_explosion_confirmation",
                "passed": False,
                "detail": live_reason,
                "fix": "Need live velocity + ICT structure (flat→vertical / vol+displace) — skip stale ELITE",
            })
        else:
            gates.append({
                "gate": "live_explosion_confirmation",
                "passed": True,
                "detail": "live velocity + structure confirmed",
            })
        ext_blocked, ext_reason = extended_session_chase_blocked(
            candidate.explosion_event, ict=ict,
        )
        if ext_blocked:
            blockers.append(ext_reason)
            gates.append({
                "gate": "explosion_extended_chase",
                "passed": False,
                "detail": ext_reason,
                "fix": "Enter in the early window (≈28–55% move) — block EXPLOSIVE after +70%",
            })
        else:
            gates.append({
                "gate": "explosion_extended_chase",
                "passed": True,
                "detail": "inside early/soft window",
            })
        trap_block, trap_reason, trap_meta = detect_fake_explosion_trap(
            candidate, snap, state=state, ict=ict,
        )
        if trap_block or trap_meta.get("action") == "block":
            blockers.append(trap_reason)
            gates.append({
                "gate": "fake_explosion_trap",
                "passed": False,
                "detail": trap_reason,
                "fix": (
                    "FOMO/fake-rip — RANGE/chop + ELITE spike after extension, "
                    "OTM inside OR, or flat live premium. Skip or tiny size only."
                ),
                "meta": {
                    "conflictFlags": trap_meta.get("conflictFlags"),
                    "psychologyEscalate": trap_meta.get("psychologyEscalate"),
                },
            })
        elif trap_meta.get("action") == "cut_size":
            gates.append({
                "gate": "fake_explosion_trap",
                "passed": True,
                "detail": f"size_cut_cap_{trap_meta.get('lotCap')}",
                "fix": "Trap soft-cut — keep small until trail proves the move",
            })
        else:
            gates.append({
                "gate": "fake_explosion_trap",
                "passed": True,
                "detail": "no FOMO/fake-rip conflict stack",
            })
    if ict and candidate.explosion_event:
        late_blocked, late_reason = late_fade_chase_blocked(candidate.explosion_event, ict)
        if late_blocked:
            blockers.append(late_reason)
            gates.append({
                "gate": "ict_late_fade_chase",
                "passed": False,
                "detail": late_reason,
                "fix": "Enter earlier on flat-base break — do not chase after peak fades",
            })
        else:
            gates.append({"gate": "ict_late_fade_chase", "passed": True, "detail": "not a late fade chase"})

    moment_type = str(
        alert.get("momentType")
        or (ict.pattern if ict and ict.active else None)
        or alert.get("ictPattern")
        or tier
        or "unknown"
    )

    would_pass = not blockers
    return {
        "symbol": symbol,
        "side": side_val,
        "strike": alert.get("strike"),
        "tier": tier,
        "score": score,
        "dailyMovePct": daily_move,
        "peakMovePct": float(alert.get("peakMovePct") or 0),
        "premium": prem,
        "velocity3s": alert.get("velocity3s"),
        "allDayExplosion": bool(alert.get("allDayExplosion")),
        "volumeAwaken": bool(alert.get("volumeAwaken")),
        "momentType": moment_type,
        "ictPattern": alert.get("ictPattern") or (ict.pattern if ict else None),
        "ictFlatThenVertical": bool(
            alert.get("ictFlatThenVertical") or (ict.flat_then_vertical if ict else False)
        ),
        "ictBreakout": bool(alert.get("ictBreakout") or (ict.active if ict else False)),
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
    if "instrument_cooldown" in b:
        return "Same-strike cooldown after loss — ELITE 95%+ session rip bypasses re-entry"
    if "last_n" in b:
        return "Elevated rank floor after loss cluster — ELITE 95%+ bypasses last-N gate"
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
    moment_taxonomy = _classify_moment_types(missed, passed, snapshots)

    return {
        "at": datetime.now(IST).isoformat(),
        "summary": _report_summary(missed, passed, best, session_blocks, policy, moment_taxonomy),
        "entryPolicy": policy,
        "policyMeta": policy_meta,
        "badDayMinRank": (chop.get("badDayRouting") or {}).get("minRankFloor"),
        "worstDayBreakoutMinRank": settings.worst_day_breakout_min_rank,
        "bestTradesMinRank": settings.best_trades_min_rank_score,
        "eliteCounterMinScore": settings.premium_led_elite_counter_min_score,
        "sessionBlocks": session_blocks[:6],
        "momentTaxonomy": moment_taxonomy,
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


def _classify_moment_types(
    missed: list[dict],
    passed: list[dict],
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    """Bucket radar moments so operators see which rip styles are being missed."""
    from collections import Counter

    buckets: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = {}

    def _bucket_alert(alert: dict, symbol: str) -> str:
        if alert.get("ictMegaRip") or float(alert.get("dailyMovePct") or 0) >= 200:
            return "mega_rip"
        if alert.get("ictFlatThenVertical") or alert.get("ictPattern") == "flat_then_vertical":
            return "flat_then_vertical"
        if alert.get("ictPremiumFvg") or alert.get("ictPattern") == "premium_fvg":
            return "premium_fvg"
        if alert.get("volumeAwaken") or alert.get("ictVolumeAwakening"):
            return "volume_awakening"
        peak = float(alert.get("peakMovePct") or 0)
        v3 = float(alert.get("velocity3s") or 0)
        if peak >= 40 and v3 < 1.0:
            return "faded_vertical_rip"
        if str(alert.get("tier") or "") in ("ELITE", "EXPLODING"):
            return "live_explosion"
        return "building_or_watch"

    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            tier = str(alert.get("tier") or "")
            daily = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
            if tier == "WATCH" and daily < 20 and not alert.get("ictBreakout"):
                continue
            kind = _bucket_alert(alert, sym)
            buckets[kind] += 1
            examples.setdefault(kind, []).append({
                "symbol": sym,
                "side": alert.get("side"),
                "strike": alert.get("strike"),
                "premium": alert.get("premium"),
                "tier": tier,
                "dailyMovePct": daily,
                "peakMovePct": alert.get("peakMovePct"),
                "ictPattern": alert.get("ictPattern"),
            })

    missed_by_type: Counter[str] = Counter()
    for row in missed:
        kind = str(row.get("momentType") or row.get("ictPattern") or "unknown")
        missed_by_type[kind] += 1

    priority = [
        "flat_then_vertical",
        "volume_awakening",
        "premium_fvg",
        "live_explosion",
        "faded_vertical_rip",
        "mega_rip",
        "building_or_watch",
    ]
    ordered = [
        {
            "type": t,
            "radarCount": buckets.get(t, 0),
            "missedCount": missed_by_type.get(t, 0),
            "examples": (examples.get(t) or [])[:3],
            "captureHint": _moment_capture_hint(t),
        }
        for t in priority
        if buckets.get(t) or missed_by_type.get(t)
    ]
    return {
        "types": ordered,
        "totalRadarMoments": sum(buckets.values()),
        "topMissedType": ordered[0]["type"] if ordered else None,
    }


def _moment_capture_hint(moment_type: str) -> str:
    return {
        "flat_then_vertical": "Enter on base break + volume (early ICT) — do not wait for 80%+",
        "explosion_extended_chase": "Skip EXPLOSIVE after +70% session move — chase kills PF",
        "volume_awakening": "Trade volume surge on BUILDING/EXPLODING immediately",
        "premium_fvg": "Premium gap-up imbalance — prioritize over faded peak chase",
        "live_explosion": "Live EXPLODING/ELITE — clear chart/breadth gates via vertical-rip bypass",
        "faded_vertical_rip": "Peak already printed — caution size or skip if velocity dead",
        "mega_rip": "ALL-IN path — extreme session move, max hold / trail",
        "building_or_watch": "Promote via ICT early break when flat base + displacement",
    }.get(moment_type, "Review skipped reasons for this moment class")


def _report_summary(
    missed: list[dict],
    passed: list[dict],
    best: Any,
    session_blocks: list[dict],
    policy: str,
    moment_taxonomy: Optional[dict[str, Any]] = None,
) -> str:
    parts: list[str] = []
    if session_blocks:
        parts.append(f"Session: {session_blocks[0].get('reason')}")
    parts.append(f"Policy: {policy}")
    if moment_taxonomy and moment_taxonomy.get("topMissedType"):
        parts.append(f"Moment class: {moment_taxonomy['topMissedType']}")
    if missed:
        top = missed[0]
        parts.append(
            f"Top miss: {top.get('symbol')} {top.get('side')} {top.get('strike')} "
            f"+{top.get('dailyMovePct', 0):.0f}% blocked by {top.get('primaryBlocker')}",
        )
    if passed and not best:
        cooldown_misses = [
            r for r in passed
            if any(g.get("gate") == "instrument_cooldown" and not g.get("passed") for g in r.get("gates") or [])
        ]
        if cooldown_misses:
            c0 = cooldown_misses[0]
            parts.append(
                f"{len(passed)} pass gates but blocked by instrument cooldown "
                f"(e.g. {c0.get('symbol')} {c0.get('strike')})",
            )
        else:
            parts.append(f"{len(passed)} would pass gates but not selected as best")
    elif best:
        parts.append(f"Best: {best.symbol} {best.mode} score={best.score:.0f}")
    elif not missed and not passed:
        parts.append("No significant explosion alerts on radar")
    return " · ".join(parts)
