"""EOD 'would-have-traded' report.

Replays a completed day's premium tape through the strategy the live system now runs
(near-base first-lift entry + index-drift confirmation + ELITE full-lot sizing + FTV
runner-trail exit) WITH RE-ENTRIES, and returns the trades it would have generated
(entry, lots, SL/TP path, exit, P&L) plus a summary.

This is a hindsight simulation for review — it approximates the full live selector/gate
stack (it does not re-run every gate), so treat the numbers as indicative, not booked.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _drift_ok(spot_rel: list[tuple[float, float]], now_s: float, side: str) -> bool:
    """Index sustained-drift confirmation for one side, from the spot tape up to now."""
    import app.engines.index_tick_helpers as ith

    ith._ltp_history["SENSEX"] = deque(
        (ts, s) for ts, s in spot_rel if now_s - 120 <= ts <= now_s
    )
    ith._ltp_history["NIFTY"] = ith._ltp_history["SENSEX"]
    return bool(ith.recent_index_drift("SENSEX", side)["drift"])


def replay_contract_trades(
    *,
    symbol: str,
    side: str,
    strike: float,
    tier: str,
    series: list[tuple[datetime, float, float]],
    spot_rel: list[tuple[float, float]],
    t0: datetime,
    settings: Any = None,
    max_trades: int = 4,
) -> list[dict[str, Any]]:
    """Replay one contract with RE-ENTRIES → list of would-have-traded records."""
    from app.engines.capital_allocator import lot_multiplier, max_lots_for_capital
    from app.engines.explosion_profit import evaluate_explosion_exit
    from app.engines.moment_stage_trail import build_moment_stage_plan
    from app.models.schemas import PaperTrade, Side, StrategyType

    s = settings or get_settings()
    units = int(lot_multiplier(symbol) or 20)
    risk = _f(getattr(s, "elite_full_lot_risk_inr", 10_000.0), 10_000.0)
    est = _f(getattr(s, "elite_full_lot_est_stop_points", 8.0), 8.0)
    cap = _f(getattr(s, "max_sizing_capital_inr", 200_000.0), 200_000.0)
    nb_min, nb_max = 0.10, 0.25
    cooldown = 90.0

    trades: list[dict[str, Any]] = []
    win: deque[tuple[datetime, float]] = deque()
    i = 0
    n = len(series)
    wnow = datetime.now(IST)
    next_ok_after = series[0][0] if series else None
    while i < n and len(trades) < max_trades:
        t, p, sp = series[i]
        win.append((t, p))
        while win and (t - win[0][0]).total_seconds() > 1200:
            win.popleft()
        base = min(x[1] for x in win)
        off = (p - base) / base if base > 0 else 0.0
        entered = (
            base > 0 and nb_min <= off <= nb_max and p >= 15
            and (next_ok_after is None or t >= next_ok_after)
            and _drift_ok(spot_rel, (t - t0).total_seconds(), side)
        )
        if not entered:
            i += 1
            continue
        # --- ENTER near the base ---
        ep = p
        lots = max(1, min(
            max_lots_for_capital(symbol, ep),
            int(risk / (est * units)),
            int(0.35 * cap / (ep * units)),
        ))
        plan = build_moment_stage_plan(
            entry_premium=ep, base_premium=base, velocity_3s=3.0, volume_surge=2.5,
            session_move_pct=30.0, flat_then_vertical=True, max_profit=True,
        )
        ctx = {
            "momentType": "flat_then_vertical", "ictFlatThenVertical": True,
            "maxProfitCapture": True, "ictBasePremium": base, "eliteFullLot": True,
            "velocity3s": 3.0,
        }
        if plan:
            ctx.update(plan)
        tr = PaperTrade(
            id=f"{symbol}:{side}:{strike}", symbol=symbol, side=Side(side), strike=strike,
            entryPremium=ep, currentPremium=ep, lots=lots,
            strategyType=StrategyType.EXPLOSIVE, openedAt=wnow, bestPnlPoints=0.0,
            entryContext=ctx,
        )
        best = 0.0
        peak = ep
        et = t
        exit_rec = None
        j = i
        while j < n:
            tj, pj, _spj = series[j]
            tr.openedAt = wnow - timedelta(seconds=(tj - et).total_seconds())
            tr.currentPremium = pj
            best = max(best, pj - ep)
            tr.bestPnlPoints = best
            peak = max(peak, pj)
            v = 2.0 if pj >= peak else -0.8
            tr.entryContext["liveVelocity3s"] = v
            reason, _pnl = evaluate_explosion_exit(tr, pj, tier, units, live_velocity_3s=v)
            if reason:
                exit_rec = (tj, pj, reason)
                break
            j += 1
        if exit_rec is None:
            exit_rec = (series[-1][0], series[-1][1], "eod_close")
        xt, xp, reason = exit_rec
        pnl = (xp - ep) * lots * units
        trades.append({
            "symbol": symbol, "side": side, "strike": strike, "tier": tier,
            "entryAt": et.strftime("%H:%M:%S"), "entryPremium": round(ep, 1),
            "basePremium": round(base, 1), "offBasePct": round(off * 100, 1),
            "lots": lots, "exitAt": xt.strftime("%H:%M:%S"), "exitPremium": round(xp, 1),
            "movePct": round((xp - ep) / ep * 100, 1), "peakPct": round(best / ep * 100, 1),
            "pnlInr": round(pnl, 0), "exitReason": reason,
            "_entryDt": et, "_exitDt": xt,
        })
        # advance past the exit + cooldown for a possible re-entry
        i = max(j + 1, i + 1)
        next_ok_after = xt + timedelta(seconds=cooldown)
    return trades


def generate_eod_trade_report(date: str, *, top_n: int = 8) -> dict[str, Any]:
    """Read the day's tape, pick the strongest contracts, replay with re-entries."""
    settings = get_settings()
    from app.services.radar_archive import read_archive_entries
    from app.services.radar_learning import read_premium_tape

    entries = read_archive_entries(date)
    # Rank candidates by realised max favourable excursion (the real opportunities).
    ranked = []
    for e in entries:
        o = e.get("outcome") or {}
        alert = e.get("alert") or {}
        tier = str(e.get("tier") or alert.get("tier") or "").upper()
        if tier not in ("ELITE", "EXPLODING"):
            continue
        ranked.append((
            _f(o.get("mfePct")), str(e.get("symbol") or "").upper(),
            str(e.get("side") or "").upper(), _f(e.get("strike")), tier,
        ))
    ranked.sort(reverse=True)
    targets = ranked[:top_n]
    if not targets:
        return {"date": date, "status": "no_top_candidates", "trades": []}

    batches = read_premium_tape(date)
    if not batches:
        return {"date": date, "status": "no_tape", "trades": []}

    # Build per-contract premium series + the shared spot tape.
    want = {(sym, side, strike) for _m, sym, side, strike, _tier in targets}
    series_map: dict[tuple, list] = {k: [] for k in want}
    spot_pairs: list[tuple[datetime, float]] = []
    seen_spot: set[str] = set()
    for b in batches:
        ts = b.get("ts")
        if not ts:
            continue
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            continue
        for c in b.get("contracts", []):
            key = (str(c.get("symbol") or "").upper(), str(c.get("side") or "").upper(),
                   _f(c.get("strike")))
            if key in want:
                series_map[key].append((t, _f(c.get("premium")), _f(c.get("spot"))))
                if ts not in seen_spot and _f(c.get("spot")) > 0:
                    seen_spot.add(ts)
                    spot_pairs.append((t, _f(c.get("spot"))))
    spot_pairs.sort()
    if not spot_pairs:
        return {"date": date, "status": "no_spot", "trades": []}
    t0 = spot_pairs[0][0]
    spot_rel = [((t - t0).total_seconds(), sp) for t, sp in spot_pairs]

    candidates: list[dict[str, Any]] = []
    for _m, sym, side, strike, tier in targets:
        ser = sorted(x for x in series_map.get((sym, side, strike), []) if x[1] > 0)
        if len(ser) < 10:
            continue
        candidates.extend(replay_contract_trades(
            symbol=sym, side=side, strike=strike, tier=tier,
            series=ser, spot_rel=spot_rel, t0=t0, settings=settings,
        ))

    taken = apply_portfolio_limits(candidates, settings=settings)
    for t in taken:
        t.pop("_entryDt", None)
        t.pop("_exitDt", None)
    total = round(sum(_f(t.get("pnlInr")) for t in taken), 0)
    wins = sum(1 for t in taken if _f(t.get("pnlInr")) > 0)
    daily_stop = _f(getattr(settings, "daily_loss_stop_inr", 20_000.0), 20_000.0)
    return {
        "date": date,
        "status": "ok",
        "tradeCount": len(taken),
        "candidateCount": len(candidates),
        "wins": wins,
        "losses": len(taken) - wins,
        "netPnlInr": total,
        "dailyLossStopInr": daily_stop,
        "note": (
            "Hindsight simulation (approximate). Applies one-position-at-a-time + the "
            "daily loss stop; still does not re-run every live gate."
        ),
        "trades": taken,
    }


def apply_portfolio_limits(
    candidates: list[dict[str, Any]],
    *,
    settings: Any = None,
) -> list[dict[str, Any]]:
    """Model the live book: one position at a time, halt for the day at the loss stop.

    The per-contract replay generates every candidate leg independently; live trading holds
    ONE position at a time and stops taking new entries once the day's loss stop is hit.
    Applying those turns an unbounded 'take everything' number into a realistic one.
    """
    s = settings or get_settings()
    daily_stop = _f(getattr(s, "daily_loss_stop_inr", 20_000.0), 20_000.0)
    ordered = sorted(candidates, key=lambda t: t.get("_entryDt") or datetime.now(IST))
    taken: list[dict[str, Any]] = []
    cum = 0.0
    open_until: Optional[datetime] = None
    for t in ordered:
        edt = t.get("_entryDt")
        xdt = t.get("_exitDt")
        if daily_stop > 0 and cum <= -abs(daily_stop):
            break  # daily loss stop hit — no more entries today
        if open_until is not None and edt is not None and edt < open_until:
            continue  # a position is already open — one at a time
        taken.append(t)
        cum += _f(t.get("pnlInr"))
        open_until = xdt
    return taken

