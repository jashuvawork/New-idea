"""Session mode PF feedback + size-until-first-green."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.pretrade_validator import TradeRecord
from app.engines.session_mode_feedback import (
    cap_lots_until_first_green,
    compute_mode_stats,
    mode_session_rank_bonus,
    session_has_green_explosion,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.session_mode_feedback_enabled = True
    s.session_mode_feedback_min_trades = 2
    s.edge_session_pf_target = 2.5
    s.size_until_first_green_enabled = True
    s.size_until_first_green_lot_cap = 6
    s.size_until_first_green_modes_csv = "explosion,scalp"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_mode_stats_and_bonus_demotes_bleeding_explosion():
    trades = [
        TradeRecord("NIFTY", "CALL", -18000, mode="explosion", best_pnl_points=0),
        TradeRecord("NIFTY", "CALL", -34000, mode="quick_sideways", best_pnl_points=0),
        TradeRecord("NIFTY", "PUT", -5000, mode="quick_sideways", best_pnl_points=0),
        TradeRecord("NIFTY", "CALL", -2000, mode="explosion", best_pnl_points=0),
        TradeRecord("SENSEX", "CALL", 800, mode="explosion", best_pnl_points=20),
    ]
    stats = compute_mode_stats(trades)
    assert stats["explosion"].trades == 3
    assert stats["quick_sideways"].net_pnl_inr < 0
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        # quick bled hard → demote
        assert mode_session_rank_bonus("quick_sideways", stats) < 0
        # explosion mixed but net negative with losses → demote or small
        exp_bonus = mode_session_rank_bonus("explosion", stats)
        assert exp_bonus <= 0


def test_mode_bonus_promotes_winning_mode():
    trades = [
        TradeRecord("NIFTY", "CALL", 5000, mode="scalp", best_pnl_points=10),
        TradeRecord("NIFTY", "CALL", 8000, mode="scalp", best_pnl_points=15),
        TradeRecord("NIFTY", "PUT", -500, mode="scalp", best_pnl_points=2),
    ]
    stats = compute_mode_stats(trades)
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert mode_session_rank_bonus("scalp", stats) > 0


def test_size_until_first_green_caps_before_proof():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="a",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24300,
            entryPremium=50,
            currentPremium=45,
            lots=5,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=-2000,
            bestPnlPoints=0,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert session_has_green_explosion(state) is False
        assert cap_lots_until_first_green(49, state, mode="explosion") == 6


def test_size_until_first_green_allows_after_proof():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="b",
            symbol="SENSEX",
            side=Side.CALL,
            strike=78100,
            entryPremium=100,
            currentPremium=110,
            lots=2,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=800,
            bestPnlPoints=20,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert session_has_green_explosion(state) is True
        assert cap_lots_until_first_green(49, state, mode="explosion") == 49


def test_size_until_first_green_caps_scalp_before_proof():
    """Jul20 never-green oversize scalp (16 lots) must be capped to 6 before a green scalp."""
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="s1",
            symbol="NIFTY",
            side=Side.CALL,
            strike=23950,
            entryPremium=248,
            currentPremium=220,
            lots=11,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.SCALP,
            pnlInr=-21490,
            bestPnlPoints=0,
            entryContext={"selectionMode": "scalp"},
        )
    ]
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert cap_lots_until_first_green(16, state, mode="scalp") == 6


def test_size_until_first_green_allows_scalp_after_green():
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="s2",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24200,
            entryPremium=143,
            currentPremium=200,
            lots=8,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.SCALP,
            pnlInr=43705,
            bestPnlPoints=33,
            entryContext={"selectionMode": "scalp"},
        )
    ]
    with patch("app.engines.session_mode_feedback.get_settings", return_value=_settings()):
        assert cap_lots_until_first_green(20, state, mode="scalp") == 20


def test_same_strike_post_win_full_size_by_default():
    """Default: after a same-strike win, next vertical still gets full capital lots."""
    from app.engines.session_mode_feedback import cap_same_strike_explosion_reentry_after_win

    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="win8",
            symbol="SENSEX",
            side=Side.CALL,
            strike=77500,
            entryPremium=285,
            currentPremium=334,
            lots=6,
            openedAt=datetime.now(IST),
            closedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=5848,
            bestPnlPoints=54.7,
            entryContext={"selectionMode": "explosion", "explosionTier": "ELITE"},
        )
    ]
    s = _settings(
        explosion_post_win_same_strike_lot_cap_enabled=False,
        explosion_post_win_same_strike_lot_cap=6,
    )
    with patch("app.engines.session_mode_feedback.get_settings", return_value=s):
        lots, meta = cap_same_strike_explosion_reentry_after_win(
            29, state, symbol="SENSEX", side=Side.CALL, strike=77500,
        )
    assert lots == 29
    assert meta["applied"] is False


def test_same_strike_post_win_caps_when_enabled():
    """Optional protective mode: enable cap → next same-strike entry soft-capped."""
    from app.engines.session_mode_feedback import cap_same_strike_explosion_reentry_after_win

    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="win8",
            symbol="SENSEX",
            side=Side.CALL,
            strike=77500,
            entryPremium=285,
            currentPremium=334,
            lots=6,
            openedAt=datetime.now(IST),
            closedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=5848,
            bestPnlPoints=54.7,
            entryContext={"selectionMode": "explosion", "explosionTier": "ELITE"},
        )
    ]
    s = _settings(
        explosion_post_win_same_strike_lot_cap_enabled=True,
        explosion_post_win_same_strike_lot_cap=6,
    )
    with patch("app.engines.session_mode_feedback.get_settings", return_value=s):
        lots, meta = cap_same_strike_explosion_reentry_after_win(
            29, state, symbol="SENSEX", side=Side.CALL, strike=77500,
        )
    assert lots == 6
    assert meta["applied"] is True
    assert meta["priorPnlInr"] == 5848


def test_same_strike_post_win_ignores_other_strike():
    from app.engines.session_mode_feedback import cap_same_strike_explosion_reentry_after_win

    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="win8",
            symbol="SENSEX",
            side=Side.CALL,
            strike=77500,
            entryPremium=285,
            currentPremium=334,
            lots=6,
            openedAt=datetime.now(IST),
            closedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=5848,
            bestPnlPoints=54.7,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    s = _settings(
        explosion_post_win_same_strike_lot_cap_enabled=True,
        explosion_post_win_same_strike_lot_cap=6,
    )
    with patch("app.engines.session_mode_feedback.get_settings", return_value=s):
        lots, meta = cap_same_strike_explosion_reentry_after_win(
            29, state, symbol="SENSEX", side=Side.CALL, strike=77900,
        )
    assert lots == 29
    assert meta["applied"] is False


def test_same_strike_latest_loss_clears_prior_win_cap():
    from app.engines.session_mode_feedback import cap_same_strike_explosion_reentry_after_win
    from datetime import timedelta

    now = datetime.now(IST)
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="win8",
            symbol="SENSEX",
            side=Side.CALL,
            strike=77500,
            entryPremium=285,
            currentPremium=334,
            lots=6,
            openedAt=now - timedelta(minutes=20),
            closedAt=now - timedelta(minutes=15),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=5848,
            bestPnlPoints=54.7,
            entryContext={"selectionMode": "explosion"},
        ),
        PaperTrade(
            id="loss9",
            symbol="SENSEX",
            side=Side.CALL,
            strike=77500,
            entryPremium=320,
            currentPremium=300,
            lots=6,
            openedAt=now - timedelta(minutes=10),
            closedAt=now - timedelta(minutes=5),
            strategyType=StrategyType.EXPLOSIVE,
            pnlInr=-2000,
            bestPnlPoints=1.0,
            entryContext={"selectionMode": "explosion"},
        ),
    ]
    s = _settings(
        explosion_post_win_same_strike_lot_cap_enabled=True,
        explosion_post_win_same_strike_lot_cap=6,
    )
    with patch("app.engines.session_mode_feedback.get_settings", return_value=s):
        lots, meta = cap_same_strike_explosion_reentry_after_win(
            29, state, symbol="SENSEX", side=Side.CALL, strike=77500,
        )
    assert lots == 29
    assert meta.get("reason") == "latest_same_strike_not_a_win"


def _peak_captured_ftv(side: Side, *, closed_at: datetime) -> PaperTrade:
    return PaperTrade(
        id=f"nifty-24300-{side.value.lower()}",
        symbol="NIFTY",
        side=side,
        strike=24300,
        entryPremium=75.05,
        currentPremium=86.0,
        lots=1,
        openedAt=closed_at - timedelta(minutes=3),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_peak_capture",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=10.95 * 65,
        pnlPoints=10.95,
        bestPnlPoints=30.75,
        maxLtp=105.80,
        entryContext={
            "selectionMode": "explosion",
            "ictFlatThenVertical": True,
            "maxProfitCapture": True,
        },
    )


def _post_peak_guard_settings():
    return _settings(
        explosion_post_peak_reentry_guard_enabled=True,
        explosion_post_peak_reentry_lookback_seconds=1800,
        explosion_post_peak_reentry_min_peak_points=20.0,
        explosion_post_peak_reentry_near_peak_pct=15.0,
        explosion_post_peak_reentry_base_samples=3,
        explosion_post_peak_reentry_base_span_seconds=6.0,
        explosion_post_peak_reentry_min_reacceleration_pct=8.0,
        explosion_post_peak_reentry_min_velocity_3s=1.5,
    )


def test_peak_captured_ftv_blocks_exhausted_high_reentry_for_ce_and_pe():
    from app.engines.session_mode_feedback import exhausted_ftv_reentry_blocked

    closed_at = datetime.now(IST) - timedelta(seconds=20)
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=_post_peak_guard_settings(),
    ):
        for side in (Side.CALL, Side.PUT):
            state = AutoTraderState(
                closedPaperTrades=[_peak_captured_ftv(side, closed_at=closed_at)]
            )
            blocked, meta = exhausted_ftv_reentry_blocked(
                state,
                symbol="NIFTY",
                side=side,
                strike=24300,
                premium=108.02,
                velocity_3s=3.0,
            )
            assert blocked is True
            assert meta["nearExhaustedPeak"] is True
            assert meta["newBaseReacceleration"] is False


def test_peak_captured_ftv_allows_new_base_and_reacceleration_for_ce_and_pe():
    import app.engines.explosion_detector as detector
    from app.engines.session_mode_feedback import exhausted_ftv_reentry_blocked

    closed_at = datetime.now(IST) - timedelta(seconds=30)
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=_post_peak_guard_settings(),
    ):
        for side in (Side.CALL, Side.PUT):
            detector.reset_detector_state_for_tests()
            key = detector._open_key("NIFTY", 24300, side)
            detector._record_local_base(key, closed_at + timedelta(seconds=3), 82.0)
            detector._record_local_base(key, closed_at + timedelta(seconds=7), 83.0)
            detector._record_local_base(key, closed_at + timedelta(seconds=11), 82.5)
            detector._record_local_base(key, closed_at + timedelta(seconds=15), 108.02)
            state = AutoTraderState(
                closedPaperTrades=[_peak_captured_ftv(side, closed_at=closed_at)]
            )

            blocked, meta = exhausted_ftv_reentry_blocked(
                state,
                symbol="NIFTY",
                side=side,
                strike=24300,
                premium=108.02,
                velocity_3s=4.0,
            )

            assert blocked is False
            assert meta["newBaseReacceleration"] is True
            assert meta["baseSamples"] == 3
            assert meta["baseSpanSeconds"] == 8.0
