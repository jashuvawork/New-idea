"""Open-gap ITM CE/PE — prev-close baseline + chop/MTF/pre-expiry capture."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import (
    ExplosionEvent,
    _session_low,
    _session_open,
    _session_peak,
    apply_prior_close_baseline,
    prior_close_from_option_leg,
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.engines.mtf_chart_analysis import validate_mtf_scalp
from app.engines.open_gap_capture import (
    elite_open_gap_mtf_bypass,
    open_gap_chop_bypass,
    open_gap_near_expiry_symbol_allow,
)
from app.engines.winner_entry_guards import chop_weak_explosion_blocks_entry
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SymbolSnapshot,
)
from app.services.upstox import normalize_option_leg

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.open_gap_prev_close_baseline_enabled = True
    s.open_gap_baseline_min_gap_pct = 15.0
    s.open_gap_elite_mtf_bypass_enabled = True
    s.open_gap_elite_mtf_min_move_pct = 40.0
    s.open_gap_chop_elite_bypass_enabled = True
    s.open_gap_near_expiry_symbol_allow_enabled = True
    s.open_premium_min_move_pct = 25.0
    s.open_premium_explosion_enabled = True
    s.all_day_explosion_session_move_min_pct = 40.0
    s.explosion_chop_min_session_move_pct = 28.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.aggressive_min_explosion_score = 45.0
    s.explosion_elite_never_block_enabled = True
    s.pre_expiry_expiry_symbol_explosion_min_rank = 45.0
    s.min_option_premium_inr = 20.0
    s.explosion_max_premium_inr = 400.0
    s.max_option_premium_inr = 300.0
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.explosion_worst_day_scan_range = 500
    s.explosion_sensex_worst_day_scan_range = 500
    s.expiry_itm_monitor_enabled = True
    s.expiry_itm_scan_range = 800
    s.expiry_sensex_itm_scan_range = 1200
    s.expiry_atm_tier_velocity_mult = 1.0
    s.explosion_atm_proximity_bonus_max = 8.0
    s.explosion_otm_depth_penalty_per_step = 3.0
    s.peak_move_explosion_min_pct = 35.0
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_score_sticky_enabled = False
    s.velocity_peak_score_boost_enabled = False
    s.session_open_use_intraday_low = True
    s.session_open_low_backfill_pct = 5.0
    s.volume_spike_baseline_enabled = True
    s.volume_spike_baseline_min_surge = 3.5
    s.spike_velocity_baseline_min_pct = 12.0
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.execution_mtf_enabled = True
    s.execution_chart_premium_check_enabled = False
    s.chart_override_min_score = 75.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _elite_event(move: float = 192.0, tier: str = "ELITE") -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77500.0,
        premium=270.0,
        velocity_3s=5.0,
        velocity_9s=8.0,
        velocity_15s=10.0,
        volume_surge=3.0,
        explosion_score=90.0,
        tier=tier,
        reason="open-gap",
        daily_move_pct=move,
        peak_move_pct=move,
    )


def test_normalize_option_leg_keeps_prev_close():
    leg = normalize_option_leg({
        "instrument_key": "BSE_FO|x",
        "market_data": {"ltp": 270.0, "close": 92.45, "open": 95.0, "volume": 1000, "oi": 500},
        "option_greeks": {"delta": 0.5},
    })
    assert float(leg["prev_close"]) == 92.45
    assert float(leg["close"]) == 92.45
    assert prior_close_from_option_leg(leg) == 92.45


def test_apply_prior_close_baseline_seeds_open_gap():
    reset_detector_state_for_tests()
    with patch("app.config.get_settings", return_value=_settings()):
        key = "SENSEX:CALL:77500.0"
        # Simulate mid-spike first tick then prior-close arrives
        _session_open[key] = 250.0
        _session_peak[key] = 270.0
        _session_low[key] = 250.0
        changed = apply_prior_close_baseline(key, 270.0, 92.45)
        assert changed is True
        assert _session_open[key] == 92.45
        move = ((270.0 - 92.45) / 92.45) * 100
        assert move >= 190


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
@patch("app.config.get_settings")
def test_scan_detects_elite_from_prev_close_on_first_poll(mock_settings, _open):
    """Jul29 pattern: first LTP already mid-gap, prev_close seeds ELITE immediately."""
    reset_detector_state_for_tests()
    mock_settings.return_value = _settings()
    chain = [{
        "strike_price": 77500,
        "call_options": {
            "ltp": 270.0,
            "prev_close": 92.45,
            "close": 92.45,
            "volume": 2_000_000,
        },
    }]
    events = scan_chain_explosions("SENSEX", chain, spot=77500.0, atm=77600.0)
    ce = [e for e in events if e.side == Side.CALL and e.strike == 77500]
    assert ce, "77500 CE open-gap must appear on radar"
    assert ce[0].daily_move_pct >= 150
    assert ce[0].tier == "ELITE"


@patch("app.engines.winner_entry_guards.get_settings")
@patch("app.engines.open_gap_capture.get_settings")
def test_chop_allows_elite_open_gap(mock_og, mock_wg):
    s = _settings()
    mock_og.return_value = s
    mock_wg.return_value = s
    snap = MagicMock()
    snap.regime = Regime.RANGE_BOUND
    snap.spotChart = None
    candidate = SimpleNamespace(
        mode="explosion",
        score=90.0,
        tier="ELITE",
        explosion_event=_elite_event(192.0, "ELITE"),
        alert={},
    )
    assert open_gap_chop_bypass(candidate, snap) is True
    blocked, reason = chop_weak_explosion_blocks_entry(candidate, snap)
    assert not blocked, reason


@patch("app.engines.open_gap_capture.get_settings")
def test_mtf_bypass_for_breadth_aligned_elite(mock_settings):
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24200.0,
        atmStrike=24200.0,
        regime=Regime.TREND_EXPANSION,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
    )
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200.0,
        premium=153.0,
        velocity_3s=4.0,
        velocity_9s=6.0,
        velocity_15s=8.0,
        volume_surge=2.0,
        explosion_score=85.0,
        tier="ELITE",
        reason="open-gap",
        daily_move_pct=98.0,
        peak_move_pct=98.0,
    )
    assert elite_open_gap_mtf_bypass(
        Side.CALL, snap, explosion_event=event, mode="explosion",
    )

    # Stale 5m bearish must not block when open-gap bypass is wired as premium_led.
    from app.models.schemas import TimeframeChartRead

    index_mtf = {
        "5m": TimeframeChartRead(
            label="5m", direction="BEARISH", momentumPct=-0.1, trendStrength=40,
        ),
        "1m": TimeframeChartRead(
            label="1m", direction="BULLISH", momentumPct=0.2, trendStrength=50,
        ),
    }
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=_settings()):
        ok, reason, _meta = validate_mtf_scalp(
            Side.CALL, index_mtf, None,
            premium_led_bypass=True,
            scalp_mode=False,
        )
    assert ok, reason


@patch("app.engines.open_gap_capture.get_settings")
@patch("app.engines.expiry_day_guards.get_settings")
def test_near_expiry_symbol_allow(mock_eg, mock_og):
    s = _settings()
    s.expiry_day_guards_enabled = True
    mock_og.return_value = s
    mock_eg.return_value = s
    tomorrow = (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=tomorrow,
        spot=77500.0,
        atmStrike=77600.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=57.0,
        breadth=Breadth(bias="BULLISH", score=81, aligned=True),
    )
    candidate = SimpleNamespace(
        mode="explosion",
        side=Side.CALL,
        score=90.0,
        tier="ELITE",
        explosion_event=_elite_event(),
    )
    assert open_gap_near_expiry_symbol_allow(candidate, snap) is True
