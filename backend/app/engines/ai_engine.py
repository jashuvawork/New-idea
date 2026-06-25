"""TQS (Trade Quality Score) — weighted AI matrix scorer."""

from typing import Any, Optional

from app.models.schemas import (
    Breadth,
    Greeks,
    HeatmapStrike,
    MarketProfile,
    Orderflow,
    Regime,
    Side,
)


def score_tqs(
    orderflow: Orderflow,
    greeks: Greeks,
    breadth: Breadth,
    profile: MarketProfile,
    spot: float,
    regime: Regime,
    runner_velocity: float = 0,
    news_sentiment: str = "NEUTRAL",
) -> tuple[float, dict[str, float]]:
    """Return TQS 0-100 and component breakdown."""
    components: dict[str, float] = {}

    # Orderflow weight 30%
    of_score = (
        orderflow.deltaVelocity * 0.35
        + orderflow.volumeAcceleration * 0.30
        + orderflow.breakoutVelocity * 0.20
        + orderflow.tickMomentum * 0.15  # enhanced fusion
    )
    components["orderflow"] = min(100, of_score)

    # Greeks / IV weight 15%
    iv_score = 50 + (greeks.ivExpansion - 1.0) * 30
    if 30 < greeks.ivRank < 70:
        iv_score += 10
    components["greeks"] = min(100, max(0, iv_score))

    # Breadth weight 20%
    breadth_score = breadth.score
    if breadth.aligned:
        breadth_score = min(100, breadth_score + 15)
    components["breadth"] = breadth_score

    # Market profile weight 15%
    profile_score = 50.0
    if profile.poc and profile.vah and profile.val:
        if profile.val <= spot <= profile.vah:
            profile_score = 65
        elif spot > profile.vah:
            profile_score = 70 if breadth.bias == "BULLISH" else 45
        elif spot < profile.val:
            profile_score = 70 if breadth.bias == "BEARISH" else 45
    components["profile"] = profile_score

    # Regime weight 10%
    regime_scores = {
        Regime.TREND_EXPANSION: 80,
        Regime.VOLATILITY_SPIKE: 75,
        Regime.RANGE_BOUND: 55,
        Regime.CHOP: 35,
    }
    components["regime"] = regime_scores.get(regime, 50)

    # Runner velocity weight 10%
    vel_score = min(100, runner_velocity * 25)
    components["velocity"] = vel_score

    # News adjustment ±5
    news_adj = {"BULLISH": 3, "BEARISH": -3, "NEUTRAL": 0}.get(news_sentiment, 0)
    components["news"] = 50 + news_adj

    weights = {
        "orderflow": 0.30,
        "greeks": 0.15,
        "breadth": 0.20,
        "profile": 0.15,
        "regime": 0.10,
        "velocity": 0.10,
        "news": 0.00,  # applied as flat adjustment
    }

    tqs = sum(components[k] * weights[k] for k in weights) + news_adj
    return min(100, max(0, round(tqs, 1))), components


def rank_runner(
    strike_data: dict[str, Any],
    side: Side,
    prev_premium: Optional[float],
) -> tuple[float, float]:
    """Score explosive runner candidate. Returns (score, velocity_pct)."""
    ltp = strike_data.get("ltp") or strike_data.get("last_price") or 0
    oi = strike_data.get("oi", 0)
    volume = strike_data.get("volume", 0)
    bid = strike_data.get("bid", 0)
    ask = strike_data.get("ask", 0)

    velocity_pct = 0.0
    if prev_premium and prev_premium > 0 and ltp:
        velocity_pct = ((ltp - prev_premium) / prev_premium) * 100

    spread_penalty = 0
    if bid and ask and ltp:
        spread_pct = ((ask - bid) / ltp) * 100 if ltp else 0
        spread_penalty = min(20, spread_pct * 5)

    oi_score = min(30, (oi / 100_000) * 10) if oi else 0
    vol_score = min(25, (volume / 10_000) * 10) if volume else 0
    vel_score = min(35, velocity_pct * 12)
    liquidity = min(10, 10 - spread_penalty)

    score = oi_score + vol_score + vel_score + liquidity
    return min(100, max(0, score)), velocity_pct


def build_breadth(chain: list[dict[str, Any]], spot: float) -> Breadth:
    """Compute market breadth from option chain OI."""
    call_oi = put_oi = 0
    for row in chain:
        call_oi += row.get("call_options", {}).get("oi", 0) or row.get("CE", {}).get("oi", 0) or 0
        put_oi += row.get("put_options", {}).get("oi", 0) or row.get("PE", {}).get("oi", 0) or 0

    total = call_oi + put_oi
    if total == 0:
        return Breadth(score=50, bias="NEUTRAL", aligned=False)

    call_pct = (call_oi / total) * 100
    if call_pct > 55:
        bias = "BULLISH"
        score = min(100, 50 + (call_pct - 50) * 2)
    elif call_pct < 45:
        bias = "BEARISH"
        score = min(100, 50 + (50 - call_pct) * 2)
    else:
        bias = "NEUTRAL"
        score = 50

    return Breadth(score=round(score, 1), bias=bias, aligned=abs(call_pct - 50) > 5)


def build_heatmap(chain: list[dict[str, Any]], spot: float, atm: float) -> list:
    """Build strike heatmap with liquidity and gamma wall detection."""
    rows: list[HeatmapStrike] = []
    max_oi = 1
    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        ce = row.get("call_options", {}) or row.get("CE", {})
        pe = row.get("put_options", {}) or row.get("PE", {})
        call_oi = ce.get("oi", 0) or 0
        put_oi = pe.get("oi", 0) or 0
        max_oi = max(max_oi, call_oi, put_oi)

    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        ce = row.get("call_options", {}) or row.get("CE", {})
        pe = row.get("put_options", {}) or row.get("PE", {})
        call_oi = ce.get("oi", 0) or 0
        put_oi = pe.get("oi", 0) or 0
        call_ltp = ce.get("ltp") or ce.get("last_price")
        put_ltp = pe.get("ltp") or pe.get("last_price")

        liq = ((call_oi + put_oi) / max_oi) * 100
        gamma_wall = abs(strike - atm) <= 50 and (call_oi > max_oi * 0.7 or put_oi > max_oi * 0.7)
        sweep_risk = liq * 0.3 if abs(strike - spot) < 100 else liq * 0.1

        rows.append(
            HeatmapStrike(
                strike=strike,
                callOi=call_oi,
                putOi=put_oi,
                callLtp=call_ltp,
                putLtp=put_ltp,
                callInstrumentKey=ce.get("instrument_key"),
                putInstrumentKey=pe.get("instrument_key"),
                gammaWall=gamma_wall,
                liquidityScore=round(liq, 1),
                sweepRisk=round(sweep_risk, 1),
            )
        )
    return sorted(rows, key=lambda x: x.strike)
