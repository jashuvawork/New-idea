"""Peak move + sticky tier — faded rips still surface as signals."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import (
    ExplosionEvent,
    _apply_sticky_tier,
    _effective_session_move,
    _session_open,
    _session_peak,
    _tier_sticky,
    scan_chain_explosions,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _chain_row(strike: float, call_ltp: float, volume: int = 80000) -> dict:
    return {
        "strike_price": strike,
        "call_options": {"ltp": call_ltp, "volume": volume},
    }


def setup_function() -> None:
    _session_open.clear()
    _session_peak.clear()
    _tier_sticky.clear()


def test_effective_session_move_uses_peak_after_fade():
    assert _effective_session_move(2.0, 35.0) == 35.0
    assert _effective_session_move(20.0, 22.0) == 20.0


def test_sticky_tier_holds_exploding():
    key = "SENSEX:CALL:77000"
    tier = _apply_sticky_tier(key, "EXPLODING")
    assert tier == "EXPLODING"
    faded = _apply_sticky_tier(key, "WATCH")
    assert faded == "EXPLODING"


@patch("app.config.get_settings")
def test_peak_move_survives_pullback(mock_settings):
    s = mock_settings.return_value
    s.open_premium_explosion_enabled = True
    s.open_premium_min_move_pct = 25.0
    s.min_option_premium_inr = 20.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_scan_range = 1500
    s.explosion_sensex_scan_range = 1500
    s.all_day_explosion_session_move_min_pct = 25.0
    s.explosion_volume_awaken_min = 25000
    s.explosion_volume_awaken_min_velocity_3s = 1.0

    chain = [_chain_row(77000, 100.0)]
    scan_chain_explosions("SENSEX", chain, spot=77000.0, atm=77000.0, expiry_day=True)
    chain2 = [_chain_row(77000, 150.0)]
    events = scan_chain_explosions("SENSEX", chain2, spot=77000.0, atm=77000.0, expiry_day=True)
    rip = [e for e in events if e.strike == 77000 and e.side == Side.CALL]
    assert rip
    assert rip[0].peak_move_pct >= 49

    chain3 = [_chain_row(77000, 95.0)]
    events2 = scan_chain_explosions("SENSEX", chain3, spot=77000.0, atm=77000.0, expiry_day=True)
    faded = [e for e in events2 if e.strike == 77000 and e.side == Side.CALL]
    assert faded
    assert faded[0].peak_move_pct >= 49
    assert faded[0].daily_move_pct >= 20


def test_forward_signals_includes_volume_awaken_watch():
    from app.engines.forward_signals_engine import build_forward_signals, _explosion_radar_visible
    from app.models.schemas import AutoTraderState, Breadth, MarketPhase, Regime, SymbolSnapshot

    assert _explosion_radar_visible({
        "tier": "WATCH",
        "volumeAwaken": True,
        "velocity3s": 1.0,
    })
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=datetime.now(IST).strftime("%Y-%m-%d"),
        regime=Regime.CHOP,
        tradeQualityScore=40.0,
        breadth=Breadth(bias="BULLISH", score=60, aligned=True),
        explosionAlerts=[
            {
                "side": "CALL",
                "strike": 77000.0,
                "premium": 120.0,
                "explosionScore": 42.0,
                "tier": "WATCH",
                "dailyMovePct": 8.0,
                "peakMovePct": 28.0,
                "velocity3s": 3.2,
                "tradeable": False,
                "volumeAwaken": True,
                "reason": "volAwaken×80k",
            },
        ],
    )
    report = build_forward_signals({"SENSEX": snap}, AutoTraderState())
    explosions = [s for s in report.get("signals") or [] if s.get("horizon") == "EXPLOSION"]
    assert len(explosions) == 1
    assert explosions[0].get("peakMovePct") == 28.0
