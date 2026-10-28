"""Same-strike reentry after a win, only while the premium is rising off a new base."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.session_mode_feedback import (
    fresh_base_funnel_fields,
    fresh_base_pretrade_meta_from_alert,
    same_strike_post_win_fresh_base_reentry,
)
from app.engines.trade_selector import _explosion_candidates
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _win(*, side: Side = Side.PUT, strike: float = 74200.0, symbol: str = "SENSEX") -> PaperTrade:
    closed_at = datetime.now(IST) - timedelta(minutes=30)
    return PaperTrade(
        id="oct21-74200-put-win",
        symbol=symbol,
        side=side,
        strike=strike,
        entryPremium=297.0,
        currentPremium=315.0,
        lots=17,
        openedAt=closed_at - timedelta(minutes=8),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_stage_trail",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=18000.0,
        entryContext={"selectionMode": "explosion"},
    )


def _state(*trades: PaperTrade, open_trades: list[PaperTrade] | None = None) -> AutoTraderState:
    return AutoTraderState(
        closedPaperTrades=list(trades),
        openPaperTrades=list(open_trades or []),
    )


def _call(**kwargs):
    settings = kwargs.pop("settings", Settings())
    with patch("app.engines.session_mode_feedback.get_settings", return_value=settings):
        return same_strike_post_win_fresh_base_reentry(**kwargs)


def test_alert_stamp_flows_to_pretrade_and_funnel_meta():
    alert = {
        "sameStrikePostWinFreshBase": True,
        "sameStrikePostWinFreshBaseMeta": {
            "reason": "fresh_base_reentry",
            "priorWinTradeId": "win-1",
        },
    }
    pre = fresh_base_pretrade_meta_from_alert(alert)
    assert pre["sameStrikePostWinFreshBase"] is True
    funnel = fresh_base_funnel_fields(pretrade_meta=pre)
    assert funnel["freshBaseReentryReason"] == "fresh_base_reentry"
    assert funnel["priorWinTradeId"] == "win-1"


def test_fresh_base_reentry_allows_rising_pad_after_same_strike_win():
    proven = {
        "newBaseReacceleration": True,
        "basePremium": 280.0,
        "reaccelerationPct": 14.3,
        "velocity3s": 2.1,
    }
    with patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(True, proven),
    ):
        ok, meta = _call(
            state=_state(_win()),
            symbol="SENSEX",
            side=Side.PUT,
            strike=74200.0,
            premium=320.0,
            velocity_3s=2.1,
            alert={"premiumMomentum5Pct": 1.4},
        )
    assert ok is True
    assert meta["reason"] == "fresh_base_reentry"
    assert meta["sameStrikePostWinFreshBase"] is True


def test_fresh_base_reentry_blocks_fading_print():
    ok, meta = _call(
        state=_state(_win()),
        symbol="SENSEX",
        side=Side.PUT,
        strike=74200.0,
        premium=320.0,
        velocity_3s=2.1,
        alert={"premiumMomentum5Pct": -0.8},
    )
    assert ok is False
    assert meta["reason"] == "premium_fading"


def test_fresh_base_reentry_blocks_flat_velocity():
    ok, meta = _call(
        state=_state(_win()),
        symbol="SENSEX",
        side=Side.PUT,
        strike=74200.0,
        premium=320.0,
        velocity_3s=0.0,
        alert={},
    )
    assert ok is False
    assert meta["reason"] == "premium_fading"


def test_fresh_base_reentry_blocks_lift_already_past_the_pad():
    proven = {"newBaseReacceleration": True, "reaccelerationPct": 43.0}
    with patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(True, proven),
    ):
        ok, meta = _call(
            state=_state(_win()),
            symbol="SENSEX",
            side=Side.PUT,
            strike=74200.0,
            premium=400.0,
            velocity_3s=2.4,
            alert={"premiumMomentum5Pct": 3.0},
        )
    assert ok is False
    assert meta["reason"] == "above_fresh_base_pad"


def test_fresh_base_reentry_blocks_hot_velocity_without_a_new_base():
    with patch(
        "app.engines.explosion_detector.post_close_base_reacceleration",
        return_value=(False, {"newBaseReacceleration": False}),
    ):
        ok, meta = _call(
            state=_state(_win()),
            symbol="SENSEX",
            side=Side.PUT,
            strike=74200.0,
            premium=318.0,
            velocity_3s=2.4,
            alert={"premiumMomentum5Pct": 1.0},
        )
    assert ok is False
    assert meta["reason"] == "no_fresh_base"


def test_fresh_base_reentry_blocks_a_second_leg():
    win = _win()
    opened = win.closedAt + timedelta(minutes=4)
    second = PaperTrade(
        id="oct21-74200-put-reentry",
        symbol="SENSEX",
        side=Side.PUT,
        strike=74200.0,
        entryPremium=320.0,
        currentPremium=330.0,
        lots=4,
        openedAt=opened,
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"selectionMode": "explosion"},
    )
    ok, meta = _call(
        state=_state(win, open_trades=[second]),
        symbol="SENSEX",
        side=Side.PUT,
        strike=74200.0,
        premium=340.0,
        velocity_3s=2.2,
        alert={"premiumMomentum5Pct": 1.0},
    )
    assert ok is False
    assert meta["reason"] == "reentry_already_taken"


def test_fresh_base_reentry_ignores_the_other_side():
    ok, meta = _call(
        state=_state(_win()),
        symbol="SENSEX",
        side=Side.CALL,
        strike=74300.0,
        premium=180.0,
        velocity_3s=2.5,
        alert={"premiumMomentum5Pct": 1.0},
    )
    assert ok is False
    assert meta["reason"] == "no_same_strike_win"


def test_selector_keeps_non_tradeable_alert_on_fresh_base_reentry():
    alert = {
        "id": "74200-put",
        "tradeable": False,
        "tier": "ELITE",
        "side": "PUT",
        "strike": 74200,
        "premium": 320.0,
        "velocity3s": 2.1,
        "explosionScore": 96.0,
    }
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=74180.0,
        atmStrike=74200.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=70.0,
        breadth=Breadth(bias="BEARISH", score=70, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.2,
            trendStrength=70,
            emaBias="BEARISH",
            candleBias="BEARISH",
            macdBias="BEARISH",
        ),
        explosionAlerts=[alert],
        suggestedTrades=[],
    )
    state = SimpleNamespace(
        openPaperTrades=[],
        closedPaperTrades=[_win()],
        calibrationBlocks={"CALL": False, "PUT": False},
    )
    seen: dict[str, bool] = {}

    def _band(*_args, **_kwargs):
        seen["band"] = True
        return False

    with (
        patch("app.engines.trade_selector.premium_in_band", side_effect=_band),
        patch(
            "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
            return_value=(True, {"reason": "fresh_base_reentry"}),
        ),
    ):
        out = _explosion_candidates("SENSEX", snap, state, Settings())
    assert seen.get("band") is True
    assert out == []
