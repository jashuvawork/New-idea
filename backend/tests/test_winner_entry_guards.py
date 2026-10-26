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


def _fade_settings(mock_settings):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.execution_chart_min_premium_momentum_pct = -0.15
    mock_settings.return_value = s
    return s


@patch("app.engines.winner_entry_guards.get_settings")
def test_reclaim_off_the_low_is_not_a_fade(mock_settings):
    """26 Oct 09:39: 22500 CE was ~15% off the 127 low. A 0.15% dip is the lift."""
    _fade_settings(mock_settings)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=160.0,
        premium_momentum_3s=-0.47,
        premium_momentum_5s=-0.93,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=15.0, tier="ELITE"),
        premium_off_low_pct=15.0,
    )
    assert not blocked
    assert reason == "premium_lift_off_low_ok"


@patch("app.engines.winner_entry_guards.get_settings")
def test_open_flush_at_the_low_still_fades(mock_settings):
    """26 Oct 09:20: 161→127. Price is the low, so the reclaim waiver stays off."""
    _fade_settings(mock_settings)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=160.0,
        premium_momentum_3s=-12.0,
        premium_momentum_5s=-18.0,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=-21.0, tier="ELITE"),
        premium_off_low_pct=0.4,
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


@patch("app.engines.winner_entry_guards.get_settings")
def test_collapse_off_the_low_still_fades(mock_settings):
    """A fresh -8% dump still blocks after price has left the low."""
    _fade_settings(mock_settings)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=160.0,
        premium_momentum_3s=-6.0,
        premium_momentum_5s=-8.0,
        premium_direction="BEARISH",
        explosion_event=_event(daily_move=40.0, tier="ELITE"),
        premium_off_low_pct=20.0,
    )
    assert blocked
    assert reason == "premium_fading_at_execution"


def _premium_bars(prices: list[float]) -> list[list[float]]:
    bars = []
    for i, px in enumerate(prices):
        bars.append([i, px, px + 0.4, px - 0.4, px, 1000])
    return bars


def test_oct26_lift_candles_do_not_fade_and_the_flush_does():
    """Candle path: the 09:39 reclaim clears, the 09:20 flush still blocks."""
    from app.engines.spot_direction import analyze_premium_chart, premium_blocks_entry
    from app.models.schemas import Side

    down = [161, 156, 151, 146, 141, 136, 131, 127]
    up = [130, 134, 138, 142, 146, 148, 149, 149.5, 150, 150.2, 150.4]
    dip = [150.0, 149.7, 149.4, 149.2, 149.0]
    lift = analyze_premium_chart(_premium_bars(down + up + dip), 149.0)
    assert lift.offLowPct >= 8.0
    assert lift.momentum5Pct < -0.15
    assert lift.momentum3Pct < 0
    blocked, reason = premium_blocks_entry(Side.CALL, lift, trade_score=160.0)
    assert not blocked
    assert reason == "premium_lift_off_low_ok"

    flush_px = [161, 155, 148, 140, 133, 128, 126]
    flush = analyze_premium_chart(_premium_bars(flush_px), 126.0)
    assert flush.offLowPct < 8.0
    blocked, reason = premium_blocks_entry(Side.CALL, flush, trade_score=160.0)
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
