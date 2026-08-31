"""Aug31 NIFTY CALL 24150 — elite flip + defensive rip at armed local base after PUT loss."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.ict_breakout_monitor import _defensive_base_rip_top_allowed
from app.engines.pretrade_validator import TradeRecord
from app.engines.whipsaw_guards import check_whipsaw_candidate
from app.models.schemas import AutoTraderState, Side


def _settings(**overrides):
    s = MagicMock()
    s.whipsaw_guards_enabled = True
    s.whipsaw_elite_momentum_flip_bypass_enabled = True
    s.whipsaw_elite_momentum_flip_min_score = 85.0
    s.bearish_sideways_block_scalps = False
    s.quick_sideways_allow_bearish_chop = True
    s.ict_defensive_base_rip_require_top_quality = True
    s.ict_defensive_base_rip_min_score = 80.0
    s.ict_defensive_base_rip_min_quality = 70.0
    s.ict_defensive_base_rip_min_velocity_3s = 2.5
    s.top_ftv_a_pad_velocity_min_move_pct = 8.0
    s.top_ftv_a_pad_velocity_max_move_pct = 25.0
    s.ict_v_rip_pad_min_move_pct = 2.0
    s.ict_v_rip_max_move_pct = 25.0
    s.ict_v_rip_volume_awake_min_velocity_3s = 0.85
    s.ict_v_rip_min_velocity_3s = 1.2
    s.ict_armed_base_launch_cold_velocity_3s = -0.5
    s.ict_v_rip_min_score = 40.0
    s.ict_v_rip_min_quality = 50.0
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _aug31_call_24150_alert(**overrides):
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24150.0,
        "premium": 40.6,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "momentType": "armed_base_launch",
        "ictFirstLift": False,
        "ictFlatThenVertical": True,
        "ictArmedBaseLaunch": True,
        "ictBreakout": True,
        "localBaseMovePct": 10.3,
        "ictBaseRelativeMovePct": 10.3,
        "dailyMovePct": 10.33,
        "peakMovePct": 10.46,
        "velocity3s": 0.0,
        "volumeAwaken": True,
        "volumeSurge": 2.5,
    }
    alert.update(overrides)
    return alert


def _candidate(**overrides):
    cand = MagicMock()
    cand.symbol = "NIFTY"
    cand.side = Side.CALL
    cand.mode = "explosion"
    cand.tier = "ELITE"
    cand.score = 100.0
    cand.snap = MagicMock()
    cand.alert = _aug31_call_24150_alert()
    cand.explosion_event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        premium=40.6,
        velocity_3s=0.0,
        velocity_9s=0.0,
        velocity_15s=0.0,
        volume_surge=2.5,
        explosion_score=100,
        tier="ELITE",
        reason="armed_base_launch",
        daily_move_pct=10.33,
        peak_move_pct=10.46,
    )
    for key, value in overrides.items():
        setattr(cand, key, value)
    return cand


@patch("app.engines.whipsaw_guards.get_settings")
def test_elite_flip_bypass_at_armed_local_base_after_put_loss(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    trades = [
        TradeRecord("NIFTY", "PUT", -1059.5, "adaptive_stop_loss", 23950, "1329fea0")
    ]
    snap = MagicMock()
    with patch(
        "app.engines.whipsaw_guards.collect_session_trades", return_value=trades
    ), patch(
        "app.engines.whipsaw_guards.is_bearish_sideways", return_value=True
    ), patch(
        "app.engines.whipsaw_guards.detect_ce_pe_whipsaw", return_value=(False, {})
    ), patch(
        "app.engines.whipsaw_guards.check_bearish_sideways_entry",
        return_value=(False, "ok"),
    ), patch(
        "app.engines.whipsaw_guards.check_opposite_side_cooldown",
        return_value=(False, "ok"),
    ):
        ok, reason, meta = check_whipsaw_candidate(_candidate(), state, {"NIFTY": snap})
    assert ok, reason
    assert meta.get("eliteMomentumFlipBypass") is True


@patch("app.engines.whipsaw_guards.get_settings")
def test_flip_still_blocked_without_local_base_pad(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState()
    trades = [
        TradeRecord("NIFTY", "PUT", -1059.5, "adaptive_stop_loss", 23950, "1329fea0")
    ]
    cand = _candidate()
    cand.alert = _aug31_call_24150_alert(localBaseMovePct=1.0, ictBaseRelativeMovePct=1.0)
    with patch(
        "app.engines.whipsaw_guards.collect_session_trades", return_value=trades
    ), patch(
        "app.engines.whipsaw_guards.is_bearish_sideways", return_value=True
    ):
        ok, reason, _ = check_whipsaw_candidate(cand, state, {"NIFTY": MagicMock()})
    assert not ok
    assert reason == "no_flip_after_PUT_loss"


def test_defensive_rip_softens_cold_v3_for_armed_flat_vertical_at_pad():
    settings = _settings()
    ok, reason = _defensive_base_rip_top_allowed(
        tier="ELITE",
        quality=82.0,
        score=100.0,
        velocity_3s=0.0,
        settings=settings,
        base_move_pct=10.3,
        volume_awake=True,
        armed_base_launch=True,
        first_lift=True,
    )
    assert ok is True
    assert reason == "ok"


def test_defensive_rip_still_blocks_extended_pad_chase():
    settings = _settings()
    ok, reason = _defensive_base_rip_top_allowed(
        tier="ELITE",
        quality=82.0,
        score=100.0,
        velocity_3s=0.0,
        settings=settings,
        base_move_pct=30.0,
        volume_awake=True,
        armed_base_launch=True,
        first_lift=True,
    )
    assert ok is False
    assert "defensive_rip_top_v3" in reason
