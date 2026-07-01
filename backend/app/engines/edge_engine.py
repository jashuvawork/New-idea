"""Realtime edge engine — statistical entry scoring, PF feedback, momentum-aware exits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.engines.pretrade_validator import TradeRecord, analyze_last_n_trades, collect_session_trades
from app.models.schemas import AutoTraderState, PaperTrade, Side, SpotChart, SymbolSnapshot, StrategyType


@dataclass
class EdgeScore:
    total: float = 0.0
    timing: float = 0.0
    momentum: float = 0.0
    chart: float = 0.0
    ml: float = 0.0
    session: float = 0.0
    lot_scale: float = 1.0
    min_rank_adjust: float = 0.0
    tighten_exits: bool = False
    let_runners: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "timing": round(self.timing, 1),
            "momentum": round(self.momentum, 1),
            "chart": round(self.chart, 1),
            "ml": round(self.ml, 1),
            "session": round(self.session, 1),
            "lotScale": round(self.lot_scale, 2),
            "minRankAdjust": round(self.min_rank_adjust, 1),
            "tightenExits": self.tighten_exits,
            "letRunners": self.let_runners,
            "reasons": self.reasons[:6],
        }


@dataclass
class SessionPfFeedback:
    profit_factor: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    lot_scale: float = 1.0
    rank_penalty: float = 0.0
    tighten_exits: bool = False
    pause_quick_scalps: bool = False
    message: str = ""


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def session_pf_feedback(state: AutoTraderState, lookback: int = 10) -> SessionPfFeedback:
    """Rolling session PF drives lot size and exit tightness toward 2.5+ target."""
    settings = get_settings()
    trades = collect_session_trades(state)
    recent = trades[-lookback:] if trades else []
    if len(recent) < 3:
        return SessionPfFeedback(message="insufficient_session_trades")

    summary = analyze_last_n_trades(recent, len(recent))
    pf = float(summary.get("profitFactor") or 0)
    wins = int(summary.get("wins") or 0)
    count = int(summary.get("count") or 0)
    wr = (wins / count * 100) if count else 0.0

    fb = SessionPfFeedback(
        profit_factor=pf,
        win_rate=wr,
        trade_count=count,
    )

    target = settings.edge_session_pf_target
    tighten_below = settings.edge_session_pf_tighten_below

    if pf >= target:
        fb.lot_scale = 1.0
        fb.message = f"session_pf_{pf:.2f}_on_target"
    elif pf >= 2.0:
        fb.lot_scale = 0.92
        fb.message = f"session_pf_{pf:.2f}_building"
    elif pf >= tighten_below:
        fb.lot_scale = 0.75
        fb.rank_penalty = 4.0
        fb.tighten_exits = True
        fb.message = f"session_pf_{pf:.2f}_cautious"
    else:
        fb.lot_scale = 0.55
        fb.rank_penalty = 8.0
        fb.tighten_exits = True
        fb.pause_quick_scalps = True
        fb.message = f"session_pf_{pf:.2f}_defensive"

    return fb


def _chart_edge(side: Side | str, chart: Optional[SpotChart]) -> tuple[float, list[str]]:
    if not chart:
        return 8.0, []
    reasons: list[str] = []
    score = 10.0
    side_v = _side_val(side)
    direction = (chart.direction or "NEUTRAL").upper()
    macd = (chart.macdBias or "NEUTRAL").upper()
    rsi = float(chart.rsi or 50)

    if side_v == "CALL":
        if direction == "BULLISH":
            score += 8
            reasons.append("chart_bullish")
        if macd == "BULLISH":
            score += 6
            reasons.append("macd_bullish")
        if 45 <= rsi <= 68:
            score += 5
        elif rsi > 72:
            score -= 4
            reasons.append("rsi_overbought_entry")
    else:
        if direction == "BEARISH":
            score += 8
        if macd == "BEARISH":
            score += 6
        if 32 <= rsi <= 55:
            score += 5
        elif rsi < 28:
            score -= 4

    mom5 = abs(chart.momentum5Pct or 0)
    score += min(8, mom5 * 40)
    score += min(10, (chart.trendStrength or 0) * 0.12)
    return min(40.0, score), reasons


def _timing_edge(snap: SymbolSnapshot) -> tuple[float, list[str]]:
    settings = get_settings()
    reasons: list[str] = []
    score = 12.0

    from app.engines.morning_premium_capture import in_morning_premium_capture_window
    from app.engines.chop_day_guards import in_momentum_rally_window
    from app.engines.session_timing import in_open_caution_window, in_midday_chop_window

    if in_morning_premium_capture_window():
        score += 14
        reasons.append("morning_capture_window")
    elif in_momentum_rally_window():
        score += 10
        reasons.append("momentum_rally_window")
    if in_open_caution_window():
        score -= 6
        reasons.append("open_caution")
    if in_midday_chop_window():
        score -= 8
        reasons.append("midday_chop")

    if snap.breadth.aligned:
        score += 6
        reasons.append("breadth_aligned")

    regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime)
    if regime == "TREND_EXPANSION":
        score += 8
    elif regime == "RANGE_BOUND":
        score += 2

    return max(0.0, min(25.0, score)), reasons


def _momentum_edge(
    velocity_3s: float,
    velocity_9s: float = 0.0,
    volume_surge: float = 1.0,
    explosion_score: float = 0.0,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if velocity_3s >= 4.0:
        score += 18
        reasons.append("vel3s_hot")
    elif velocity_3s >= 2.5:
        score += 14
        reasons.append("vel3s_strong")
    elif velocity_3s >= 1.2:
        score += 8
    elif velocity_3s >= 0.5:
        score += 4

    if velocity_9s >= 3.5:
        score += 8
    if volume_surge >= 1.8:
        score += 6
        reasons.append("volume_surge")
    elif volume_surge >= 1.3:
        score += 3

    if explosion_score >= 55:
        score += 8
    elif explosion_score >= 40:
        score += 4

    return min(30.0, score), reasons


def compute_entry_edge(
    candidate: Any,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    *,
    ml_win_prob: Optional[float] = None,
) -> EdgeScore:
    """0–100 realtime edge score — higher = better timing + probability."""
    settings = get_settings()
    if not settings.edge_engine_enabled:
        return EdgeScore(total=60.0, lot_scale=1.0)

    side = getattr(candidate, "side", Side.CALL)
    vel3 = 0.0
    vel9 = 0.0
    vol = 1.0
    expl_score = 0.0
    ev = getattr(candidate, "explosion_event", None)
    if ev:
        vel3 = float(ev.velocity_3s or 0)
        vel9 = float(ev.velocity_9s or 0)
        vol = float(ev.volume_surge or 1.0)
        expl_score = float(ev.explosion_score or 0)
    else:
        meta = getattr(candidate, "pretrade_meta", {}) or {}
        vel3 = float(meta.get("velocityPct") or 0)
        runner = snap.explosiveRunner
        if runner and runner.signal:
            vel3 = max(vel3, float(runner.signal.premiumVelocityPct or 0))
            vol = max(vol, float(runner.signal.volumeSurge or 1.0))

    timing, t_reasons = _timing_edge(snap)
    momentum, m_reasons = _momentum_edge(vel3, vel9, vol, expl_score)
    chart, c_reasons = _chart_edge(side, snap.spotChart)

    ml_score = 10.0
    if ml_win_prob is not None:
        if ml_win_prob >= 0.72:
            ml_score = 22.0
        elif ml_win_prob >= 0.58:
            ml_score = 16.0
        elif ml_win_prob <= 0.42:
            ml_score = 4.0

    tqs = float(getattr(candidate, "tqs", snap.tradeQualityScore) or 0)
    session_score = min(15.0, tqs * 0.18)

    pf_fb = session_pf_feedback(state)
    session_score += max(0.0, (pf_fb.profit_factor - 1.0) * 4)

    total = min(100.0, timing + momentum + chart + ml_score + session_score)
    reasons = t_reasons + m_reasons + c_reasons
    reasons.append(pf_fb.message)

    lot_scale = pf_fb.lot_scale
    if total >= settings.edge_min_score_for_full_size:
        lot_scale = min(1.0, lot_scale * min(1.0, 0.85 + (total - 72) * 0.005))
    elif total >= settings.edge_min_score_for_entry:
        lot_scale = min(lot_scale, 0.55 + (total - 52) * 0.01)
    else:
        lot_scale = min(lot_scale, settings.edge_lot_scale_min)

    let_runners = total >= 78 and pf_fb.profit_factor >= 2.0
    tighten = pf_fb.tighten_exits or total < 58

    if let_runners:
        reasons.append("let_runners_mode")
    if tighten:
        reasons.append("tighten_exits_pf")

    return EdgeScore(
        total=round(total, 1),
        timing=round(timing, 1),
        momentum=round(momentum, 1),
        chart=round(chart, 1),
        ml=round(ml_score, 1),
        session=round(session_score, 1),
        lot_scale=round(max(settings.edge_lot_scale_min, min(settings.edge_lot_scale_max, lot_scale)), 2),
        min_rank_adjust=pf_fb.rank_penalty,
        tighten_exits=tighten,
        let_runners=let_runners,
        reasons=reasons,
    )


def scale_lots_by_edge(lots: int, edge: EdgeScore) -> int:
    if lots <= 0:
        return 0
    scaled = max(1, int(lots * edge.lot_scale))
    return scaled


def edge_rank_bonus(edge: EdgeScore) -> float:
    if edge.total >= 85:
        return 12.0
    if edge.total >= 72:
        return 8.0
    if edge.total >= 60:
        return 4.0
    if edge.total < 52:
        return -8.0
    return 0.0


def tune_plan_with_edge(
    plan: Any,
    edge: EdgeScore,
    chart: Optional[SpotChart] = None,
    entry_velocity_3s: float = 0.0,
) -> Any:
    """Adjust adaptive exit plan from edge score + chart."""
    settings = get_settings()
    if not settings.edge_engine_enabled:
        return plan

    if edge.let_runners:
        plan.targetPoints = round(plan.targetPoints * 1.15, 2)
        plan.trailArmPoints = round(plan.trailArmPoints * 1.12, 2)
        plan.trailKeepRatio = round(min(0.78, plan.trailKeepRatio + 0.06), 2)
        plan.microTargetPoints = round(max(plan.microTargetPoints, 3.5), 2)
        plan.reasoning = (plan.reasoning or []) + ["edge_let_runners"]
    elif edge.tighten_exits:
        plan.stopPoints = round(max(settings.scalp_stop_min_points, plan.stopPoints * 0.92), 2)
        plan.trailKeepRatio = round(max(0.48, plan.trailKeepRatio - 0.04), 2)
        plan.microTargetPoints = round(plan.microTargetPoints * 0.95, 2)
        plan.reasoning = (plan.reasoning or []) + ["edge_tighten_exits"]

    if chart and entry_velocity_3s >= 2.5:
        if (chart.macdBias or "").upper() == "BULLISH":
            plan.stopPoints = round(plan.stopPoints * 1.08, 2)
            plan.trailArmPoints = round(plan.trailArmPoints * 1.05, 2)
            plan.reasoning = (plan.reasoning or []) + ["macd_confirms_hold"]

    return plan


def check_edge_realtime_exit(
    trade: PaperTrade,
    current_premium: float,
    snap: Optional[SymbolSnapshot],
    *,
    current_velocity_3s: float = 0.0,
    lot_multiplier: int = 1,
) -> tuple[Optional[str], float]:
    """
    Statistical realtime exits — momentum exhaustion, RSI overbought lock, PF giveback.
  """
    settings = get_settings()
    if not settings.edge_engine_enabled:
        return None, 0.0

    pnl_pts = current_premium - trade.entryPremium
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    best = max(trade.bestPnlPoints, pnl_pts)
    if best <= 0:
        return None, pnl_inr

    ctx = trade.entryContext or {}
    entry_vel = float(ctx.get("velocity3s") or ctx.get("entryVelocity3s") or 0)
    edge_total = float((ctx.get("edgeScore") or {}).get("total") or 0)

    # Momentum exhaustion — premium still up but velocity collapsed
    if entry_vel >= 1.5 and best >= 2.0:
        ratio = settings.edge_velocity_exhaustion_ratio
        if current_velocity_3s < entry_vel * ratio and pnl_pts >= max(1.5, best * 0.55):
            return "edge_momentum_exhaustion", pnl_inr

    chart = snap.spotChart if snap else None
    side_v = _side_val(trade.side)

    if chart and pnl_pts > 0:
        rsi = float(chart.rsi or 50)
        if side_v == "CALL" and rsi >= settings.edge_rsi_overbought_exit and best >= 3.0:
            if pnl_pts < best * 0.88:
                return "edge_rsi_overbought_giveback", pnl_inr
            if current_velocity_3s < 0.8:
                return "edge_rsi_overbought_fade", pnl_inr

        if settings.edge_macd_fade_exit_enabled:
            macd = (chart.macdBias or "NEUTRAL").upper()
            if side_v == "CALL" and macd == "BEARISH" and best >= 4.0 and pnl_pts < best * 0.75:
                return "edge_macd_fade_lock", pnl_inr
            if side_v == "PUT" and macd == "BULLISH" and best >= 4.0 and pnl_pts < best * 0.75:
                return "edge_macd_fade_lock", pnl_inr

    # High-edge trades get more room; low-edge take profit earlier on giveback
    if edge_total > 0 and edge_total < 58 and best >= 2.5:
        if best - pnl_pts >= 1.5:
            return "edge_low_score_profit_lock", pnl_inr

    return None, pnl_inr
