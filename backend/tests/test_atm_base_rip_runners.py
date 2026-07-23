"""ATM ICT flat→vertical base-rip runners — enter early, full size, hold never-green grace.

Jul23 SENSEX 76300 PE: base ~30–40 → ~140. Gaps fixed:
1. BUILDING+ICT enterable before EXPLODING (~40%)
2. Never-green adaptive-stop grace for HC/ICT (was killed at best=0)
3. Base-relative chase ignores huge session % abs_cap
4. Composer bias bypass for ICT flat→vertical (not only ELITE)
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent, _apply_sticky_score, reset_detector_state_for_tests
from app.engines.explosion_entry_guards import cap_extended_chase_lots
from app.engines.explosion_profit import _defer_adaptive_stop, check_explosion_entry
from app.engines.pretrade_validator import validate_candidate
from app.models.schemas import AutoTraderState, Breadth, PaperTrade, Side, StrategyType, SuggestedTrade

IST = ZoneInfo("Asia/Kolkata")


def _ict_signal(**kwargs):
    base = dict(
        active=True,
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=False,
        premium_fvg=False,
        session_move_pct=33.0,
        base_relative_move_pct=40.0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _building_event(**kwargs):
    defaults = dict(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        premium=40.0,
        velocity_3s=4.0,
        velocity_9s=6.0,
        velocity_15s=5.0,
        volume_surge=2.0,
        explosion_score=55.0,
        tier="BUILDING",
        reason="ict_flat_vertical",
        daily_move_pct=33.0,
        peak_move_pct=33.0,
    )
    defaults.update(kwargs)
    return ExplosionEvent(**defaults)


def _entry_settings():
    s = MagicMock()
    s.aggressive_min_explosion_score = 45.0
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.open_premium_min_move_pct = 25.0
    s.explosion_breadth_alignment_enabled = True
    s.index_pin_put_block_enabled = False
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_exhaustion_consolidation_reset_enabled = True
    s.explosion_exhaustion_reset_minutes = 12.0
    s.explosion_exhaustion_consolidation_v3_max = 0.8
    s.explosion_exhaustion_consolidation_v9_max = 1.2
    s.neutral_breadth_min_score = 55.0
    s.chop_day_guards_enabled = True
    s.base_rip_never_green_grace_seconds = 90.0
    s.base_rip_never_green_stop_mult = 2.0
    return s


@patch(
    "app.engines.explosion_entry_guards.live_explosion_confirmation_blocked",
    return_value=(False, ""),
)
@patch("app.engines.explosion_profit._ict_flat_vertical_entry_ok", return_value=True)
@patch("app.engines.morning_premium_capture.is_premium_capture_event", return_value=False)
@patch("app.engines.morning_premium_capture.is_all_day_explosion_event", return_value=False)
@patch("app.engines.morning_premium_capture.premium_led_explosion_bypass", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
def test_building_ict_flat_vertical_enters(mock_settings, *_mocks):
    mock_settings.return_value = _entry_settings()
    event = _building_event()
    trade = SuggestedTrade(
        id="x", symbol="SENSEX", side=Side.PUT, strike=76300.0,
        lastPremium=40.0, tqs=55.0, strategyType="EXPLOSIVE", confidence=55.0,
    )
    breadth = Breadth(bias="BEARISH", score=60, aligned=True)
    ok, reason = check_explosion_entry(event, trade, breadth, False, snap=None)
    assert ok is True
    assert reason == "ict_building_flat_vertical"


@patch("app.engines.explosion_profit._ict_flat_vertical_entry_ok", return_value=False)
@patch("app.engines.morning_premium_capture.is_premium_capture_event", return_value=False)
@patch("app.engines.morning_premium_capture.is_all_day_explosion_event", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
def test_building_without_ict_still_rejected(mock_settings, *_mocks):
    mock_settings.return_value = _entry_settings()
    event = _building_event(explosion_score=55.0)
    trade = SuggestedTrade(
        id="x", symbol="SENSEX", side=Side.PUT, strike=76300.0,
        lastPremium=40.0, tqs=55.0, strategyType="EXPLOSIVE", confidence=55.0,
    )
    breadth = Breadth(bias="BEARISH", score=60, aligned=True)
    ok, reason = check_explosion_entry(event, trade, breadth, False, snap=None)
    assert ok is False
    assert "tier_BUILDING" in reason


def test_never_green_grace_defers_hc_runner():
    s = _entry_settings()
    trade = PaperTrade(
        id="hc1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        entryPremium=40.0,
        currentPremium=35.0,
        lots=10,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        bestPnlPoints=0.0,
        entryContext={"highConviction": True, "ictFlatThenVertical": True},
    )
    # −5pt vs stop_floor 8 → within grace (2× floor = 16) → defer
    assert _defer_adaptive_stop(
        trade, best=0.0, hold=30.0, settings=s, pnl_pts=-5.0, stop_floor=8.0,
    ) is True


def test_never_green_grace_hard_floor_still_kills():
    s = _entry_settings()
    trade = PaperTrade(
        id="hc2",
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        entryPremium=40.0,
        currentPremium=20.0,
        lots=10,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        bestPnlPoints=0.0,
        entryContext={"highConviction": True},
    )
    # −20pt vs 2×8=16 floor → hard stop, no defer
    assert _defer_adaptive_stop(
        trade, best=0.0, hold=30.0, settings=s, pnl_pts=-20.0, stop_floor=8.0,
    ) is False


def test_never_green_no_grace_for_plain_scalp():
    """#156 never-green hard-stop must still fire for non-HC trades."""
    s = _entry_settings()
    trade = PaperTrade(
        id="sc1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200.0,
        entryPremium=120.0,
        currentPremium=115.0,
        lots=6,
        strategyType=StrategyType.SCALP,
        openedAt=datetime.now(IST),
        bestPnlPoints=0.0,
        entryContext={"selectionScore": 50.0},
    )
    assert _defer_adaptive_stop(
        trade, best=0.0, hold=30.0, settings=s, pnl_pts=-5.0, stop_floor=8.0,
    ) is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_ict_base_window_keeps_full_lots(mock_s):
    s = MagicMock()
    s.explosion_hard_lot_cap = 10
    s.explosion_extended_soft_min_move_pct = 50.0
    s.explosion_extended_soft_lot_cap = 6
    s.ict_base_relative_chase_max_move_pct = 55.0
    mock_s.return_value = s
    event = SimpleNamespace(daily_move_pct=80.0, peak_move_pct=80.0)
    ict = _ict_signal(base_relative_move_pct=40.0)
    assert cap_extended_chase_lots(10, event, ict=ict) == 10


@patch("app.engines.explosion_entry_guards.get_settings")
def test_extended_without_ict_still_soft_caps(mock_s):
    s = MagicMock()
    s.explosion_hard_lot_cap = 10
    s.explosion_extended_soft_min_move_pct = 50.0
    s.explosion_extended_soft_lot_cap = 6
    s.ict_base_relative_chase_max_move_pct = 55.0
    mock_s.return_value = s
    event = SimpleNamespace(daily_move_pct=80.0, peak_move_pct=80.0)
    assert cap_extended_chase_lots(10, event, ict=None) == 6


@patch("app.engines.pretrade_validator.check_min_entry_interval", return_value=(False, "stop_after_composer"))
@patch("app.engines.chop_day_guards.is_chop_session", return_value=False)
@patch("app.engines.extreme_explosion_moment.is_high_mover_elite_bypass", return_value=False)
@patch("app.engines.extreme_explosion_moment.is_extreme_explosion_all_in_bypass", return_value=False)
@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.composer_market_monitor.get_latest_brief")
def test_composer_ict_flat_vertical_bypasses_bias(
    mock_brief, mock_settings, *_mocks,
):
    s = MagicMock()
    s.controlled_trading_enabled = True
    s.composer_hard_gate_enabled = True
    s.composer_bias_gate_enabled = True
    s.composer_ict_flat_vertical_bias_bypass = True
    s.expiry_worst_day_elite_top_composer_bypass = False
    mock_settings.return_value = s
    mock_brief.return_value = {"standDown": False, "tradeBias": "CALL"}

    c = MagicMock()
    c.mode = "explosion"
    c.side = Side.PUT
    c.strike = 76300.0
    c.symbol = "SENSEX"
    c.tier = "BUILDING"
    c.score = 55.0
    c.tqs = 55.0
    c.confidence = 55.0
    c.explosion_event = None
    c.ictFlatThenVertical = True
    c.alert = {"ictFlatThenVertical": True}
    c.ict = _ict_signal()

    ok, reason, meta = validate_candidate(c, AutoTraderState(), session_trades=[])
    assert ok is False
    assert reason == "stop_after_composer"
    assert meta.get("composerBiasBypass") == "ict_flat_vertical"


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.composer_market_monitor.get_latest_brief")
def test_composer_building_without_ict_still_blocked(mock_brief, mock_settings):
    s = MagicMock()
    s.controlled_trading_enabled = True
    s.composer_hard_gate_enabled = True
    s.composer_bias_gate_enabled = True
    s.composer_ict_flat_vertical_bias_bypass = True
    s.expiry_worst_day_elite_top_composer_bypass = False
    mock_settings.return_value = s
    mock_brief.return_value = {"standDown": False, "tradeBias": "CALL"}

    c = MagicMock()
    c.mode = "explosion"
    c.side = Side.PUT
    c.strike = 76300.0
    c.symbol = "SENSEX"
    c.tier = "BUILDING"
    c.score = 55.0
    c.tqs = 55.0
    c.confidence = 55.0
    c.explosion_event = None
    c.ictFlatThenVertical = False
    c.alert = {}
    c.ict = None

    ok, reason, meta = validate_candidate(c, AutoTraderState(), session_trades=[])
    assert ok is False
    assert "composer_bias" in reason


def test_building_score_sticky_holds_through_dip():
    reset_detector_state_for_tests()
    k = "SENSEX:PUT:76300"
    assert _apply_sticky_score(k, 55.0, "BUILDING") == 55.0
    assert _apply_sticky_score(k, 38.0, "BUILDING") == 55.0
