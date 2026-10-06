"""Sep 9–17 legacy profile — ATM/ITM only, ₹18–350, no cheap OTM stack."""

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.best_trade_policy import (
    cheap_base_strike_eligible,
    cheap_base_strike_rank_bonus,
)
from app.engines.explosion_detector import ExplosionEvent, _shallow_otm_local_base_tradeable
from app.engines.moneyness import atm_itm_entry_allows
from app.engines.early_radar_pad_capture import otm_reversal_entry_allowed
from app.engines.sep917_legacy_profile import (
    cheap_otm_stack_disabled,
    sep917_legacy_profile_active,
    sep917_legacy_profile_summary,
    strict_atm_itm_execution,
)
from app.models.schemas import MarketPhase, Side, SymbolSnapshot


def test_legacy_profile_active_by_default():
    s = Settings()
    assert sep917_legacy_profile_active(s) is True
    assert cheap_otm_stack_disabled(s) is True
    assert strict_atm_itm_execution(s) is True


def test_legacy_premium_band_and_otm_flags():
    s = Settings()
    assert s.min_option_premium_inr == 18.0
    assert s.max_option_premium_inr == 350.0
    assert s.explosion_max_premium_inr == 350.0
    assert s.explosion_shallow_otm_entry_enabled is False
    assert s.explosion_shallow_otm_history_steps == 0
    assert s.best_trade_cheap_base_rank_priority_enabled is False
    assert s.near_base_session_capture_enabled is False
    assert s.put_slide_unlock_waive_expiry_otm is False
    assert s.ftv_elite_top_only_enabled is False
    assert s.top_moments_only_enabled is False


def test_legacy_summary_hud_shape():
    summary = sep917_legacy_profile_summary(Settings())
    assert summary["enabled"] is True
    assert summary["premiumBandInr"] == {"min": 18.0, "max": 350.0}
    assert summary["cheapBaseRankPriority"] is False
    assert summary["ftvEliteTopOnly"] is False
    assert summary["skipPrelossWorstDayPause"] is True


def test_cheap_base_rank_bonus_zero_under_legacy():
    s = Settings()
    candidate = MagicMock(mode="explosion", premium=45.0, symbol="NIFTY")
    snap = MagicMock(symbol="NIFTY")
    alert = {"localBaseMovePct": 12.0, "offLowMovePct": 8.0, "moneyness": "OTM"}
    assert cheap_base_strike_rank_bonus(candidate, alert=alert, settings=s) == 0.0
    assert cheap_base_strike_eligible(candidate, alert, snap, settings=s) is False


def test_shallow_otm_local_base_blocked_under_legacy():
    s = Settings()
    e = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=22800.0,
        premium=45.0,
        tier="ELITE",
        explosion_score=90.0,
        velocity_3s=1.0,
        velocity_9s=1.0,
        velocity_15s=1.0,
        volume_surge=2.0,
        reason="test",
        moneyness="OTM",
    )
    ict = MagicMock(flat_then_vertical=True, active=True, volume_awakening=False, base_armed=True)
    snap = MagicMock(spot=22850.0, atmStrike=22850.0)
    assert (
        _shallow_otm_local_base_tradeable(
            e, ict, structure_pad=8.0, snap=snap, settings=s,
        )
        is False
    )


def test_otm_reversal_disabled_under_sep917_strict_execution():
    s = Settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 29, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22850.0,
        atmStrike=22850.0,
    )
    alert = {
        "side": "CALL",
        "strike": 22950.0,
        "tier": "ELITE",
        "explosionScore": 95.0,
    }
    assert otm_reversal_entry_allowed(alert, snap) is False


def test_moneyness_rejects_otm_for_entry_when_shallow_disabled():
    assert Settings().explosion_shallow_otm_entry_enabled is False
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 29, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22850.0,
        atmStrike=22850.0,
    )
    allowed, reason, meta = atm_itm_entry_allows(Side.CALL, 23000.0, snap)
    assert allowed is False
    assert meta.get("moneyness") == "OTM"
    assert reason != "ok"
