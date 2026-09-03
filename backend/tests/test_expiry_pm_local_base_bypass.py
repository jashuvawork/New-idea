"""Expiry PM ITM window — local-base explosion bypass (Aug25 NIFTY CALL 24200)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.expiry_day_guards import (
    candidate_is_expiry_pm_local_base_explosion_bypass,
    check_expiry_candidate,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _cfg():
    from unittest.mock import MagicMock

    cfg = MagicMock()
    cfg.expiry_day_guards_enabled = True
    cfg.expiry_morning_end_hour = 12
    cfg.expiry_morning_end_minute = 0
    cfg.expiry_pm_itm_local_base_explosion_bypass_enabled = True
    cfg.expiry_pm_itm_local_base_min_explosion_score = 75.0
    cfg.expiry_pm_itm_local_base_min_move_pct = 2.0
    cfg.expiry_pm_itm_local_base_max_move_pct = 25.0
    cfg.expiry_worst_day_elite_top_bypass_enabled = True
    cfg.expiry_min_rank_score = 62.0
    cfg.expiry_worst_day_min_rank_score = 72.0
    cfg.explosion_max_premium_inr = 800.0
    cfg.min_option_premium_inr = 18.0
    cfg.max_option_premium_inr = 800.0
    cfg.explosion_min_premium_inr = 18.0
    return cfg


def _nifty_expiry_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-08-25",
        spot=24200.0,
        atmStrike=24200.0,
        tradeQualityScore=54.0,
        breadth=Breadth(bias="BEARISH", score=40.0, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.08,
            trendStrength=40.0,
            dataAvailable=True,
        ),
        explosionAlerts=[
            {
                "side": "CALL",
                "strike": 24200.0,
                "tier": "ELITE",
                "explosionScore": 100.0,
                "premium": 43.15,
                "dailyMovePct": 16.46,
                "peakMovePct": 23.35,
                "localBaseMovePct": 16.5,
                "ictFirstLift": True,
                "ictVRipReady": True,
                "ictFlatThenVertical": True,
                "ictBreakout": True,
                "volumeAwaken": True,
                "tradeable": True,
            }
        ],
    )


@dataclass
class _EliteCandidate:
    symbol: str = "NIFTY"
    side: Side = Side.CALL
    strike: float = 24200.0
    premium: float = 43.15
    score: float = 120.0
    mode: str = "explosion"
    tier: str = "ELITE"
    confidence: float = 100.0
    snap: SymbolSnapshot | None = None
    alert: dict | None = None
    explosion_event: object | None = None
    tqs: float = 54.0


def _aug25_call_24200_candidate(**overrides) -> _EliteCandidate:
    snap = _nifty_expiry_snap()
    alert = dict(snap.explosionAlerts[0])
    event = SimpleNamespace(
        daily_move_pct=16.46,
        peak_move_pct=23.35,
        explosion_score=100.0,
        tier="ELITE",
        side=Side.CALL,
        local_base_move_pct=16.5,
    )
    cand = _EliteCandidate(snap=snap, alert=alert, explosion_event=event)
    for key, value in overrides.items():
        setattr(cand, key, value)
    return cand


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_candidate_is_expiry_pm_local_base_bypass(mock_prem, mock_exp):
    cfg = _cfg()
    mock_exp.return_value = cfg
    mock_prem.return_value = cfg

    cand = _aug25_call_24200_candidate()
    with patch("app.engines.expiry_day_guards.is_near_expiry_day", return_value=True):
        assert candidate_is_expiry_pm_local_base_explosion_bypass(cand, cand.snap) is True


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_late_chase_not_bypassed(mock_prem, mock_exp):
    cfg = _cfg()
    mock_exp.return_value = cfg
    mock_prem.return_value = cfg

    cand = _aug25_call_24200_candidate()
    cand.alert["localBaseMovePct"] = 3.0
    cand.alert["dailyMovePct"] = 40.0
    cand.alert["peakMovePct"] = 45.0
    with patch("app.engines.expiry_day_guards.is_near_expiry_day", return_value=True):
        assert candidate_is_expiry_pm_local_base_explosion_bypass(cand, cand.snap) is False


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_check_expiry_candidate_pm_itm_allows_elite_local_base(mock_prem, mock_exp):
    cfg = _cfg()
    mock_exp.return_value = cfg
    mock_prem.return_value = cfg

    snap = _nifty_expiry_snap()
    cand = _aug25_call_24200_candidate(snap=snap)
    scalp = _EliteCandidate(
        symbol="SENSEX",
        mode="explosion",
        tier="BUILDING",
        score=60.0,
        snap=snap,
        alert={},
    )

    with patch("app.engines.expiry_day_guards.expiry_pm_itm_quick_active", return_value=True):
        with patch("app.engines.expiry_day_guards.is_near_expiry_day", return_value=True):
            with patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True):
                with patch(
                    "app.engines.expiry_day_guards.predict_worst_expiry_day",
                    return_value=(True, 50.0, ["early_expiry_chop_bearish"]),
                ):
                    with patch("app.engines.expiry_day_guards._session_declining", return_value=False):
                        with patch(
                            "app.engines.expiry_day_guards.check_expiry_explosion_open_block",
                            return_value=(False, "ok"),
                        ):
                            with patch(
                                "app.engines.aligned_explosion_bypass.expiry_aligned_explosion_trade_allowed",
                                return_value=(False, "no"),
                            ):
                                ok, reason, meta = check_expiry_candidate(
                                    cand, AutoTraderState(), {"NIFTY": snap},
                                )
                                ok_s, reason_s, _ = check_expiry_candidate(
                                    scalp, AutoTraderState(), {"NIFTY": snap},
                                )
    assert ok is True
    assert reason == "ok"
    assert meta.get("expiryPmItmLocalBaseBypass") is True
    assert ok_s is False
    assert reason_s == "expiry_pm_itm_quick_only"
