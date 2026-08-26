"""Expiry-day ITM CE+PE monitor — cover most ITM strikes on both sides."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import resolve_explosion_scan_range
from app.engines.expiry_day_guards import (
    expiry_itm_max_steps,
    expiry_itm_monitor_active,
    resolve_expiry_itm_scan_range,
)
from app.engines.moneyness import heatmap_moneyness_candidates, moneyness_allows
from app.models.schemas import (
    Breadth,
    HeatmapStrike,
    MarketPhase,
    Regime,
    Side,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.moneyness_selection_enabled = True
    s.trade_moneyness_mode = "AUTO"
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.banknifty_strike_step = 100.0
    s.moneyness_max_otm_steps = 2
    s.moneyness_max_itm_steps = 2
    s.expiry_explosion_max_otm_steps = 4
    s.expiry_itm_monitor_enabled = True
    s.expiry_max_itm_steps = 6
    s.expiry_itm_candidate_limit = 12
    s.expiry_itm_scan_range = 800
    s.expiry_sensex_itm_scan_range = 1200
    s.expiry_itm_both_sides = True
    s.expiry_near_expiry_premium_max_inr = 300.0
    s.expiry_pm_itm_premium_max_inr = 280.0
    s.moneyness_explosion_prefer = "ATM"
    s.moneyness_explosion_block_otm = True
    s.moneyness_local_base_otm_bypass_enabled = False
    s.moneyness_scalp_chop_prefer = "ITM"
    s.moneyness_high_conf_prefer = "ITM"
    s.moneyness_rank_bonus = 12.0
    s.moneyness_mismatch_penalty = 15.0
    s.high_confidence_min_score = 72.0
    s.bearish_sideways_explosion_min_score = 78.0
    s.aggressive_min_explosion_score = 70.0
    s.min_option_premium_inr = 25.0
    s.max_option_premium_inr = 175.0
    s.chop_day_guards_enabled = True
    s.whipsaw_guards_enabled = True
    s.expiry_day_guards_enabled = True
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.explosion_worst_day_scan_range = 500
    s.explosion_sensex_worst_day_scan_range = 500
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _expiry_snap(spot: float = 23950.0, bias: str = "BULLISH") -> SymbolSnapshot:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=23950.0,
        optionExpiry=today,
        regime=Regime.TREND_EXPANSION,
        tradeQualityScore=45.0,
        breadth=Breadth(bias=bias, score=55, aligned=bias == "BULLISH"),
        heatmap=[
            HeatmapStrike(strike=23950.0, callLtp=40.0, putLtp=38.0, liquidityScore=90),
            HeatmapStrike(strike=23900.0, callLtp=72.0, putLtp=28.0, liquidityScore=80),
            HeatmapStrike(strike=23850.0, callLtp=110.0, putLtp=22.0, liquidityScore=70),
            HeatmapStrike(strike=23800.0, callLtp=155.0, putLtp=18.0, liquidityScore=65),
            HeatmapStrike(strike=23750.0, callLtp=200.0, putLtp=14.0, liquidityScore=55),
            HeatmapStrike(strike=23700.0, callLtp=245.0, putLtp=12.0, liquidityScore=50),
            HeatmapStrike(strike=24000.0, callLtp=28.0, putLtp=55.0, liquidityScore=85),
            HeatmapStrike(strike=24050.0, callLtp=20.0, putLtp=85.0, liquidityScore=78),
            HeatmapStrike(strike=24100.0, callLtp=14.0, putLtp=120.0, liquidityScore=70),
            HeatmapStrike(strike=24150.0, callLtp=10.0, putLtp=160.0, liquidityScore=60),
            HeatmapStrike(strike=24200.0, callLtp=8.0, putLtp=210.0, liquidityScore=55),
            HeatmapStrike(strike=24250.0, callLtp=6.0, putLtp=255.0, liquidityScore=45),
        ],
    )


@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_itm_monitor_active_on_expiry_day(mock_settings):
    mock_settings.return_value = _settings()
    snap = _expiry_snap()
    assert expiry_itm_monitor_active(snap) is True
    assert expiry_itm_max_steps() == 6


@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_itm_monitor_off_when_disabled(mock_settings):
    mock_settings.return_value = _settings(expiry_itm_monitor_enabled=False)
    snap = _expiry_snap()
    assert expiry_itm_monitor_active(snap) is False


@patch("app.engines.expiry_day_guards.get_settings")
def test_resolve_expiry_itm_scan_range(mock_settings):
    mock_settings.return_value = _settings()
    assert resolve_expiry_itm_scan_range("NIFTY") == 800
    assert resolve_expiry_itm_scan_range("SENSEX") == 1200


def test_expiry_scan_uses_itm_range_not_worst_day_clamp():
    s = _settings()
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=True,
    ):
        assert resolve_explosion_scan_range("NIFTY", s, tight_scan=None) == 800
        assert resolve_explosion_scan_range("SENSEX", s, tight_scan=None) == 1200
        # Per-symbol expiry_day must widen even when session cache is stale/off.
        assert resolve_explosion_scan_range("SENSEX", s, expiry_day=True) == 1200


def test_expiry_scan_falls_back_to_worst_day_when_itm_monitor_off():
    s = _settings(expiry_itm_monitor_enabled=False)
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=True,
    ):
        assert resolve_explosion_scan_range("NIFTY", s, tight_scan=None) == 500
        assert resolve_explosion_scan_range("SENSEX", s, tight_scan=None) == 500


@patch("app.engines.moneyness.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True)
def test_allows_deep_itm_on_expiry(mock_expiry, mock_eg, mock_mn):
    s = _settings()
    mock_eg.return_value = s
    mock_mn.return_value = s
    snap = _expiry_snap()
    # 23700 CE = 5 steps ITM (250/50) — blocked at default max=2, allowed on expiry max=6
    ok, reason, meta = moneyness_allows(
        Side.CALL, 23700, snap, mode="explosion", candidate_score=80,
    )
    assert ok, reason
    assert meta["moneyness"] == "ITM"
    assert meta.get("expiryItmMonitor") is True


@patch("app.engines.moneyness.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True)
def test_still_blocks_too_deep_itm_beyond_expiry_cap(mock_expiry, mock_eg, mock_mn):
    s = _settings(expiry_max_itm_steps=4)
    mock_eg.return_value = s
    mock_mn.return_value = s
    snap = _expiry_snap()
    # 23650 would be 6 steps — build strike 6 steps ITM
    ok, reason, meta = moneyness_allows(
        Side.CALL, 23650, snap, mode="scalp", candidate_score=60,
    )
    assert not ok
    assert "itm_too_deep" in reason


@patch("app.engines.moneyness.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True)
@patch("app.engines.moneyness.is_chop_session", return_value=False)
@patch("app.engines.moneyness.is_bearish_sideways", return_value=False)
def test_heatmap_monitors_both_itm_ce_and_pe_on_expiry(
    mock_bs, mock_chop, mock_expiry, mock_eg, mock_mn,
):
    s = _settings()
    mock_eg.return_value = s
    mock_mn.return_value = s
    # Bullish breadth would previously drop ITM puts — expiry both-sides keeps them.
    snap = _expiry_snap(bias="BULLISH")
    rows = heatmap_moneyness_candidates("NIFTY", snap)
    asserts_ce = [r for r in rows if r["side"] == Side.CALL and r["moneyness"] == "ITM"]
    asserts_pe = [r for r in rows if r["side"] == Side.PUT and r["moneyness"] == "ITM"]
    assert asserts_ce, "expiry must monitor ITM CE"
    assert asserts_pe, "expiry must monitor ITM PE even when breadth is bullish"
    assert any(r["strike"] == 24050 for r in asserts_pe), "24050 PE must be on expiry ITM radar"
    assert all(r.get("expiryItmMonitor") for r in rows)
    assert len(rows) <= 12
