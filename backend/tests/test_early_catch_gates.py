"""Early catch gates — lower floors for pad/first-lift before chase."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.early_catch_gates import early_catch_pretrade_min_rank
from app.engines.trade_ranking import ftv_authorization_policy
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.grade_a_ftv_first_lift_enabled = True
    s.grade_a_ftv_first_lift_min_rank = 40.0
    s.early_catch_pad_min_rank = 35.0
    s.first_lift_early_pad_min_rank = 38.0
    s.grade_a_ftv_first_lift_min_explosion_score = 20.0
    s.grade_a_ftv_first_lift_min_quality = 55.0
    s.grade_a_ftv_first_lift_min_base_move_pct = 8.0
    s.grade_a_ftv_first_lift_max_base_move_pct = 45.0
    s.bullish_local_base_pad_min_explosion_score = 8.0
    s.bullish_local_base_pad_max_move_pct = 45.0
    s.bullish_local_base_pad_max_capital_pct = 0.90
    s.first_lift_trade_enabled = True
    s.first_lift_trade_min_score = 35.0
    s.first_lift_trade_min_quality = 55.0
    s.first_lift_trade_max_move_pct = 40.0
    s.first_lift_pad_explosion_bypass_enabled = True
    s.first_lift_pad_explosion_min_score = 8.0
    s.first_lift_pad_local_base_min_pct = 2.0
    s.first_lift_pad_local_base_max_pct = 25.0
    s.first_lift_pad_explosion_min_peak_pct = 25.0
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _evidence(**overrides):
    base = {
        "mode": "explosion",
        "tier": "ELITE",
        "explosionScore": 33.0,
        "flatVerticalQuality": 60.0,
        "localBaseMovePct": 21.0,
        "firstLift": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "bullishLocalBaseActive": True,
        "volumeAwaken": True,
        "flatVerticalGrade": "A+",
        "symbol": "SENSEX",
        "velocity3s": 0.0,
        "velocity9s": 0.2,
    }
    base.update(overrides)
    return base


@patch("app.engines.grade_a_ftv_capture.get_settings")
@patch("app.engines.early_catch_gates.get_settings")
def test_early_catch_lowers_pretrade_rank_for_bullish_pad(mock_ec, mock_ga):
    mock_ec.return_value = _settings()
    mock_ga.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77350.0,
        breadth=Breadth(bias="BEARISH"),
        spotChart=SpotChart(candles=[]),
        explosionAlerts=[_evidence()],
    )
    candidate = SimpleNamespace(
        symbol="SENSEX",
        mode="explosion",
        side=Side.PUT,
        strike=77300.0,
        score=33.0,
        snap=snap,
        alert=_evidence(),
        explosion_event=SimpleNamespace(velocity_3s=0.0),
    )
    assert early_catch_pretrade_min_rank(candidate) == 35.0


@patch("app.config.get_settings")
def test_ftv_auth_bullish_local_base_pad_sleeve(mock_settings):
    mock_settings.return_value = _settings()
    ranking = {"grade": "A", "score": 33.0}
    decision = ftv_authorization_policy(
        _evidence(),
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        require_allocation_rank_one=False,
    )
    assert decision.allowed is True
    assert decision.mode in ("BULLISH_LOCAL_BASE_PAD", "GRADE_A_FTV_FIRST_LIFT")


@patch("app.config.get_settings")
def test_ftv_auth_first_lift_pad_sleeve(mock_settings):
    mock_settings.return_value = _settings()
    ranking = {"grade": "A", "score": 36.0}
    decision = ftv_authorization_policy(
        _evidence(
            bullishLocalBaseActive=False,
            flatVerticalGrade="B",
            peakMovePct=30.0,
            volumeAwaken=True,
        ),
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        require_allocation_rank_one=False,
        first_lift_trade_min_score=35.0,
    )
    assert decision.allowed is True
    assert decision.mode in ("FIRST_LIFT_PAD", "FIRST_LIFT_LOCAL_BASE")
