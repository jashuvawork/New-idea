"""Explosion entry guards — OTM cap, peak-chase, MACD alignment."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent, resolve_explosion_scan_range
from app.engines.explosion_entry_guards import (
    check_all_in_moneyness_cap,
    check_explosion_macd_alignment,
    check_peak_chase_entry,
)
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings() -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.explosion_worst_day_scan_range = 500
    s.explosion_sensex_worst_day_scan_range = 500
    s.extreme_all_in_max_otm_steps = 3
    s.explosion_peak_chase_guard_enabled = True
    s.explosion_peak_chase_min_premium_mom_pct = 15.0
    s.explosion_peak_chase_max_otm_steps = 3
    s.explosion_peak_chase_min_session_move_pct = 40.0
    s.explosion_macd_alignment_required = True
    return s


def _snap(spot: float = 77350.0, macd: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=spot,
        atmStrike=77400.0,
        spotChart=SpotChart(direction="BULLISH", macdBias=macd, rsi=58.0),
    )


def test_all_in_blocks_deep_otm():
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        ok, reason, meta = check_all_in_moneyness_cap(Side.CALL, 78300.0, _snap())
        assert not ok
        assert "all_in_otm_too_deep" in reason
        assert meta["strikeStepsFromAtm"] == 9


def test_all_in_allows_atm_near():
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        ok, reason, _ = check_all_in_moneyness_cap(Side.CALL, 77500.0, _snap())
        assert ok
        assert reason == "ok"


def test_macd_blocks_call_when_bearish():
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        ok, reason = check_explosion_macd_alignment(Side.CALL, _snap(macd="BEARISH"))
        assert not ok
        assert reason == "explosion_macd_bearish_blocks_call"


def test_peak_chase_blocks_deep_otm_rip():
    with patch("app.engines.explosion_entry_guards.get_settings", return_value=_settings()):
        cand = MagicMock(mode="explosion", side=Side.CALL, strike=78300.0)
        event = ExplosionEvent(
            symbol="SENSEX",
            side=Side.CALL,
            strike=78300.0,
            premium=73.0,
            velocity_3s=18.0,
            velocity_9s=20.0,
            velocity_15s=15.0,
            volume_surge=2.0,
            explosion_score=95.0,
            tier="ELITE",
            reason="rip",
            daily_move_pct=120.0,
            peak_move_pct=130.0,
        )
        ok, reason = check_peak_chase_entry(cand, event, _snap())
        assert not ok
        assert "peak_chase" in reason


def test_tight_scan_on_expiry_session():
    s = _settings()
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=True,
    ):
        assert resolve_explosion_scan_range("SENSEX", s, tight_scan=None) == 500
        assert resolve_explosion_scan_range("NIFTY", s, tight_scan=None) == 500


def test_normal_sensex_scan_range_when_not_expiry():
    s = _settings()
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=False,
    ):
        assert resolve_explosion_scan_range("SENSEX", s) >= 1500
