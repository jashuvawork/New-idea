"""Market psychology — fear/greed, sentiment, and exit bias from live context."""

from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.schemas import Breadth, Greeks, Orderflow, Regime, SymbolSnapshot


@dataclass
class PsychologyState:
    score: float = 0.0  # -100 fear … +100 greed
    label: str = "NEUTRAL"
    fear_greed_index: float = 50.0
    news_bias: str = "NEUTRAL"
    breadth_bias: str = "NEUTRAL"
    iv_stress: str = "NORMAL"
    momentum_state: str = "BALANCED"
    analysis: str = ""
    exit_bias: str = "BALANCED"  # TIGHT_STOPS | BALANCED | LET_RUNNERS
    factors: dict[str, float] = field(default_factory=dict)


def _news_score(news: list[dict[str, Any]]) -> tuple[float, str]:
    if not news:
        return 0.0, "NEUTRAL"
    scores = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}
    total = sum(scores.get(n.get("sentiment", "NEUTRAL"), 0) for n in news[:8])
    avg = total / min(8, len(news))
    if avg > 0.25:
        return avg * 100, "BULLISH"
    if avg < -0.25:
        return avg * 100, "BEARISH"
    return avg * 50, "NEUTRAL"


def analyze_psychology(
    snap: SymbolSnapshot,
    news: Optional[list[dict[str, Any]]] = None,
) -> PsychologyState:
    """Synthesize market psychology from breadth, PCR, IV, orderflow, constituents, news."""
    factors: dict[str, float] = {}
    score = 0.0

    # PCR — crowd positioning
    pcr = snap.pcr or 1.0
    if pcr > 1.25:
        factors["pcr_fear"] = min(30, (pcr - 1.0) * 40)
        score += factors["pcr_fear"] * 0.3
        pcr_mood = "FEAR"
    elif pcr < 0.75:
        factors["pcr_greed"] = min(30, (1.0 - pcr) * 40)
        score -= factors["pcr_greed"] * 0.3
        pcr_mood = "GREED"
    else:
        pcr_mood = "BALANCED"

    # Breadth — index internals
    b = snap.breadth
    factors["breadth"] = (b.score - 50) * 0.8
    score += factors["breadth"] * 0.35

    # Constituent heatmap
    if snap.constituentHeatmap and snap.constituentHeatmap.dataAvailable:
        cb = snap.constituentHeatmap.breadthPct - 50
        factors["constituents"] = cb * 0.6
        score += factors["constituents"] * 0.25

    # IV stress
    iv_rank = snap.greeks.ivRank or 50
    iv_exp = snap.greeks.ivExpansion or 1.0
    if iv_rank > 70 or iv_exp > 1.15:
        factors["iv_fear"] = min(25, (iv_rank - 50) * 0.4)
        score += factors["iv_fear"] * 0.2
        iv_stress = "ELEVATED"
    elif iv_rank < 30:
        iv_stress = "COMPLACENT"
        factors["iv_complacent"] = -10
        score -= 5
    else:
        iv_stress = "NORMAL"

    # Momentum / euphoria
    vel = snap.orderflow.volumeAcceleration or 0
    tick = snap.orderflow.tickMomentum or 0
    if vel > 75 and tick > 70:
        factors["euphoria_risk"] = 20
        score += 15
        momentum_state = "EUPHORIA"
    elif vel > 55:
        momentum_state = "MOMENTUM"
    elif vel < 25:
        momentum_state = "DULL"
        score -= 5
    else:
        momentum_state = "BALANCED"

    # Regime
    regime = snap.regime
    regime_val = regime.value if hasattr(regime, "value") else str(regime)
    if regime_val == "CHOP":
        factors["chop_uncertainty"] = -8
        score -= 8
    elif regime_val == "TREND_EXPANSION":
        factors["trend_confidence"] = 10
        score += 10

    news_items = news or []
    news_val, news_bias = _news_score(news_items)
    factors["news"] = news_val
    score += news_val * 0.2

    score = max(-100, min(100, score))
    fear_greed = max(0, min(100, 50 + score * 0.5))

    if score >= 35:
        label = "EUPHORIA"
        exit_bias = "TIGHT_TRAIL"
    elif score >= 15:
        label = "GREED"
        exit_bias = "LET_RUNNERS"
    elif score <= -35:
        label = "FEAR"
        exit_bias = "TIGHT_STOPS"
    elif score <= -15:
        label = "CAUTION"
        exit_bias = "TIGHT_STOPS"
    else:
        label = "NEUTRAL"
        exit_bias = "BALANCED"

    analysis_parts = [
        f"Psychology: {label} (score {score:+.0f}, fear/greed {fear_greed:.0f}).",
        f"PCR mood {pcr_mood}, breadth {b.bias}, news {news_bias}.",
    ]
    if snap.constituentHeatmap and snap.constituentHeatmap.dataAvailable:
        analysis_parts.append(
            f"Constituents {snap.constituentHeatmap.advancing}↑/{snap.constituentHeatmap.declining}↓."
        )
    if exit_bias == "LET_RUNNERS":
        analysis_parts.append("Favor wider targets and trailing — momentum supports runners.")
    elif exit_bias == "TIGHT_STOPS":
        analysis_parts.append("Favor tighter stops and quicker profit locks — risk elevated.")
    elif exit_bias == "TIGHT_TRAIL":
        analysis_parts.append("Euphoria risk — arm trailing stops early, avoid chasing.")

    return PsychologyState(
        score=round(score, 1),
        label=label,
        fear_greed_index=round(fear_greed, 1),
        news_bias=news_bias,
        breadth_bias=b.bias,
        iv_stress=iv_stress,
        momentum_state=momentum_state,
        analysis=" ".join(analysis_parts),
        exit_bias=exit_bias,
        factors=factors,
    )


def psychology_to_dict(ps: PsychologyState) -> dict[str, Any]:
    return {
        "score": ps.score,
        "label": ps.label,
        "fearGreedIndex": ps.fear_greed_index,
        "newsBias": ps.news_bias,
        "breadthBias": ps.breadth_bias,
        "ivStress": ps.iv_stress,
        "momentumState": ps.momentum_state,
        "analysis": ps.analysis,
        "exitBias": ps.exit_bias,
        "factors": ps.factors,
    }
