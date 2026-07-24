"""Chop-day guardrail tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chop_day_guards import (
    alert_is_loss_streak_elite_bypass,
    apply_tiered_lot_cap,
    is_chop_session,
    is_loss_streak_elite_bypass_candidate,
    neutral_breadth_blocks_entry,
    record_session_trade_close,
    reset_session_guards,
    resolve_session_entry_pause,
    session_pause_active,
    snapshots_have_loss_streak_elite_bypass,
    symbol_rank_adjustment,
)
from app.models.schemas import AutoTraderState, Breadth, Regime, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(bias: str = "NEUTRAL", regime: Regime = Regime.RANGE_BOUND) -> SymbolSnapshot:
    from app.models.schemas import MarketPhase

    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=regime,
        breadth=Breadth(score=50, bias=bias, aligned=False),
    )


@patch("app.engines.chop_day_guards.get_settings")
def test_chop_session_detected(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    mock_settings.return_value = s
    snaps = {"NIFTY": _snap("NEUTRAL"), "SENSEX": _snap("NEUTRAL")}
    assert is_chop_session(snaps)


@patch("app.engines.chop_day_guards.get_settings")
def test_neutral_breadth_blocks_low_score(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.neutral_breadth_min_score = 60.0
    s.neutral_breadth_explosion_min_score = 55.0
    s.explosion_early_velocity_3s = 3.0
    s.momentum_bypass_velocity_pct = 2.5
    s.momentum_bypass_volume_surge = 1.4
    s.momentum_bypass_explosion_score = 48.0
    mock_settings.return_value = s
    blocked, reason = neutral_breadth_blocks_entry("NEUTRAL", 52.0, velocity_pct=1.0)
    assert blocked
    assert "neutral_breadth" in reason


@patch("app.engines.chop_day_guards.get_settings")
def test_sensex_rank_bonus_on_chop(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.sensex_rank_bonus = 10.0
    s.nifty_rank_penalty_chop = 5.0
    mock_settings.return_value = s
    assert symbol_rank_adjustment("SENSEX", True) == 10.0
    assert symbol_rank_adjustment("NIFTY", True) == -5.0


@patch("app.engines.chop_day_guards.get_settings")
def test_loss_streak_pause(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.loss_streak_pause_count = 3
    s.loss_streak_pause_seconds = 1200
    s.session_large_loss_pause_inr = 15_000.0
    s.session_large_loss_pause_seconds = 900
    mock_settings.return_value = s
    reset_session_guards()
    record_session_trade_close(-1000)
    record_session_trade_close(-1000)
    assert not session_pause_active()[0]
    record_session_trade_close(-1000)
    paused, reason = session_pause_active()
    assert paused
    assert "loss_streak_pause" in reason


@patch("app.engines.chop_day_guards.get_settings")
def test_large_single_loss_pauses_entries(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.loss_streak_pause_count = 3
    s.loss_streak_pause_seconds = 1200
    s.session_large_loss_pause_inr = 15_000.0
    s.session_large_loss_pause_seconds = 900
    mock_settings.return_value = s
    reset_session_guards()
    record_session_trade_close(-30_447)
    paused, reason = session_pause_active()
    assert paused
    assert "large_loss_pause" in reason


def _elite_bypass_settings(**overrides):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.loss_streak_pause_count = 2
    s.loss_streak_pause_seconds = 1200
    s.session_large_loss_pause_inr = 15_000.0
    s.session_large_loss_pause_seconds = 900
    s.loss_streak_elite_bypass_enabled = True
    s.loss_streak_elite_bypass_min_score = 90.0
    s.loss_streak_elite_bypass_min_chart_confidence = 56.9
    s.loss_streak_elite_bypass_tiers_csv = "ELITE,EXPLODING"
    s.loss_streak_elite_bypass_min_move_pct = 28.0
    s.loss_streak_elite_bypass_max_move_pct = 70.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _elite_alert(**overrides):
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 76400.0,
        "premium": 47.0,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "dailyMovePct": 35.0,
        "peakMovePct": 35.0,
        "ictFlatThenVertical": True,
        "ictMegaRip": False,
        "ictBreakout": True,
        "ictScore": 82.0,
        "ictBaseRelativeMovePct": 32.0,
    }
    alert.update(overrides)
    return alert


def _elite_snap(alert=None):
    from app.models.schemas import SpotChart

    snap = _snap("BEARISH", Regime.TREND_EXPANSION)
    snap.symbol = "SENSEX"
    snap.spot = 76400.0
    snap.atmStrike = 76400.0
    snap.spotChart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.3,
        momentum15Pct=-0.5,
        trendStrength=70,
        orPosition="BELOW",
        emaBias="BEARISH",
        candleBias="BEARISH",
        macdBias="BEARISH",
        rsi=35,
        spot=76400.0,
    )
    snap.explosionAlerts = [alert or _elite_alert()]
    return snap


@patch("app.engines.chop_day_guards.get_settings")
def test_alert_elite_bypass_accepts_high_elite_with_ict(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    snap = _elite_snap()
    assert alert_is_loss_streak_elite_bypass(snap.explosionAlerts[0], snap) is True
    assert snapshots_have_loss_streak_elite_bypass({"SENSEX": snap}) is True


@patch("app.engines.chop_day_guards.get_settings")
def test_alert_elite_bypass_rejects_low_score(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    snap = _elite_snap(_elite_alert(explosionScore=70.0))
    assert alert_is_loss_streak_elite_bypass(snap.explosionAlerts[0], snap) is False


@patch("app.engines.chop_day_guards.get_settings")
def test_alert_elite_bypass_rejects_extended_chase_without_base_rel(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    snap = _elite_snap(
        _elite_alert(
            dailyMovePct=120.0,
            peakMovePct=120.0,
            ictFlatThenVertical=False,
            ictBaseRelativeMovePct=0.0,
            ictBreakout=False,
            ictScore=0.0,
        )
    )
    # No ICT / chart path — confidence fails and move is past ceiling.
    with patch(
        "app.engines.chart_exit_levels.chart_trade_confidence",
        return_value=(40.0, []),
    ):
        assert alert_is_loss_streak_elite_bypass(snap.explosionAlerts[0], snap) is False


@patch("app.engines.chop_day_guards.get_settings")
def test_alert_elite_bypass_accepts_base_relative_ict_rip(mock_settings):
    """Fast flat→vertical past session ceiling still qualifies via base-relative move."""
    mock_settings.return_value = _elite_bypass_settings()
    snap = _elite_snap(
        _elite_alert(
            dailyMovePct=95.0,
            peakMovePct=95.0,
            ictFlatThenVertical=True,
            ictBaseRelativeMovePct=40.0,
        )
    )
    assert alert_is_loss_streak_elite_bypass(snap.explosionAlerts[0], snap) is True


@patch("app.engines.chop_day_guards.get_settings")
def test_exploding_needs_ict_structure(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    bare = _elite_snap(
        _elite_alert(
            tier="EXPLODING",
            explosionScore=95.0,
            ictFlatThenVertical=False,
            ictMegaRip=False,
            ictBreakout=False,
            ictScore=0.0,
        )
    )
    assert alert_is_loss_streak_elite_bypass(bare.explosionAlerts[0], bare) is False
    structured = _elite_snap(
        _elite_alert(
            tier="EXPLODING",
            explosionScore=95.0,
            ictFlatThenVertical=True,
            ictScore=80.0,
            ictBreakout=True,
        )
    )
    assert alert_is_loss_streak_elite_bypass(structured.explosionAlerts[0], structured) is True


@patch("app.engines.chop_day_guards.get_settings")
def test_loss_streak_pause_lifts_for_elite_only(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    reset_session_guards()
    record_session_trade_close(-1000)
    record_session_trade_close(-1000)
    assert session_pause_active()[0] is True

    empty = {"SENSEX": _snap("BEARISH", Regime.TREND_EXPANSION)}
    empty["SENSEX"].symbol = "SENSEX"
    empty["SENSEX"].explosionAlerts = []
    blocked, reason, meta = resolve_session_entry_pause(empty)
    assert blocked is True
    assert "loss_streak_pause" in reason
    assert not meta.get("lossStreakEliteOnly")

    snaps = {"SENSEX": _elite_snap()}
    blocked, reason, meta = resolve_session_entry_pause(snaps)
    assert blocked is False
    assert reason == "loss_streak_elite_bypass"
    assert meta.get("lossStreakEliteOnly") is True
    # Raw pause flag remains for UI / streak accounting.
    assert session_pause_active()[0] is True


@patch("app.engines.chop_day_guards.get_settings")
def test_large_loss_pause_never_bypassed_by_elite(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    reset_session_guards()
    record_session_trade_close(-30_000)
    snaps = {"SENSEX": _elite_snap()}
    blocked, reason, meta = resolve_session_entry_pause(snaps)
    assert blocked is True
    assert "large_loss_pause" in reason
    assert not meta.get("lossStreakEliteBypass")


@patch("app.engines.chop_day_guards.get_settings")
def test_elite_only_candidate_gate(mock_settings):
    mock_settings.return_value = _elite_bypass_settings()
    from app.engines.trade_selector import EntryCandidate
    from app.models.schemas import Side, StrategyType

    snap = _elite_snap()
    elite = EntryCandidate(
        symbol="SENSEX",
        snap=snap,
        mode="explosion",
        score=100.0,
        side=Side.PUT,
        strike=76400.0,
        premium=47.0,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=100.0,
        tqs=80.0,
        tier="ELITE",
        alert=snap.explosionAlerts[0],
    )
    assert is_loss_streak_elite_bypass_candidate(elite) is True

    scalp = EntryCandidate(
        symbol="SENSEX",
        snap=snap,
        mode="scalp",
        score=70.0,
        side=Side.PUT,
        strike=76400.0,
        premium=47.0,
        strategy_type=StrategyType.SCALP,
        confidence=70.0,
        tqs=60.0,
        tier=None,
        alert=None,
    )
    assert is_loss_streak_elite_bypass_candidate(scalp) is False


@patch("app.engines.chop_day_guards.get_settings")
def test_tiered_lot_cap(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.chop_lots_high = 40
    s.chop_lots_mid = 20
    s.chop_lots_min_rank = 48.0
    s.chop_lots_high_min_rank = 55.0
    s.momentum_bypass_velocity_pct = 2.5
    s.momentum_bypass_volume_surge = 1.4
    s.momentum_bypass_explosion_score = 48.0
    mock_settings.return_value = s
    with patch("app.engines.session_timing.in_midday_chop_window", return_value=False):
        assert apply_tiered_lot_cap(100, 58.0, True, "SENSEX") == 100
        assert apply_tiered_lot_cap(100, 52.0, True, "SENSEX") == 100
        assert apply_tiered_lot_cap(100, 45.0, True, "SENSEX") == 0
        assert apply_tiered_lot_cap(100, 52.0, True, "SENSEX", velocity_pct=3.0) == 100


@patch("app.engines.chop_day_guards.get_settings")
def test_day_mode_bearish(mock_settings):
    from app.engines.chop_day_guards import chop_guard_summary
    from app.models.schemas import AutoTraderState

    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.primary_window_start_hour = 10
    s.primary_window_start_minute = 0
    s.daily_max_trades_pre10_chop = 5
    s.daily_max_trades_chop = 20
    s.loss_streak_pause_count = 3
    s.loss_streak_pause_seconds = 1200
    s.session_large_loss_pause_inr = 15_000.0
    s.session_large_loss_pause_seconds = 900
    s.loss_streak_elite_bypass_enabled = False
    s.momentum_bypass_velocity_pct = 2.5
    s.momentum_bypass_volume_surge = 1.4
    s.momentum_bypass_explosion_score = 48.0
    s.momentum_rally_start_hour = 11
    s.momentum_rally_start_minute = 0
    s.momentum_rally_end_hour = 13
    s.momentum_rally_end_minute = 45
    mock_settings.return_value = s

    snaps = {
        "NIFTY": _snap("BEARISH", Regime.TREND_EXPANSION),
        "SENSEX": _snap("BEARISH", Regime.TREND_EXPANSION),
    }
    snaps["NIFTY"].symbol = "NIFTY"
    snaps["SENSEX"].symbol = "SENSEX"
    # chop_guard_summary pulls many engines; stub the heavy ones so MagicMock
    # numeric comparisons don't explode on unset attrs.
    with patch(
        "app.engines.pretrade_validator.check_last_n_trades_pause",
        return_value=(False, "ok", {}),
    ), patch(
        "app.engines.pretrade_validator.last_n_trades_summary",
        return_value={},
    ), patch(
        "app.engines.pretrade_validator.resolve_effective_daily_trade_cap",
        return_value=(20, "chop"),
    ), patch(
        "app.engines.whipsaw_guards.whipsaw_guard_summary",
        return_value={},
    ), patch(
        "app.engines.session_timing.in_midday_chop_window", return_value=False,
    ), patch(
        "app.engines.session_timing.in_open_caution_window", return_value=False,
    ), patch(
        "app.engines.chop_day_guards.in_momentum_rally_window", return_value=False,
    ), patch(
        "app.engines.chop_day_guards.before_primary_window", return_value=False,
    ), patch(
        "app.engines.expiry_day_guards.is_expiry_session", return_value=False,
    ), patch(
        "app.engines.expiry_day_guards.expiry_guard_summary", return_value={},
    ), patch(
        "app.engines.worst_day_guard.worst_day_guard_summary", return_value={},
    ), patch(
        "app.engines.dual_mode_strategy.dual_mode_summary", return_value={},
    ), patch(
        "app.engines.bad_day_routing.bad_day_routing_summary", return_value={},
    ), patch(
        "app.engines.directional_lock.directional_lock_summary", return_value={},
    ), patch(
        "app.engines.confidence_hold.high_confidence_close_summary", return_value={},
    ), patch(
        "app.engines.psychology_hold.psychology_hold_summary", return_value={},
    ), patch(
        "app.engines.ict_breakout_monitor.ict_monitor_summary", return_value={},
    ), patch(
        "app.engines.worst_day_itm_fade.worst_day_trades_summary", return_value={},
    ), patch(
        "app.engines.moneyness.resolve_preferred_moneyness", return_value="ATM",
    ), patch(
        "app.engines.simple_profit.get_session_targets",
        return_value=MagicMock(sessionLabel="TEST", targetPoints=20),
    ), patch(
        "app.engines.daily_18pct_strategy.get_session_limits",
        return_value=MagicMock(confidenceTier="MEDIUM"),
    ), patch(
        "app.engines.market_momentum.index_moment_summary", return_value={},
    ):
        summary = chop_guard_summary(AutoTraderState(), snaps)
    assert summary["dayMode"] == "BEARISH DAY"
    assert "NIFTY" in summary["symbolBreadth"]
    assert summary["symbolBreadth"]["NIFTY"]["bias"] == "BEARISH"
