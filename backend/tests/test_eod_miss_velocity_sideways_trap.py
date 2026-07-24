"""Jul24 EOD miss follow-ups: structured CE velocity, sideways 75, local-base trap skip."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import (
    detect_fake_explosion_trap,
    live_explosion_confirmation_blocked,
    structured_near_atm_call,
)
from app.engines.whipsaw_guards import check_bearish_sideways_entry
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.explosion_live_confirm_enabled = True
    s.explosion_live_confirm_min_velocity_3s = 2.0
    s.explosion_live_confirm_ict_min_velocity_3s = 1.5
    s.explosion_live_confirm_structured_ce_min_velocity_3s = 1.0
    s.structured_near_atm_max_otm_steps = 3
    s.explosion_live_confirm_require_structure = True
    s.explosion_live_confirm_hot_velocity_3s = 8.0
    s.explosion_live_confirm_premium_capture_bypass = True
    s.explosion_live_confirm_premium_min_vol_surge = 1.3
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.local_base_overrides_session_chart_enabled = True
    s.local_base_ichimoku_chart_bypass_enabled = True
    s.local_base_chart_bypass_require_ichimoku = False
    s.local_base_overrides_bearish_breadth = True
    s.local_base_ichimoku_max_adverse_mom5_pct = 0.12
    s.local_base_chart_bypass_min_score = 38.0
    s.local_base_chart_bypass_radar_min_move_pct = 28.0
    s.whipsaw_guards_enabled = True
    s.bearish_sideways_halt_enabled = True
    s.bearish_sideways_block_scalps = True
    s.bearish_sideways_explosion_min_score = 78.0
    s.bearish_sideways_local_base_min_score = 75.0
    s.worst_day_breakout_min_velocity_3s = 2.5
    s.worst_day_structured_ce_min_velocity_3s = 1.5
    s.worst_day_breakout_peak_velocity_bypass_enabled = True
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_midday_require_structure = True
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.fake_explosion_trap_post_win_lot_cap = 8
    s.fake_explosion_trap_post_win_max_pnl_inr = 3000.0
    s.fake_explosion_trap_post_win_lookback = 1
    s.fake_explosion_trap_psychology_escalate = True
    s.fake_explosion_trap_skip_soft_cut_base_window = True
    s.fake_explosion_trap_max_premium_mom_pct = 0.15
    s.nifty_strike_step = 50.0
    s.moneyness_atm_tolerance_points = 50.0
    s.moneyness_explosion_prefer = "ATM"
    s.trade_moneyness_mode = "AUTO"
    s.moneyness_selection_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, spot=23785.0, atm=23800.0):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=atm,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=54.8,
        breadth=Breadth(bias="NEUTRAL", score=50, aligned=False),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=0.02,
            momentum15Pct=-0.2,
            momentum30Pct=-0.3,
            trendStrength=40,
            emaBias="BEARISH",
            candleBias="NEUTRAL",
            orPosition="BELOW",
            macdBias="BEARISH",
            rsi=45,
            spot=spot,
        ),
        explosionAlerts=[{
            "side": "CALL",
            "strike": 23850.0,
            "tier": "EXPLODING",
            "explosionScore": 88.5,
            "dailyMovePct": 36.0,
            "peakMovePct": 36.0,
            "ictFlatThenVertical": True,
            "ictBreakout": True,
            "ictBaseRelativeMovePct": 30.0,
            "ictPattern": "flat_then_vertical",
            "tradeable": True,
        }],
    )


def _ict(**kw):
    defaults = dict(
        active=True,
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=False,
        mega_rip=False,
        premium_fvg=False,
        local_swing_base=False,
        base_relative_move_pct=30.0,
        session_move_pct=36.0,
        velocity_3s=0.4,
        volume_surge=2.0,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _event(*, strike=23850.0, v3=0.4, tier="EXPLODING", score=88.5, move=36.0):
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=strike,
        tier=tier,
        explosion_score=score,
        velocity_3s=v3,
        velocity_9s=0.5,
        volume_surge=2.0,
        daily_move_pct=move,
        peak_move_pct=move,
        premium=100.0,
    )


@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_near_atm_call_detects_23850(mock_eg, mock_lb):
    s = _settings()
    mock_eg.return_value = s
    mock_lb.return_value = s
    snap = _snap()
    assert structured_near_atm_call(
        Side.CALL, 23850.0, snap, ict=_ict(), alert=snap.explosionAlerts[0],
    ) is True
    assert structured_near_atm_call(
        Side.CALL, 24100.0, snap, ict=_ict(), alert=snap.explosionAlerts[0],
    ) is False  # 6 OTM


@patch("app.engines.explosion_detector.retained_peak_velocity_3s", return_value=3.2)
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_live_confirm_allows_structured_ce_with_peak_velocity(mock_eg, mock_lb, _peak):
    s = _settings()
    mock_eg.return_value = s
    mock_lb.return_value = s
    snap = _snap()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(v3=0.4),
        ict=_ict(),
        snap=snap,
    )
    assert blocked is False


@patch("app.engines.explosion_detector.retained_peak_velocity_3s", return_value=0.0)
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_live_confirm_still_blocks_dead_structured_ce(mock_eg, mock_lb, _peak):
    s = _settings()
    mock_eg.return_value = s
    mock_lb.return_value = s
    snap = _snap()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(v3=0.2),
        ict=_ict(),
        snap=snap,
    )
    assert blocked is True
    assert "stale_live_velocity" in reason


@patch("app.engines.explosion_detector.retained_peak_velocity_3s", return_value=2.8)
@patch("app.engines.ict_breakout_monitor.analyze_explosion_event_ict")
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.worst_day_guard.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_worst_day_soft_velocity_for_structured_ce(
    mock_eg, mock_wd, mock_lb, mock_ict, _peak,
):
    from app.engines.worst_day_guard import worst_day_allows_candidate
    from app.models.schemas import AutoTraderState

    s = _settings()
    s.worst_day_pause_enabled = True
    s.worst_day_breakout_only_enabled = True
    s.worst_day_breakout_min_rank = 68.0
    s.worst_day_breakout_min_symbol_tqs = 45.0
    s.worst_day_breakout_require_chart_align = False
    s.worst_day_breakout_tiers_csv = "ELITE,EXPLODING"
    s.worst_day_full_pause_loss_inr = -50000.0
    s.worst_day_early_chop_pause = True
    s.worst_day_min_losses = 3
    s.worst_day_min_loss_inr = -15000.0
    mock_eg.return_value = s
    mock_wd.return_value = s
    mock_lb.return_value = s
    mock_ict.return_value = _ict(velocity_3s=1.6)
    snap = _snap()
    snap.tradeQualityScore = 54.8
    snap.breadth = Breadth(bias="BULLISH", score=70, aligned=True)
    event = _event(v3=1.6, score=88.5)
    cand = SimpleNamespace(
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        score=88.5,
        side=Side.CALL,
        strike=23850.0,
        symbol="NIFTY",
        alert=snap.explosionAlerts[0],
        explosion_event=event,
    )
    with patch(
        "app.engines.worst_day_guard.session_entry_policy",
        return_value=("BREAKOUT_ONLY", {"worstDay": {"isWorst": True}}),
    ), patch(
        "app.engines.worst_day_guard._breadth_aligned", return_value=True,
    ), patch(
        "app.engines.explosion_detector.effective_breakout_velocities",
        return_value=(1.6, 1.8, {}),
    ):
        ok, reason, meta = worst_day_allows_candidate(
            cand, AutoTraderState(), {"NIFTY": snap}, policy="BREAKOUT_ONLY",
        )
    assert ok, reason
    assert meta.get("structuredNearAtmCe") is True


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=True)
@patch("app.engines.whipsaw_guards.is_bearish_sideways", return_value=True)
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.whipsaw_guards.get_settings")
def test_sideways_allows_local_base_ce_at_75(mock_ws, mock_lb, _bs, _bss):
    s = _settings()
    mock_ws.return_value = s
    mock_lb.return_value = s
    snap = _snap()
    cand = SimpleNamespace(
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        score=77.0,
        side=Side.CALL,
        strike=23900.0,
        alert={
            "side": "CALL",
            "strike": 23900.0,
            "tier": "EXPLODING",
            "explosionScore": 77.0,
            "dailyMovePct": 38.0,
            "ictFlatThenVertical": True,
            "ictBaseRelativeMovePct": 30.0,
            "ictPattern": "flat_then_vertical",
        },
        explosion_event=None,
    )
    blocked, reason = check_bearish_sideways_entry(cand, {snap.symbol: snap})
    assert blocked is False


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=True)
@patch("app.engines.whipsaw_guards.is_bearish_sideways", return_value=True)
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.whipsaw_guards.get_settings")
def test_sideways_still_blocks_low_score_without_local_base(mock_ws, mock_lb, _bs, _bss):
    s = _settings()
    mock_ws.return_value = s
    mock_lb.return_value = s
    snap = _snap()
    cand = SimpleNamespace(
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        score=70.0,
        side=Side.CALL,
        strike=23900.0,
        alert={
            "side": "CALL",
            "tier": "EXPLODING",
            "explosionScore": 70.0,
            "dailyMovePct": 10.0,
            "ictFlatThenVertical": False,
            "ictBreakout": False,
            "ictBaseRelativeMovePct": 0,
            "ictPattern": "watch",
        },
        explosion_event=None,
    )
    blocked, reason = check_bearish_sideways_entry(cand, {snap.symbol: snap})
    assert blocked is True
    assert reason == "bearish_sideways_explosion_only"


@patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True)
@patch("app.engines.explosion_entry_guards._regime_chopish", return_value=True)
@patch("app.engines.explosion_entry_guards._premium_mom_flat", return_value=False)
@patch("app.engines.explosion_entry_guards._post_small_win", return_value=(False, {}))
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_fake_trap_skips_midday_block_with_local_base(
    mock_eg, mock_lb, _post, _flat, _chop, _mid,
):
    s = _settings()
    mock_eg.return_value = s
    mock_lb.return_value = s
    snap = _snap()
    event = _event(tier="ELITE", score=100, v3=0.1, move=40.0)
    cand = SimpleNamespace(
        mode="explosion",
        tier="ELITE",
        score=100.0,
        side=Side.CALL,
        strike=23850.0,
        alert=snap.explosionAlerts[0],
        explosion_event=event,
    )
    # No ICT object — structure comes from local-base alert flags.
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap, ict=None)
    assert blocked is False or reason != "fake_explosion_trap_midday_no_structure"
    assert meta.get("localBaseStructure") is True or blocked is False
