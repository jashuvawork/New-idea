"""Extreme ALL-IN explosion bypass — capped so late chases cannot reopen gates."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.aligned_side_guard import breadth_hard_blocks_side
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.engines.extreme_explosion_moment import (
    is_extreme_explosion_all_in_bypass,
    snapshots_have_all_in_explosion,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _elite_put_event(daily_move: float = 497.0) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76800.0,
        premium=120.0,
        velocity_3s=8.0,
        velocity_9s=12.0,
        velocity_15s=20.0,
        volume_surge=3.0,
        explosion_score=95.0,
        tier="ELITE",
        reason=f"+{daily_move:.0f}%/session",
        daily_move_pct=daily_move,
    )


def _settings():
    s = MagicMock()
    s.extreme_explosion_all_in_enabled = True
    s.extreme_explosion_elite_move_min_pct = 100.0
    s.extreme_explosion_all_in_move_min_pct = 150.0
    s.extreme_explosion_all_in_min_score = 35.0
    s.extreme_all_in_bypass_max_move_pct = 70.0
    s.high_mover_bypass_max_move_pct = 70.0
    s.breadth_hard_side_block_enabled = True
    s.explosion_reentry_cooldown_seconds = 180
    return s


def _bullish_snap(daily_move: float = 497.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77200.0,
        spotChart=SpotChart(direction="BULLISH", spot=77200.0, momentum5Pct=0.15),
        breadth=Breadth(score=68, bias="BULLISH", aligned=True),
        explosionAlerts=[
            {
                "side": "PUT",
                "strike": 76800.0,
                "tier": "ELITE",
                "explosionScore": 95.0,
                "dailyMovePct": daily_move,
                "tradeable": True,
            },
        ],
    )


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_elite_497pct_no_longer_all_in_bypass(mock_settings):
    """Late mega rips must not bypass — they are PF killers."""
    mock_settings.return_value = _settings()
    event = _elite_put_event()
    assert is_extreme_explosion_all_in_bypass(event=event) is False
    blocked, _ = breadth_hard_blocks_side(Side.PUT, "BULLISH", event=event)
    assert blocked is True


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_normal_put_still_hard_blocked_on_bullish(mock_settings):
    mock_settings.return_value = _settings()
    event = _elite_put_event(daily_move=45.0)
    event.explosion_score = 92.0
    assert is_extreme_explosion_all_in_bypass(event=event) is False
    blocked, _ = breadth_hard_blocks_side(Side.PUT, "BULLISH", event=event)
    assert blocked is True


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_snapshots_reject_late_all_in_explosion(mock_settings):
    mock_settings.return_value = _settings()
    snap = _bullish_snap(497.0)
    assert snapshots_have_all_in_explosion({"SENSEX": snap}) is False


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.extreme_explosion_moment.get_settings")
def test_explosion_entry_rejects_late_extreme_put(mock_extreme, mock_ep):
    s = _settings()
    mock_extreme.return_value = s
    mock_ep.return_value = s

    snap = _bullish_snap()
    event = _elite_put_event()
    trade = SuggestedTrade(
        id="t1", symbol="SENSEX", side=Side.PUT, strike=76800.0,
        lastPremium=120.0, tqs=55, strategyType=StrategyType.EXPLOSIVE, confidence=95,
    )
    ok, reason = check_explosion_entry(event, trade, snap.breadth, False, snap=snap)
    assert ok is False
    assert "extreme_all_in" not in reason
