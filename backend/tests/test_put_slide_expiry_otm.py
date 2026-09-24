"""Sep 9 symmetric — SENSEX expiry OTM PUT slide unlock waives preorder block."""

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.models.schemas import MarketPhase, Side, SymbolSnapshot
from app.engines.best_trade_policy import expiry_cheap_otm_entry_blocked
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _sensex_expiry_snap(*, spot: float = 74070.0) -> SymbolSnapshot:
    from datetime import datetime

    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=74000.0,
        tradeQualityScore=50.0,
        optionExpiry="2026-09-24",
    )


def test_symmetric_shallow_otm_put_waive_helper():
    s = settings_mock()
    alert = {
        "tier": "ELITE",
        "ictArmedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 8.0,
        "shallowOtmLocalBaseTradeable": True,
    }
    assert _symmetric_expiry_otm_put_waive(alert, settings=s) is True


def _put_candidate(*, strike: float = 73900.0, premium: float = 85.0):
    alert = {
        "premium": premium,
        "tier": "ELITE",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 8.0,
        "ictArmedBaseLaunch": True,
        "shallowOtmLocalBaseTradeable": True,
        "timingAssessment": "GOOD",
    }
    return MagicMock(
        mode="explosion",
        symbol="SENSEX",
        side=Side.PUT,
        strike=strike,
        premium=premium,
        alert=alert,
    )


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-24")
def test_sensex_expiry_otm_put_blocked_without_slide_unlock(_mock_today):
    s = settings_mock()
    s.put_slide_unlock_waive_expiry_otm = False
    snap = _sensex_expiry_snap()
    cand = _put_candidate()
    cand.alert = {"premium": 85.0, "tier": "WATCH"}
    blocked, reason = expiry_cheap_otm_entry_blocked(
        cand, snap, cand.alert, state=MagicMock(), settings=s,
    )
    assert blocked is True
    assert reason == "best_trade_block_expiry_otm_itm_atm_only"


@patch("app.engines.put_slide_ce_mirror.put_slide_entry_unlock_expiry_otm_bypass", return_value=True)
@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-24")
def test_sensex_expiry_otm_put_waived_when_slide_unlock(_mock_today, _mock_bypass):
    s = settings_mock()
    snap = _sensex_expiry_snap()
    cand = _put_candidate()
    blocked, reason = expiry_cheap_otm_entry_blocked(
        cand, snap, cand.alert, state=MagicMock(), settings=s,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-24")
def test_sensex_expiry_itm_put_not_blocked(_mock_today):
    s = settings_mock()
    snap = _sensex_expiry_snap(spot=74070.0)
    cand = _put_candidate(strike=74100.0, premium=120.0)
    blocked, reason = expiry_cheap_otm_entry_blocked(
        cand, snap, cand.alert, state=MagicMock(), settings=s,
    )
    assert blocked is False
