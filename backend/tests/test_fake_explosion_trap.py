"""Fake explosion trap — Jul20 NIFTY 24300 CE FOMO / never-green path."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import (
    cap_fake_explosion_trap_lots,
    detect_fake_explosion_trap,
)
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.engines.pretrade_validator import TradeRecord
from app.models.schemas import MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _confirmed_ict(move: float) -> ICTBreakoutSignal:
    """Confirmed flat→vertical structure — what a genuine base rip supplies live.

    detect_fake_explosion_trap now hard-blocks chop+ELITE with NO ICT structure
    (Jul23 displacement-spike fix). Real base rips carry structure, so the trap
    tests must pass it in; without it every case looks structure-less.
    """
    return ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=80.0,
        reasons=["flat_then_vertical"],
        flat_then_vertical=True,
        volume_awakening=True,
        session_move_pct=move,
        base_relative_move_pct=move,
    )


def _settings(**overrides):
    s = MagicMock()
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.explosion_early_window_max_move_pct = 55.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.explosion_local_base_recent_window_enabled = False
    s.explosion_local_base_chase_max_move_pct = 65.0
    s.fake_explosion_trap_max_premium_mom_pct = 0.15
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_block_worst_midday_chop = True
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.fake_explosion_trap_post_win_lot_cap = 8
    s.fake_explosion_trap_post_win_max_pnl_inr = 3000.0
    s.fake_explosion_trap_post_win_lookback = 1
    s.fake_explosion_trap_post_win_velocity_block_enabled = True
    s.fake_explosion_trap_post_win_min_velocity_3s = 0.0
    s.fake_explosion_trap_post_win_midday_min_velocity_3s = 1.0
    s.fake_explosion_trap_post_win_armed_base_bypass_enabled = False
    s.fake_explosion_trap_post_win_require_top_confidence = True
    s.fake_explosion_trap_post_win_hc_min_velocity_3s = 2.0
    s.high_conviction_sizing_enabled = True
    s.high_conviction_min_score = 90.0
    s.high_conviction_min_chart_confidence = 56.9
    s.high_conviction_min_velocity_3s = 2.0
    s.missed_explosion_promote_min_move_pct = 28.0
    s.missed_explosion_promote_max_move_pct = 55.0
    s.fake_explosion_trap_psychology_escalate = True
    s.fake_explosion_trap_skip_soft_cut_base_window = True
    s.fake_explosion_trap_skip_soft_cut_near_otm = True
    s.moneyness_local_base_max_otm_steps = 3
    s.fake_explosion_trap_midday_require_structure = True
    s.moneyness_explosion_prefer = "ATM"
    s.trade_moneyness_mode = "AUTO"
    s.midday_chop_start_hour = 11
    s.midday_chop_start_minute = 30
    s.midday_chop_end_hour = 13
    s.midday_chop_end_minute = 30
    s.nifty_strike_step = 50
    s.sensex_strike_step = 100
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(
    daily: float = 29.8,
    *,
    v3: float = 13.1,
    tier: str = "ELITE",
    strike: float = 24300.0,
) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=strike,
        premium=58.0,
        velocity_3s=v3,
        velocity_9s=v3,
        velocity_15s=v3,
        volume_surge=2.5,
        explosion_score=100.0,
        tier=tier,
        reason="flat_then_vertical",
        daily_move_pct=daily,
        peak_move_pct=daily,
    )


def _snap(*, regime: Regime = Regime.RANGE_BOUND, or_pos: str = "INSIDE") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=regime,
        spot=24244.75,
        atmStrike=24200.0,
        tradeQualityScore=49,
        spotChart=SpotChart(
            direction="BULLISH",
            timeframe="5m",
            barCount=51,
            momentum5Pct=0.133,
            momentum15Pct=0.266,
            trendStrength=70.6,
            emaBias="NEUTRAL",
            candleBias="NEUTRAL",
            orPosition=or_pos,
            rsi=62.94,
            macdBias="BULLISH",
        ),
    )


def _candidate(event: ExplosionEvent, snap: SymbolSnapshot, **overrides) -> MagicMock:
    cand = MagicMock()
    cand.mode = "explosion"
    cand.side = event.side
    cand.strike = event.strike
    cand.score = overrides.get("score", 165.0)
    cand.tier = event.tier
    cand.explosion_event = event
    cand.snap = snap
    cand.pretrade_meta = overrides.get("pretrade_meta", {})
    return cand


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_blocks_jul20_otm_inside_or_chop_elite(mock_money_settings, mock_settings):
    """RANGE + ELITE + OTM inside OR → hard block (Jul20 24300 CE)."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap()
    cand = _candidate(_event(), snap)
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert blocked is True
    assert meta.get("action") == "block"
    assert "otm_inside_or" in meta.get("conflictFlags", [])
    assert "fake_explosion_trap" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_blocks_premium_flat_extension(mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    # ATM strike — avoid OTM path; premium flat + extension should still block.
    snap = _snap(or_pos="ABOVE")
    cand = _candidate(_event(strike=24200.0), snap)
    prem = {"direction": "NEUTRAL", "momentum3Pct": 0.0, "momentum5Pct": 0.0}
    blocked, reason, meta = detect_fake_explosion_trap(
        cand, snap, premium_chart=prem,
    )
    assert blocked is True
    assert "premium_flat" in meta.get("conflictFlags", [])
    assert "premium_flat" in reason or meta.get("action") == "block"


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_fresh_local_pad_is_not_misclassified_as_session_extension(
    mock_money_settings, mock_settings, side,
):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="ABOVE")
    event = _event(daily=67.0, strike=24200.0)
    event.side = side
    cand = _candidate(event, snap)
    prem = {"direction": "NEUTRAL", "momentum3Pct": 0.0, "momentum5Pct": 0.0}

    with patch(
        "app.engines.explosion_entry_guards._midday_chop_active",
        return_value=False,
    ):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand,
            snap,
            premium_chart=prem,
            ict=_confirmed_ict(20.0),
        )

    assert blocked is False
    assert reason != "fake_explosion_trap_premium_flat_extension"
    assert "session_extended" not in meta.get("conflictFlags", [])
    assert meta["localBaseMovePct"] == 20.0


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_small_win_cuts_size(mock_collect, mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    # Trend day + ATM breakout OR — no hard block, but post-win clamps.
    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="ABOVE")
    cand = _candidate(_event(daily=12.0, v3=4.0, tier="EXPLODING", strike=24200.0), snap)

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="SENSEX",
                side="CALL",
                pnl_inr=445.6,
                exit_reason="explosion_trail_sl",
                strike=78300.0,
            )
        ],
    ), patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(),
        )
    assert blocked is False
    assert meta.get("action") == "cut_size"
    assert meta.get("lotCap") == 8
    assert meta.get("psychologyEscalate") == "FOMO"
    assert cap_fake_explosion_trap_lots(49, meta) == 8


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_win_blocks_negative_v3_midday(mock_collect, mock_money_settings, mock_settings):
    """Aug28 NIFTY 24050 PE — post-win micro-pullback v3=-0.38 must hard-block."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="BELOW")
    cand = _candidate(
        _event(daily=22.0, v3=-0.38, tier="EXPLODING", strike=24050.0),
        snap,
    )

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side="PUT",
                pnl_inr=2346.27,
                exit_reason="explosion_stage_trail",
                strike=24200.0,
            )
        ],
    ), patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(), ict=_confirmed_ict(22.0),
        )

    assert blocked is True
    assert reason == "fake_explosion_trap_post_win_cold_velocity"
    assert meta.get("action") == "block"
    assert meta.get("postWinVelocityBlock") is True
    assert meta.get("requiredMinVelocity3s") == 1.0


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_win_armed_base_does_not_bypass_cold_velocity(
    mock_collect, mock_money_settings, mock_settings,
):
    """Aug28 12:55 — ictBaseArmed must not skip post-win cold-velocity hard block."""
    cfg = _settings(fake_explosion_trap_post_win_armed_base_bypass_enabled=False)
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="BELOW")
    cand = _candidate(
        _event(daily=8.0, v3=-0.38, tier="EXPLODING", strike=24050.0),
        snap,
    )
    cand.side = Side.PUT
    cand.alert = {
        "ictBaseArmed": True,
        "ictArmedBaseLaunch": False,
        "localBaseMovePct": 7.93,
    }

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side="PUT",
                pnl_inr=2346.27,
                exit_reason="explosion_stage_trail",
                strike=24200.0,
            )
        ],
    ), patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(), ict=_confirmed_ict(8.0),
        )

    assert blocked is True
    assert reason == "fake_explosion_trap_post_win_cold_velocity"


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_win_blocks_without_top_confidence(mock_collect, mock_money_settings, mock_settings):
    """Aug28 24050 — post-win probe without topRank must hard-block (not 8-lot cut)."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="BELOW")
    cand = _candidate(
        _event(daily=22.0, v3=1.2, tier="EXPLODING", strike=24050.0),
        snap,
        score=210.84,
        pretrade_meta={
            "causalRanking": {
                "topRankEligible": False,
                "fullSleeveEligible": False,
                "grade": "A",
            },
        },
    )

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side="PUT",
                pnl_inr=2346.27,
                exit_reason="explosion_stage_trail",
                strike=24200.0,
            )
        ],
    ), patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(), ict=_confirmed_ict(22.0),
        )

    assert blocked is True
    assert reason == "fake_explosion_trap_post_win_not_top_confidence"
    assert meta.get("postWinTopConfidenceBlock") is True


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_win_weak_positive_v3_non_midday_blocks_without_top_rank(
    mock_collect, mock_money_settings, mock_settings,
):
    """Off-midday post-win with weak v3 and no topRank must block — not 8-lot probe."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="ABOVE")
    cand = _candidate(_event(daily=12.0, v3=0.6, tier="EXPLODING", strike=24200.0), snap)

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side="PUT",
                pnl_inr=500.0,
                exit_reason="explosion_trail_sl",
                strike=24200.0,
            )
        ],
    ), patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(),
        )

    assert blocked is True
    assert reason == "fake_explosion_trap_post_win_not_top_confidence"


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.collect_session_trades", create=True)
def test_post_win_top_rank_still_soft_caps(mock_collect, mock_money_settings, mock_settings):
    """Top-rank post-win re-entry with warm v3 keeps the 8-lot soft cap."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg

    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="ABOVE")
    cand = _candidate(
        _event(daily=12.0, v3=0.6, tier="EXPLODING", strike=24200.0),
        snap,
        pretrade_meta={"causalRanking": {"topRankEligible": True}},
    )

    with patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[
            TradeRecord(
                symbol="NIFTY",
                side="PUT",
                pnl_inr=500.0,
                exit_reason="explosion_trail_sl",
                strike=24200.0,
            )
        ],
    ), patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(),
        )

    assert blocked is False
    assert meta.get("action") == "cut_size"
    assert meta.get("lotCap") == 8


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_chop_elite_soft_cut_without_otm_trap(mock_money_settings, mock_settings):
    """Chop + ELITE on ATM with OR breakout → cut size, not necessarily block."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="ABOVE")
    cand = _candidate(_event(daily=18.0, strike=24200.0), snap)
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap, ict=_confirmed_ict(18.0))
    assert blocked is False
    assert meta.get("action") == "cut_size"
    assert meta.get("lotCap") == 6
    assert meta.get("psychologyEscalate") in ("OVERCONFIDENCE", "FOMO", None)
    assert cap_fake_explosion_trap_lots(49, meta) == 6


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_clean_trend_atm_not_trapped(mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(regime=Regime.TREND_EXPANSION, or_pos="ABOVE")
    # Strong chart so _regime_chopish is false even without RANGE
    snap.spotChart.momentum5Pct = 0.6
    snap.spotChart.trendStrength = 80.0
    cand = _candidate(_event(daily=18.0, v3=5.0, tier="EXPLODING", strike=24200.0), snap)
    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert blocked is False
    assert meta.get("action") not in ("block", "cut_size")
    assert cap_fake_explosion_trap_lots(20, meta) == 20


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_jul15_atm_base_window_not_hard_blocked(mock_money_settings, mock_settings):
    """RANGE + ELITE + ATM + 32–45% move = Jul15 keep — no hard block, no soft lot-cap."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="BELOW")
    # True ATM (24200) — 24250 is 1-step OTM and must still be soft-cut capable.
    cand = _candidate(_event(daily=32.0, v3=7.9, strike=24200.0), snap)
    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=False):
        blocked, reason, meta = detect_fake_explosion_trap(cand, snap, ict=_confirmed_ict(32.0))
    assert blocked is False
    assert meta.get("action") not in ("block", "cut_size")
    assert "base_window" in meta.get("conflictFlags", [])
    assert "session_extended" not in meta.get("conflictFlags", [])
    assert cap_fake_explosion_trap_lots(49, meta) == 49


@patch("app.engines.elite_never_block.elite_never_block_active", return_value=False)
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_jul31_near_otm_base_window_full_lots(
    mock_money_settings, mock_settings, _mock_enb,
):
    """Jul31 NIFTY 24500 CE — 2-step OTM + local base in 28–55% → no 6-lot soft cut."""
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="ABOVE")
    snap.atmStrike = 24400.0
    snap.spot = 24420.0
    cand = _candidate(
        _event(daily=29.9, v3=4.5, tier="EXPLODING", strike=24500.0),
        snap,
    )
    ict = _confirmed_ict(29.9)
    ict.local_swing_base = True
    ict.base_premium = 31.9
    ict.base_relative_move_pct = 28.7
    ict.volume_awakening = True
    ict.displacement = True
    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True):
        blocked, reason, meta = detect_fake_explosion_trap(cand, snap, ict=ict)
    assert blocked is False
    assert meta.get("action") != "cut_size", meta
    assert meta.get("baseWindowFullLots") is True
    assert cap_fake_explosion_trap_lots(64, meta, bypass_soft_cap=False) == 64
    assert cap_fake_explosion_trap_lots(
        64, {"fakeExplosionTrap": True, "action": "cut_size", "lotCap": 6},
        bypass_soft_cap=True,
    ) == 64


def test_high_conviction_bypasses_soft_trap_cap():
    meta = {"fakeExplosionTrap": True, "action": "cut_size", "lotCap": 6}
    assert cap_fake_explosion_trap_lots(40, meta, bypass_soft_cap=True) == 40
    assert cap_fake_explosion_trap_lots(40, meta, bypass_soft_cap=False) == 6
    assert cap_fake_explosion_trap_lots(40, {"fakeExplosionTrap": True, "action": "block"}, bypass_soft_cap=True) == 0


@patch("app.engines.explosion_entry_guards.get_settings")
def test_chop_cut_size_honors_soft_cap_despite_bypass(mock_settings):
    """Aug6: chop+elite cut_size(6) must not restore 27 via baseWindowFullLots bypass."""
    mock_settings.return_value = _settings()
    meta = {
        "fakeExplosionTrap": True,
        "action": "cut_size",
        "lotCap": 6,
        "chopRegime": True,
        "middayChop": True,
        "eliteHot": True,
        "conflictFlags": ["chop_regime", "midday_chop", "elite_hot"],
        "conflictCount": 3,
    }
    assert cap_fake_explosion_trap_lots(27, meta, bypass_soft_cap=True) == 6


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_extended_chase_still_flags_session_extended(mock_money_settings, mock_settings):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="ABOVE")
    cand = _candidate(_event(daily=80.0, strike=24200.0), snap)
    blocked, reason, meta = detect_fake_explosion_trap(cand, snap)
    assert "session_extended" in meta.get("conflictFlags", [])


def test_cap_block_zeros_lots():
    assert cap_fake_explosion_trap_lots(49, {"fakeExplosionTrap": True, "action": "block"}) == 0


@patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True)
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.get_settings")
def test_worst_midday_chop_elite_hard_blocks(
    mock_money_settings, mock_settings, _midday,
):
    """Aug18: EXPIRY WORST midday + EXPLODING must hard-block, not soft-cap to 6."""
    from app.models.schemas import Breadth

    cfg = _settings()
    mock_settings.return_value = cfg
    mock_money_settings.return_value = cfg
    snap = _snap(or_pos="BELOW")
    snap.breadth = Breadth(bias="BEARISH", score=45.0, aligned=True)
    # Armed-base style: early pad, not session-extended.
    event = _event(daily=18.0, v3=2.4, tier="EXPLODING", strike=24250.0)
    cand = _candidate(event, snap)
    state = MagicMock()
    state.dayMode = "EXPIRY WORST"
    state.dailyStrategy = {"dayMode": "EXPIRY WORST", "dayType": "WORST"}
    ict = _confirmed_ict(5.7)
    blocked, reason, meta = detect_fake_explosion_trap(
        cand, snap, state=state, ict=ict,
    )
    assert blocked is True
    assert reason == "fake_explosion_trap_worst_midday_chop"
    assert meta.get("action") == "block"
    assert "midday_chop" in meta.get("conflictFlags", [])
    assert "chop_regime" in meta.get("conflictFlags", [])
    assert "elite_hot" in meta.get("conflictFlags", [])


def test_trap_soft_cap_honor_bypassed_for_index_confirmed_ftv():
    from app.engines.explosion_entry_guards import _trap_soft_cap_must_honor

    meta = {
        "action": "cut_size",
        "chopRegime": True,
        "eliteHot": True,
        "indexConfirmedFtv": True,
        "localBaseStructure": True,
        "lotCap": 6,
    }
    assert _trap_soft_cap_must_honor(meta) is False
    assert cap_fake_explosion_trap_lots(17, meta, bypass_soft_cap=True) == 17
