"""Fake explosion trap — Jul20 NIFTY 24300 CE FOMO / never-green path."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import (
    cap_fake_explosion_trap_lots,
    detect_fake_explosion_trap,
)
from app.engines.pretrade_validator import TradeRecord
from app.models.schemas import MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.explosion_early_window_max_move_pct = 55.0
    s.fake_explosion_trap_max_premium_mom_pct = 0.15
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.fake_explosion_trap_post_win_lot_cap = 8
    s.fake_explosion_trap_post_win_max_pnl_inr = 3000.0
    s.fake_explosion_trap_post_win_lookback = 1
    s.fake_explosion_trap_psychology_escalate = True
    s.moneyness_explosion_prefer = "ATM"
    s.trade_moneyness_mode = "AUTO"
    s.midday_chop_start_hour = 11
    s.midday_chop_start_minute = 30
    s.midday_chop_end_hour = 13
    s.midday_chop_end_minute = 30
    s.nifty_strike_step = 50
    s.sensex_strike_step = 100
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(
    daily: float = 29.8,
    *,
    v3: float = 13.1,
    tier: str = "ELITE",
    strike: float = 24300.0,
) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=strike,
        premium=58.0,
        velocity_3s=v3,
        velocity_9s=v3,
        velocity_15s=v3,
        volume_surge=2.5,
        explosion_score=100.0,
        tier=tier,
        reason="flat_then_vertical",
        daily_move_pct=daily,
        peak_move_pct=daily,
    )


def _snap(*, regime: Regime = Regime.RANGE_BOUND, or_pos: str = "INSIDE") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=regime,
        spot=24244.75,
        atmStrike=24200.0,
        tradeQualityScore=49,
        spotChart=SpotChart(
            direction="BULLISH",
            timeframe="5m",
            barCount=51,
            momentum5Pct=0.133,
            momentum15Pct=0.266,
            trendStrength=70.6,
            emaBias="NEUTRAL",
            candleBias="NEUTRAL",
            orPosition=or_pos,
            rsi=62.94,
            macdBias="BULLISH",
        ),
    )


def _candidate(event: ExplosionEvent, snap: SymbolSnapshot) -> MagicMock:
    cand = MagicMock()
    cand.mode = "explosion"
    cand.side = event.side
    cand.strike = event.strike
    cand.score = 165.0
    cand.tier = event.tier
    cand.explosion_event = event
    cand.snap = snap
    return cand


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_blocks_jul20_otm_inside_or_chop_elite(mock_money_settings, mock_settings):
    """RANGE + ELITE + OTM inside OR → hard block (Jul20 24300 CE)."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap()
    cand = _candidate(_event(), snap)
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert blocked is True
    assert meta.get("action") == "block"
    assert "otm_inside_or" in meta.get("conflictFlags", [])
    assert "fake_explosion_trap" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_blocks_premium_flat_extension(mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    # ATM strike — avoid OTM path; premium flat + extension should still block.
    snap = _snap(or_pos="ABOVE")
    cand = _candidate(_event(strike=24200.0), snap)
    prem = {"direction": "NEUTRAL", "momentum3Pct": 0.0, "momentum5Pct": 0.0}
    blocked, reason, meta = detect_fake_explosion_trap(
        cand, snap, premium_chart=prem,
    )
    assert blocked is True
    assert "premium_flat" in meta.get("conflictFlags", [])
    assert "premium_flat" in reason or meta.get("action") == "block"


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_small_win_cuts_size(mock_collect, mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    # Trend day + ATM breakout OR — no hard block, but post-win clamps.
    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="ABOVE")
    cand = _candidate(_event(daily=12.0, v3=4.0, tier="EXPLODING", strike=24200.0), snap)

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="SENSEX",
                side="CALL",
                pnl_inr=445.6,
                exit_reason="explosion_trail_sl",
                strike=78300.0,
            )
        ],
    ):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(),
        )
    assert blocked is False
    assert meta.get("action") == "cut_size"
    assert meta.get("lotCap") == 8
    assert meta.get("psychologyEscalate") == "FOMO"
    assert cap_fake_explosion_trap_lots(49, meta) == 8


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_chop_elite_soft_cut_without_otm_trap(mock_money_settings, mock_settings):
    """Chop + ELITE on ATM with OR breakout → cut size, not necessarily block."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="ABOVE")
    cand = _candidate(_event(daily=18.0, strike=24200.0), snap)
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert blocked is False
    assert meta.get("action") == "cut_size"
    assert meta.get("lotCap") == 6
    assert meta.get("psychologyEscalate") in ("OVERCONFIDENCE", "FOMO", None)
    assert cap_fake_explosion_trap_lots(49, meta) == 6


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_clean_trend_atm_not_trapped(mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="ABOVE")
    # Strong chart so _regime_chopish is false even without RANGE
    snap.spotChart.momentum5Pct = 0.6
    snap.spotChart.trendStrength = 80.0
    cand = _candidate(_event(daily=18.0, v3=5.0, tier="EXPLODING", strike=24200.0), snap)
    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert blocked is False
    assert meta.get("action") not in ("block", "cut_size")
    assert cap_fake_explosion_trap_lots(20, meta) == 20


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_jul15_atm_base_window_not_hard_blocked(mock_money_settings, mock_settings):
    """RANGE + ELITE + ATM + 32–45% move = Jul15 keep — soft size cut only, not hard block."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="BELOW")
    cand = _candidate(_event(daily=32.0, v3=7.9, strike=24250.0), snap)
    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert blocked is False
    assert meta.get("action") == "cut_size"
    assert "base_window" in meta.get("conflictFlags", [])
    assert "session_extended" not in meta.get("conflictFlags", [])
    assert cap_fake_explosion_trap_lots(49, meta) == 6


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_extended_chase_still_flags_session_extended(mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="ABOVE")
    cand = _candidate(_event(daily=80.0, strike=24200.0), snap)
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert "session_extended" in meta.get("conflictFlags", [])


def test_cap_block_zeros_lots():
    assert cap_fake_explosion_trap_lots(49, {"fakeExplosionTrap": True, "action": "block"}) == 0
