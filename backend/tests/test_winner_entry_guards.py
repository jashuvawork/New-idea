"""Winner entry guards — block fading premium and loss-streak churn."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.winner_entry_guards import (
    chop_weak_explosion_blocks_entry,
    premium_fading_blocks_entry,
    session_winner_gate,
)
from app.models.schemas import AutoTraderState, Regime, Side


def _event(daily_move: float = 10.0, tier: str = "EXPLODING") -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=78000.0,
        premium=200.0,
        velocity_3s=2.0,
        velocity_9s=3.0,
        velocity_15s=4.0,
        volume_surge=1.5,
        explosion_score=62.0,
        tier=tier,
        reason="test",
        daily_move_pct=daily_move,
    )


@patch("app.engines.winner_entry_guards.get_settings")
def test_fading_premium_blocks_even_high_score(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.35
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=100.0,
        premium_momentum_3s=-0.44,
        premium_momentum_5s=-2.35,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=5.0),
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_elite_extreme_move_bypasses_fading_premium(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    mock_settings.return_value = s

    blocked, _ = premium_fading_blocks_entry(
        trade_score=100.0,
        premium_momentum_3s=-0.44,
        premium_momentum_5s=-2.35,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=105.0, tier="ELITE"),
    )
    assert not blocked


@patch("app.engines.winner_entry_guards.get_settings")
def test_confirmed_ftv_fills_through_shallow_dip(mock_settings):
    """Confirmed near-base FTV first-lift takes AT the base through a shallow retest dip."""
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.ftv_premium_fade_fill_enabled = True
    s.ftv_premium_fade_fill_max_drawdown_pct = -0.6
    mock_settings.return_value = s

    # -0.4% dip is shallower than the -0.6% floor: the base retest, not a collapse.
    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-0.30,
        premium_momentum_5s=-0.40,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=20.0, tier="EXPLODING"),
        confirmed_ftv_bypass=True,
    )
    assert not blocked
    assert reason == "ftv_shallow_fade_ok"


@patch("app.engines.winner_entry_guards.get_settings")
def test_confirmed_ftv_still_blocks_deep_collapse(mock_settings):
    """A deeper collapse (below the floor) is a real fade — still blocked even for a FTV."""
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.ftv_premium_fade_fill_enabled = True
    s.ftv_premium_fade_fill_max_drawdown_pct = -0.6
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-0.44,
        premium_momentum_5s=-2.35,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=20.0, tier="EXPLODING"),
        confirmed_ftv_bypass=True,
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_shallow_dip_still_blocks_without_ftv_bypass(mock_settings):
    """Without the confirmed-FTV bypass, even a shallow dip blocks (default behaviour)."""
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.ftv_premium_fade_fill_enabled = True
    s.ftv_premium_fade_fill_max_drawdown_pct = -0.6
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-0.30,
        premium_momentum_5s=-0.40,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=20.0, tier="EXPLODING"),
        confirmed_ftv_bypass=False,
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_ftv_fade_fill_only_for_elite_exploding(mock_settings):
    """The shallow-fade bypass is restricted to ELITE/EXPLODING events."""
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    s.ftv_premium_fade_fill_enabled = True
    s.ftv_premium_fade_fill_max_drawdown_pct = -0.6
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-0.30,
        premium_momentum_5s=-0.40,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=20.0, tier="BUILDING"),
        confirmed_ftv_bypass=True,
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_early_pad_fills_through_shallow_dip(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.35
    s.early_radar_pad_fade_fill_enabled = True
    s.early_radar_pad_fade_fill_max_drawdown_pct = -1.5
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-0.90,
        premium_momentum_5s=-1.20,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=12.0, tier="BUILDING"),
        early_pad_bypass=True,
    )
    assert not blocked
    assert reason == "early_pad_shallow_fade_ok"


@patch("app.engines.winner_entry_guards.get_settings")
def test_early_pad_still_blocks_deep_collapse(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.35
    s.early_radar_pad_fade_fill_enabled = True
    s.early_radar_pad_fade_fill_max_drawdown_pct = -1.5
    mock_settings.return_value = s

    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-1.80,
        premium_momentum_5s=-2.35,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=12.0, tier="BUILDING"),
        early_pad_bypass=True,
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_chop_weak_explosion_blocked(mock_settings):
    s = MagicMock()
    s.all_day_explosion_session_move_min_pct = 40.0
    s.aggressive_min_explosion_score = 45.0
    s.explosion_chop_min_session_move_pct = 28.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    mock_settings.return_value = s

    snap = MagicMock()
    snap.regime = Regime.CHOP
    snap.spotChart = None
    candidate = SimpleNamespace(
        mode="explosion",
        score=50.0,
        tier="EXPLODING",
        explosion_event=_event(daily_move=5.0),
        alert={"ictFlatThenVertical": False, "ictDisplacement": True},
    )
    blocked, reason = chop_weak_explosion_blocks_entry(candidate, snap)
    assert blocked
    assert "chop_immature" in reason or reason == "chop_weak_explosion"
