"""Daily 18% capital strategy — progressive targets with confidence-gated full limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


@dataclass
class TradingLimits:
    """Per-session gates derived from progress + market confidence."""

    phase: str = "ACCUMULATE"
    confidenceTier: str = "MEDIUM"
    marketConfidence: float = 50.0
    dayMode: str = "NORMAL"
    dailyTargetInr: float = 0.0
    sessionPnlInr: float = 0.0
    progressPct: float = 0.0
    minRankScore: float = 58.0
    maxTradesToday: int = 8
    lotSizeMultiplier: float = 1.0
    allowExplosion: bool = False
    allowQuickSideways: bool = True
    allowFullLots: bool = False
    unlockFullLimits: bool = False
    message: str = ""
    playbook: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "confidenceTier": self.confidenceTier,
            "marketConfidence": round(self.marketConfidence, 1),
            "dayMode": self.dayMode,
            "dailyTargetInr": round(self.dailyTargetInr, 2),
            "sessionPnlInr": round(self.sessionPnlInr, 2),
            "progressPct": round(self.progressPct, 1),
            "minRankScore": self.minRankScore,
            "maxTradesToday": self.maxTradesToday,
            "lotSizeMultiplier": self.lotSizeMultiplier,
            "allowExplosion": self.allowExplosion,
            "allowQuickSideways": self.allowQuickSideways,
            "allowFullLots": self.allowFullLots,
            "unlockFullLimits": self.unlockFullLimits,
            "message": self.message,
            "playbook": self.playbook,
        }


_session_limits: Optional[TradingLimits] = None


def set_session_limits(limits: Optional[TradingLimits]) -> None:
    global _session_limits
    _session_limits = limits


def get_session_limits() -> Optional[TradingLimits]:
    return _session_limits


def resolve_daily_target_inr(capital_base: float) -> float:
    """Daily PnL goal — 18% of sizing capital by default."""
    settings = get_settings()
    if settings.daily_profit_target_from_capital and capital_base > 0:
        return round(capital_base * settings.daily_profit_target_pct, 2)
    return float(settings.daily_profit_target_inr)


def compute_market_confidence(snapshots: dict[str, SymbolSnapshot]) -> tuple[float, str]:
    """
    0–100 confidence from regime, breadth, TQS, explosions, day mode.
    Returns (score, day_mode_label).
    """
    settings = get_settings()
    live = [s for s in snapshots.values() if s.dataAvailable]
    if not live:
        return 40.0, "NO_DATA"

    from app.engines.chop_day_guards import chop_guard_summary
    from app.engines.expiry_day_guards import expiry_guard_summary, is_expiry_session

    chop_meta = chop_guard_summary(AutoTraderState(), snapshots)
    day_mode = str(chop_meta.get("dayMode") or "NORMAL")
    expiry = expiry_guard_summary(AutoTraderState(), snapshots)

    score = 42.0
    tqs_vals = [float(s.tradeQualityScore or 0) for s in live]
    score += min(18, sum(tqs_vals) / len(tqs_vals) * 0.35)

    regimes = [
        str(s.regime.value if hasattr(s.regime, "value") else s.regime) for s in live
    ]
    if any(r == "TREND_EXPANSION" for r in regimes):
        score += 14
    elif all(r == "RANGE_BOUND" for r in regimes):
        score -= 6

    biases = [(s.breadth.bias or "NEUTRAL").upper() for s in live]
    if biases and all(b == biases[0] and b != "NEUTRAL" for b in biases):
        score += 12
    elif biases.count("NEUTRAL") == len(biases):
        score -= 4

    top_scores: list[float] = []
    for s in live:
        top = s.topExplosion or {}
        if top.get("score"):
            top_scores.append(float(top["score"]))
        if s.explosiveRunner and (s.explosiveRunner.score or 0) > 0:
            top_scores.append(float(s.explosiveRunner.score))
    if top_scores:
        score += min(20, max(top_scores) * 0.22)

    if chop_meta.get("momentumRally"):
        score += 8
    dm_upper = day_mode.upper()
    if any(x in dm_upper for x in ("BULLISH", "BEARISH")) and "MIXED" not in dm_upper:
        score += 10
    if "RALLY" in dm_upper:
        score += 6
    if is_expiry_session(snapshots):
        score -= 6
        if expiry.get("worstDay"):
            score -= 10

    score = max(0.0, min(100.0, score))
    return round(score, 1), day_mode


def _confidence_tier(score: float) -> str:
    settings = get_settings()
    if score >= settings.daily_18pct_elite_confidence_min:
        return "ELITE"
    if score >= settings.daily_18pct_high_confidence_min:
        return "HIGH"
    if score >= settings.daily_18pct_medium_confidence_min:
        return "MEDIUM"
    return "LOW"


def _session_phase(progress_pct: float, target_hit: bool) -> str:
    if target_hit and progress_pct >= 100:
        return "EXTEND"
    if progress_pct >= 70:
        return "PROTECT"
    if progress_pct >= 35:
        return "BUILD"
    return "ACCUMULATE"


def compute_trading_limits(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState,
    *,
    session_pnl: float,
    capital_base: float,
    trades_today: int = 0,
) -> TradingLimits:
    """Confidence + progress playbook for all day types."""
    settings = get_settings()
    target = resolve_daily_target_inr(capital_base)
    progress = (session_pnl / target * 100) if target > 0 else 0.0
    target_hit = session_pnl >= target
    phase = _session_phase(progress, target_hit)

    conf_score, day_mode = compute_market_confidence(snapshots)
    tier = _confidence_tier(conf_score)

    unlock_full = (
        conf_score >= settings.daily_18pct_unlock_full_limits_min_confidence
        and (target_hit or progress >= 85)
    )

    limits = TradingLimits(
        phase=phase,
        confidenceTier=tier,
        marketConfidence=conf_score,
        dayMode=day_mode,
        dailyTargetInr=target,
        sessionPnlInr=session_pnl,
        progressPct=progress,
    )

    playbook: list[str] = []

    # Base rank / mode by day type
    if "EXPIRY WORST" in day_mode or expiry_worst_day(day_mode):
        limits.minRankScore = settings.daily_18pct_expiry_min_rank
        limits.maxTradesToday = settings.daily_18pct_expiry_max_trades
        limits.allowExplosion = tier in ("HIGH", "ELITE")
        limits.lotSizeMultiplier = 0.55 if tier == "LOW" else 0.75
        playbook.append("Expiry worst — morning scalps only, high rank")
    elif "EXPIRY" in day_mode:
        limits.minRankScore = settings.daily_18pct_expiry_min_rank
        limits.maxTradesToday = settings.daily_18pct_expiry_max_trades + 2
        limits.allowExplosion = tier != "LOW"
        limits.lotSizeMultiplier = 0.65 if tier == "LOW" else 0.85
        playbook.append("Expiry day — selective entries, dual-side only when chop")
    elif "CHOP" in day_mode or "RALLY" in day_mode:
        limits.minRankScore = settings.quick_sideways_min_rank_score
        limits.allowQuickSideways = True
        limits.maxTradesToday = settings.daily_18pct_chop_max_trades
        limits.lotSizeMultiplier = 0.6 if tier == "LOW" else 0.8
        limits.allowExplosion = tier in ("HIGH", "ELITE") or "RALLY" in day_mode
        playbook.append("Chop/sideways — quick scalps build toward 18%")
    elif "BULLISH" in day_mode or "BEARISH" in day_mode:
        limits.minRankScore = settings.best_trades_min_rank_score - 4
        limits.allowExplosion = tier != "LOW"
        limits.maxTradesToday = settings.controlled_max_trades_per_day + 2
        limits.lotSizeMultiplier = 0.85
        playbook.append("Directional day — trade aligned side, hold runners on HIGH conf")
    else:
        limits.minRankScore = settings.pretrade_min_rank_score
        limits.maxTradesToday = settings.controlled_max_trades_per_day
        limits.allowExplosion = tier in ("HIGH", "ELITE")
        limits.lotSizeMultiplier = 0.75 if tier == "LOW" else 1.0
        playbook.append("Normal session — standard gates until confidence rises")

    # Phase adjustments (progress toward 18%)
    if phase == "ACCUMULATE":
        limits.allowQuickSideways = True
        limits.minRankScore = min(limits.minRankScore, settings.quick_sideways_min_rank_score)
        limits.lotSizeMultiplier = min(limits.lotSizeMultiplier, 0.7 if tier == "LOW" else 0.85)
        playbook.append(f"Accumulate ({progress:.0f}% of ₹{target:,.0f}) — base hits from quick trades")
    elif phase == "BUILD":
        limits.minRankScore = max(limits.minRankScore, settings.pretrade_min_rank_score)
        playbook.append(f"Build ({progress:.0f}%) — add quality setups toward daily 18%")
    elif phase == "PROTECT":
        limits.minRankScore = max(limits.minRankScore, settings.daily_18pct_high_confidence_min - 6)
        limits.lotSizeMultiplier = min(limits.lotSizeMultiplier, 0.8)
        limits.allowExplosion = tier in ("HIGH", "ELITE")
        playbook.append(f"Protect ({progress:.0f}%) — only stronger signals until target hit")
    elif phase == "EXTEND":
        limits.minRankScore = settings.daily_18pct_high_confidence_min
        limits.allowExplosion = tier in ("HIGH", "ELITE")
        playbook.append(f"Target hit (18% = ₹{target:,.0f}) — extend only on HIGH confidence")

    # Confidence tier overrides
    if tier == "LOW":
        limits.allowExplosion = False
        limits.allowFullLots = False
        limits.lotSizeMultiplier = min(limits.lotSizeMultiplier, 0.55)
        limits.minRankScore = min(limits.minRankScore, settings.quick_sideways_min_rank_score)
        playbook.append("Low confidence — quick sideways only, reduced size")
    elif tier == "MEDIUM":
        limits.allowFullLots = False
        limits.lotSizeMultiplier = min(limits.lotSizeMultiplier, 0.85)
        if not limits.allowExplosion:
            playbook.append("Medium confidence — no full-size explosion unless rally")
    elif tier == "HIGH":
        limits.allowExplosion = True
        limits.lotSizeMultiplier = max(limits.lotSizeMultiplier, 0.9)
        playbook.append("High confidence — explosions + full rank gates OK")
    elif tier == "ELITE":
        limits.allowExplosion = True
        limits.allowFullLots = True
        limits.lotSizeMultiplier = 1.0
        limits.minRankScore = max(settings.quick_sideways_min_rank_score, limits.minRankScore - 4)
        playbook.append("Elite confidence — full limits unlocked")

    if unlock_full:
        limits.unlockFullLimits = True
        limits.allowFullLots = True
        limits.maxTradesToday = max(
            limits.maxTradesToday,
            settings.daily_18pct_full_limit_max_trades,
        )
        limits.lotSizeMultiplier = 1.0
        playbook.append("18% in sight + elite setup — maximum sizing allowed")

    if trades_today >= limits.maxTradesToday:
        playbook.append(f"Daily trade cap reached ({trades_today}/{limits.maxTradesToday})")

    from app.engines.morning_premium_capture import in_morning_premium_capture_window, morning_capture_active

    if in_morning_premium_capture_window() and morning_capture_active(snapshots):
        limits.allowExplosion = True
        limits.minRankScore = min(limits.minRankScore, settings.morning_capture_min_rank_score)
        playbook.append("Morning premium capture — BUILDING+ explosions enabled")

    if settings.day_adaptive_enabled:
        from app.engines.day_adaptive_engine import build_day_adaptive_profile, apply_profile_to_limits

        adaptive = build_day_adaptive_profile(day_mode, tier, snapshots, phase=phase, state=state)
        apply_profile_to_limits(adaptive, limits)
        playbook.extend(adaptive.playbook)

    limits.playbook = playbook
    limits.message = (
        f"{phase} · {tier} conf ({conf_score:.0f}) · "
        f"₹{session_pnl:,.0f} / ₹{target:,.0f} ({progress:.0f}%) · {day_mode}"
    )
    return limits


def expiry_worst_day(day_mode: str) -> bool:
    return "EXPIRY WORST" in (day_mode or "").upper()


def entries_allowed_by_limits(
    limits: TradingLimits,
    candidate_mode: str,
    candidate_score: float,
    trades_today: int,
) -> tuple[bool, str]:
    """Gate a candidate against daily 18% strategy limits."""
    settings = get_settings()
    if not settings.daily_18pct_strategy_enabled:
        return True, "ok"

    if trades_today >= limits.maxTradesToday:
        return False, f"daily_18pct_trade_cap_{trades_today}"

    if candidate_mode == "explosion" and not limits.allowExplosion:
        return False, "daily_18pct_explosion_blocked_low_confidence"

    if candidate_mode == "quick_sideways" and not limits.allowQuickSideways:
        return False, "daily_18pct_quick_sideways_blocked"

    if candidate_score < limits.minRankScore:
        return False, f"daily_18pct_rank_below_{limits.minRankScore:.0f}"

    if limits.phase == "EXTEND" and limits.confidenceTier not in ("HIGH", "ELITE"):
        return False, "daily_18pct_extend_requires_high_confidence"

    return True, "ok"


def scale_lots_for_limits(lots: int, limits: TradingLimits) -> int:
    if not get_settings().daily_18pct_strategy_enabled:
        return lots
    if limits.allowFullLots and limits.unlockFullLimits:
        return lots
    mult = max(0.25, min(1.0, limits.lotSizeMultiplier))
    scaled = max(1, int(lots * mult))
    return scaled if scaled > 0 else 0
