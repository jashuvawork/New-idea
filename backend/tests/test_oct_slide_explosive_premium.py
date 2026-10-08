"""Frozen Oct slide day — ELITE ITM premium above ₹350 still builds candidates."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.premium_filter import explosion_alert_premium_tradeable
from app.engines.put_slide_ce_mirror import put_slide_near_miss_waive
from app.engines.rally_capture import explosion_near_miss_waive
from app.models.schemas import AutoTraderState, MarketPhase, SymbolSnapshot
from tests.mock_defaults import settings_mock


def _frozen_settings(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=True,
        aggressive_min_explosion_score=45.0,
        oct_paper_slide_explosion_max_premium_inr=650.0,
        **kwargs,
    )


IST = ZoneInfo("Asia/Kolkata")


def _sensex_snap(spot: float = 71600.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=71600.0,
        sessionHigh=72800.0,
        sessionLow=71500.0,
    )


@patch("app.engines.premium_filter.oct_paper_slide_explosion_context_armed", return_value=True)
@patch("app.engines.premium_filter.get_settings")
def test_elite_put_high_premium_tradeable_on_slide(mock_settings, _ctx):
    mock_settings.return_value = _frozen_settings()
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 71700.0,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "peakMovePct": 45.0,
        "premium": 420.0,
    }
    snap = _sensex_snap()
    assert explosion_alert_premium_tradeable(
        420.0,
        peak_move_pct=45.0,
        snap=snap,
        alert=alert,
        state=AutoTraderState(),
        settings=mock_settings.return_value,
    )


@patch("app.engines.premium_filter.get_settings")
def test_elite_put_premium_still_blocks_deep_otm_without_context(mock_settings):
    mock_settings.return_value = _frozen_settings()
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 73200.0,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "peakMovePct": 45.0,
        "premium": 420.0,
    }
    snap = _sensex_snap(spot=71600.0)
    assert not explosion_alert_premium_tradeable(
        420.0,
        peak_move_pct=45.0,
        snap=snap,
        alert=alert,
        state=AutoTraderState(),
        settings=mock_settings.return_value,
    )


@patch("app.engines.put_slide_ce_mirror.put_pe_base_context_armed", return_value=(True, "slide", {}))
@patch("app.engines.put_slide_ce_mirror.get_settings")
def test_put_slide_near_miss_waives_premium_oob(mock_settings, _armed):
    mock_settings.return_value = _frozen_settings()
    alert = {"side": "PUT", "tier": "ELITE", "explosionScore": 100.0, "symbol": "SENSEX"}
    snap = _sensex_snap()
    assert put_slide_near_miss_waive(
        alert,
        snap=snap,
        state=AutoTraderState(),
        readiness_reason="premium_out_of_band",
    )


@patch("app.config.get_settings")
def test_explosion_near_miss_waives_premium_oob_string(mock_settings):
    mock_settings.return_value = _frozen_settings()
    alert = {"tier": "ELITE", "explosionScore": 100.0, "side": "PUT", "symbol": "SENSEX"}
    assert explosion_near_miss_waive(
        alert,
        readiness_reason="premium_out_of_band",
        settings=_frozen_settings(),
    )
