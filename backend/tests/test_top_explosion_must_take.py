"""Top ELITE/EXPLODING ATM/ITM near-base must never be blocked."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.elite_never_block import (
    elite_never_block_active,
    top_explosion_must_take_active,
)
from app.engines.explosion_entry_guards import (
    check_explosion_macd_alignment,
    live_explosion_confirmation_blocked,
)
from app.engines.entry_timing import timing_blocks_entry
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**kwargs):
    s = MagicMock()
    s.explosion_top_must_take_enabled = True
    s.explosion_top_must_take_tiers_csv = "ELITE,EXPLODING"
    s.explosion_top_must_take_min_score = 62.0
    s.explosion_top_must_take_require_atm_itm = True
    s.explosion_elite_never_block_enabled = True
    s.entry_timing_elite_bypass_requires_hot = True
    s.min_option_premium_inr = 18.0
    s.ict_structured_early_entry_enabled = True
    s.ict_structured_early_min_move_pct = 10.0
    s.ict_structured_early_max_move_pct = 45.0
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 55.0
    s.explosion_chase_use_local_base = True
    s.local_base_min_trustworthy_premium = 5.0
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.banknifty_strike_step = 100.0
    s.explosion_macd_alignment_required = True
    s.explosion_live_confirm_enabled = True
    s.explosion_live_confirm_min_velocity_3s = 1.2
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _snap(spot=24500.0):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=spot,
        regime=Regime.CHOP,
        tradeQualityScore=48.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.05,
            macdBias="BULLISH",
        ),
    )


def _event(*, tier="ELITE", premium=72.0, strike=24500.0, base_rel=28.0, v3=0.8):
    return SimpleNamespace(
        tier=tier,
        peak_move_pct=base_rel,
        daily_move_pct=base_rel,
        velocity_3s=v3,
        velocity_9s=0.5,
        volume_surge=1.5,
        side=Side.PUT,
        strike=strike,
        symbol="NIFTY",
        premium=premium,
        explosion_score=100.0,
        ict_base_relative_move_pct=base_rel,
        off_low_move_pct=base_rel,
    )


def _ict(base_rel=28.0):
    return SimpleNamespace(
        active=True,
        flat_then_vertical=True,
        local_swing_base=True,
        volume_awakening=True,
        displacement=True,
        premium_fvg=False,
        mega_rip=False,
        base_relative_move_pct=base_rel,
        session_move_pct=base_rel,
        base_premium=53.8,
        velocity_3s=0.8,
        volume_surge=1.5,
        score=70.0,
    )


def _cand(event, snap):
    return SimpleNamespace(
        mode="explosion",
        tier=event.tier,
        side=event.side,
        strike=event.strike,
        premium=event.premium,
        score=100.0,
        confidence=100.0,
        explosion_event=event,
        snap=snap,
        alert={
            "tier": event.tier,
            "side": "PUT",
            "strike": event.strike,
            "premium": event.premium,
            "explosionScore": 100.0,
            "dailyMovePct": event.daily_move_pct,
            "peakMovePct": event.peak_move_pct,
            "ictBaseRelativeMovePct": event.ict_base_relative_move_pct,
            "ictFlatThenVertical": True,
            "ictBreakout": True,
            "tradeable": True,
        },
    )


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_must_take_near_base_atm_even_when_cold(mock_mny, mock_g, mock_enb):
    s = _settings()
    mock_enb.return_value = s
    mock_g.return_value = s
    mock_mny.return_value = s
    snap = _snap()
    event = _event(v3=0.8, base_rel=28.0)
    ict = _ict(28.0)
    cand = _cand(event, snap)
    assert top_explosion_must_take_active(
        candidate=cand, event=event, snap=snap, ict=ict,
    ) is True
    assert elite_never_block_active(
        candidate=cand, event=event, snap=snap, ict=ict,
    ) is True


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_must_take_blocks_chase_outside_window(mock_mny, mock_g, mock_enb):
    s = _settings()
    mock_enb.return_value = s
    mock_g.return_value = s
    mock_mny.return_value = s
    snap = _snap()
    event = _event(base_rel=63.0, premium=108.0)
    ict = _ict(63.0)
    cand = _cand(event, snap)
    assert top_explosion_must_take_active(
        candidate=cand, event=event, snap=snap, ict=ict,
    ) is False


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_must_take_rejects_otm(mock_mny, mock_g, mock_enb):
    s = _settings()
    mock_enb.return_value = s
    mock_g.return_value = s
    mock_mny.return_value = s
    snap = _snap(spot=24500.0)
    event = _event(strike=24050.0, premium=22.0, base_rel=30.0)
    ict = _ict(30.0)
    cand = _cand(event, snap)
    assert top_explosion_must_take_active(
        candidate=cand, event=event, snap=snap, ict=ict,
    ) is False


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_macd_and_live_confirm_skip_for_must_take(mock_mny, mock_g, mock_enb):
    s = _settings()
    mock_enb.return_value = s
    mock_g.return_value = s
    mock_mny.return_value = s
    snap = _snap()
    event = _event(v3=0.3, base_rel=28.0)
    ict = _ict(28.0)
    cand = _cand(event, snap)
    ok, _ = check_explosion_macd_alignment(
        Side.PUT, snap, event=event, candidate=cand,
    )
    assert ok is True
    live_blocked, _ = live_explosion_confirmation_blocked(
        event, ict=ict, snap=snap,
    )
    assert live_blocked is False


@patch("app.engines.entry_timing.get_settings")
def test_timing_block_still_fires_without_must_take_context(mock_s):
    mock_s.return_value = _settings(entry_timing_assessment_enabled=True)
    blocked, reason = timing_blocks_entry({
        "action": "block",
        "assessment": "COLD",
        "reasons": ["live_v3_cold"],
    })
    assert blocked is True
    assert "entry_timing_cold" in reason


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_trap_fade_chase_never_block_near_base_top(
    mock_mny, mock_ict_s, mock_g, mock_enb,
):
    """At the base, fake-trap / late-fade / extended-chase must not stop the fill."""
    from app.engines.explosion_entry_guards import (
        detect_fake_explosion_trap,
        extended_session_chase_blocked,
    )
    from app.engines.ict_breakout_monitor import late_fade_chase_blocked

    s = _settings()
    s.fake_explosion_trap_enabled = True
    s.ict_late_chase_block_enabled = True
    s.explosion_extended_chase_block_enabled = True
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.ict_late_chase_min_peak_pct = 75.0
    s.ict_late_chase_max_live_velocity_3s = 1.0
    mock_enb.return_value = s
    mock_g.return_value = s
    mock_ict_s.return_value = s
    mock_mny.return_value = s

    snap = _snap()
    # Day peak looks like a chase, but local base is still in the 10–45% pad.
    event = _event(v3=0.4, base_rel=28.0, premium=72.0)
    event.peak_move_pct = 120.0
    event.daily_move_pct = 120.0
    ict = _ict(28.0)
    cand = _cand(event, snap)

    trap_block, _, trap_meta = detect_fake_explosion_trap(
        cand, snap, ict=ict,
    )
    assert trap_block is False
    assert trap_meta.get("topMustTake") or trap_meta.get("eliteNeverBlock")

    late_blocked, _ = late_fade_chase_blocked(event, ict, snap=snap)
    assert late_blocked is False

    chase_blocked, _ = extended_session_chase_blocked(event, ict=ict)
    assert chase_blocked is False


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_must_take_uses_local_base_not_day_peak(mock_mny, mock_g, mock_enb):
    s = _settings()
    mock_enb.return_value = s
    mock_g.return_value = s
    mock_mny.return_value = s
    snap = _snap()
    event = _event(base_rel=28.0)
    event.peak_move_pct = 385.0
    event.daily_move_pct = 385.0
    ict = _ict(28.0)
    cand = _cand(event, snap)
    assert top_explosion_must_take_active(
        candidate=cand, event=event, snap=snap, ict=ict,
    ) is True
