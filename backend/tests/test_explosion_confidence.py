"""High-confidence explosion filter — missed-trade keep list alignment."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_confidence import (
    high_confidence_explosion,
    missed_explosion_rank_bonus,
)
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.missed_explosion_promote_enabled = True
    s.missed_explosion_promote_min_score = 70.0
    s.missed_explosion_promote_min_move_pct = 28.0
    s.missed_explosion_promote_max_move_pct = 55.0
    s.missed_explosion_promote_rank_bonus = 22.0
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 250.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_cheap_rip_min_premium_inr = 8.0
    s.explosion_cheap_rip_min_peak_pct = 25.0
    s.nifty_strike_step = 50
    s.sensex_strike_step = 100
    s.chart_alignment_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, direction: str = "BULLISH", breadth: str = "BULLISH", spot: float = 24250.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.RANGE_BOUND,
        spot=spot,
        atmStrike=24250.0,
        tradeQualityScore=62,
        breadth=Breadth(score=70, bias=breadth, aligned=True),
        spotChart=SpotChart(
            direction=direction,
            timeframe="5m",
            barCount=40,
            momentum5Pct=0.2,
            momentum15Pct=0.35,
            trendStrength=72.0,
            emaBias="BULLISH",
            candleBias="BULLISH",
            orPosition="ABOVE",
            rsi=61.0,
            macdBias="BULLISH",
        ),
    )


def _event(
    *,
    strike: float = 24250.0,
    premium: float = 95.0,
    daily: float = 35.0,
    tier: str = "ELITE",
    score: float = 88.0,
) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=strike,
        premium=premium,
        velocity_3s=8.0,
        velocity_9s=10.0,
        velocity_15s=9.0,
        volume_surge=2.8,
        explosion_score=score,
        tier=tier,
        reason="flat_then_vertical",
        daily_move_pct=daily,
        peak_move_pct=daily,
    )


@patch("app.engines.explosion_confidence.get_settings")
@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_accepts_jul15_style_atm_elite(mock_m, mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    mock_m.return_value = cfg
    snap = _snap()
    event = _event()
    alert = {
        "tier": "ELITE",
        "explosionScore": 88,
        "dailyMovePct": 35,
        "peakMovePct": 35,
        "ictFlatThenVertical": True,
        "ictDisplacement": True,
        "volumeAwaken": True,
    }
    ok, reason, meta = high_confidence_explosion(
        side=Side.CALL,
        strike=24250,
        premium=95,
        snap=snap,
        alert=alert,
        explosion_event=event,
        tier="ELITE",
        score=88,
    )
    assert ok is True
    assert reason == "high_confidence_base_rip"
    assert meta["highConfidenceExplosion"] is True


@patch("app.engines.explosion_confidence.get_settings")
@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_rejects_cheap_deep_otm_missed_radar(mock_m, mock_p, mock_s):
    """Jul20-style ₹3–6 deep OTM radar rows stay blocked (premium_out_of_band)."""
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    mock_m.return_value = cfg
    snap = _snap(spot=24250)
    ok, reason, _ = high_confidence_explosion(
        side=Side.CALL,
        strike=24550,  # deep OTM
        premium=4.5,
        snap=snap,
        alert={
            "tier": "ELITE",
            "explosionScore": 92,
            "dailyMovePct": 40,
            "peakMovePct": 48,
        },
        tier="ELITE",
        score=92,
    )
    assert ok is False
    assert reason == "premium_out_of_band"


@patch("app.engines.explosion_confidence.get_settings")
@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_rejects_immature_and_extended(mock_m, mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    mock_m.return_value = cfg
    snap = _snap()
    ok_early, reason_early, _ = high_confidence_explosion(
        side=Side.CALL,
        strike=24250,
        premium=80,
        snap=snap,
        alert={"tier": "ELITE", "explosionScore": 80, "dailyMovePct": 18, "peakMovePct": 18},
        tier="ELITE",
        score=80,
    )
    assert ok_early is False
    assert "immature" in reason_early

    ok_late, reason_late, _ = high_confidence_explosion(
        side=Side.CALL,
        strike=24250,
        premium=120,
        snap=snap,
        alert={"tier": "ELITE", "explosionScore": 90, "dailyMovePct": 72, "peakMovePct": 80},
        tier="ELITE",
        score=90,
    )
    assert ok_late is False
    assert "extended" in reason_late


@patch("app.engines.explosion_confidence.get_settings")
@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_rank_bonus_promotes_high_confidence_call(mock_m, mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    mock_m.return_value = cfg
    snap = _snap()
    event = _event()
    cand = SimpleNamespace(
        mode="explosion",
        side=Side.CALL,
        strike=24250.0,
        premium=95.0,
        confidence=88.0,
        score=140.0,  # rank composite — must NOT be used as explosion score alone
        tier="ELITE",
        alert={
            "tier": "ELITE",
            "explosionScore": 88,
            "dailyMovePct": 35,
            "peakMovePct": 35,
            "ictFlatThenVertical": True,
        },
        explosion_event=event,
        pretrade_meta=None,
    )
    bonus = missed_explosion_rank_bonus(cand, snap)
    assert bonus >= 22.0
    assert cand.pretrade_meta and cand.pretrade_meta.get("missedExplosionPromote") is True


@patch("app.engines.explosion_confidence.get_settings")
def test_rank_bonus_zero_for_scalp(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    cand = SimpleNamespace(mode="scalp", side=Side.CALL, strike=24250, premium=40, confidence=50)
    assert missed_explosion_rank_bonus(cand, snap) == 0.0
