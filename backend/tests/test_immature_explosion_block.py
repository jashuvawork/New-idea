"""Block Jul20-style displacement noise at +0.8%/+1.4% session move."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import immature_explosion_blocked
from app.engines.ict_breakout_monitor import ICTBreakoutSignal, analyze_ict_breakout
from app.engines.winner_entry_guards import chop_weak_explosion_blocks_entry
from app.models.schemas import MarketPhase, Regime, Side, SymbolSnapshot
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.explosion_immature_block_enabled = True
    s.explosion_immature_min_session_move_pct = 22.0
    s.explosion_chop_min_session_move_pct = 28.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_displacement_min_velocity_3s = 2.2
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 12.0
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_vertical_min_session_move_pct = 80.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_volume_surge_awaken_min = 3.0
    s.ict_mega_rip_min_session_move_pct = 200.0
    s.ict_breakout_min_score = 28.0
    s.ict_fvg_score_bonus = 14.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 22.0
    s.explosion_volume_awaken_min = 25000
    s.all_day_explosion_session_move_min_pct = 40.0
    s.aggressive_min_explosion_score = 45.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(daily: float, *, v3: float = 3.5, tier: str = "EXPLODING") -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200.0,
        premium=80.0,
        velocity_3s=v3,
        velocity_9s=v3,
        velocity_15s=v3,
        volume_surge=1.2,
        explosion_score=55.0,
        tier=tier,
        reason="displacement",
        daily_move_pct=daily,
        peak_move_pct=daily,
    )


@patch("app.engines.explosion_entry_guards.get_settings")
def test_blocks_jul20_08pct_displacement(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = immature_explosion_blocked(_event(0.77))
    assert blocked is True
    assert "immature_explosion" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_allows_real_rip_at_30pct(mock_settings):
    mock_settings.return_value = _settings()
    blocked, _ = immature_explosion_blocked(_event(30.0))
    assert blocked is False


@patch("app.engines.winner_entry_guards.get_settings")
def test_chop_blocks_high_rank_tiny_move(mock_settings):
    """Rank score must NOT bypass chop immature guard (Jul20 root cause)."""
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.CHOP,
        tradeQualityScore=60,
    )
    cand = MagicMock()
    cand.mode = "explosion"
    cand.score = 120.0  # inflated rank — previously bypassed
    cand.tier = "EXPLODING"
    cand.explosion_event = _event(1.4)
    cand.alert = {"ictPattern": "displacement", "ictDisplacement": True}
    blocked, reason = chop_weak_explosion_blocks_entry(cand, snap)
    assert blocked is True
    assert "chop_immature" in reason or "chop_weak" in reason


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_displacement_alone_not_active_on_tiny_move(mock_settings):
    mock_settings.return_value = _settings()
    ict = analyze_ict_breakout(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200,
        premium=80.0,
        session_move_pct=1.4,
        peak_move_pct=1.4,
        velocity_3s=3.5,
        volume_surge=1.1,
        volume=5000,
        tier="EXPLODING",
    )
    assert ict.displacement is True
    assert ict.active is False
    assert ict.pattern == "displacement"
