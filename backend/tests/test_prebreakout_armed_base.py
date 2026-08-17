"""Causal sticky pre-breakout base replay for the Aug 17 NIFTY 24300 CE shape."""

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines import explosion_detector
from app.engines.auto_trader import _top_rank_full_budget_lots_allowed
from app.engines.capital_allocator import RankedAllocation
from app.engines.explosion_detector import (
    _armed_base_anchors,
    _armed_base_reset_after,
    _local_base_hist,
    _open_key,
    armed_base_anchor,
    consume_armed_base_anchor,
    event_to_dict,
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.engines.session_mode_feedback import exhausted_ftv_reentry_blocked
from app.engines.trade_selector import find_best_entry
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


def _snapshot(
    side: Side,
    *,
    spot: float = 24300.0,
    atm: float = 24300.0,
) -> SymbolSnapshot:
    adverse = -0.08 if side == Side.CALL else 0.08
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=70.0,
        spot=spot,
        atmStrike=atm,
        regime=Regime.TREND_EXPANSION,
        breadth=Breadth(
            bias="BULLISH" if side == Side.CALL else "BEARISH",
            score=70.0,
            aligned=True,
        ),
        spotChart=SpotChart(
            direction="BEARISH" if side == Side.CALL else "BULLISH",
            momentum5Pct=adverse,
            momentum10Pct=adverse * 0.6,
            momentum15Pct=adverse * 0.1,
        ),
    )


def _scanner(side: Side, settings: Settings):
    current = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    option_key = "call_options" if side == Side.CALL else "put_options"

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

    def advance(seconds: float) -> None:
        nonlocal current
        current += timedelta(seconds=seconds)

    def scan(premium: float, volume: float = 27_127_300, *, spot: float = 24300.0):
        events = scan_chain_explosions(
            "NIFTY",
            [{
                "strike_price": 24300.0,
                option_key: {"ltp": premium, "volume": volume},
            }],
            spot=spot,
            atm=24300.0,
        )
        advance(3)
        matches = [
            event for event in events
            if event.side == side and event.strike == 24300.0
        ]
        return event_to_dict(matches[0]) if matches else None

    return _Clock, scan, advance


def _arm_base(scan) -> dict:
    armed = None
    for premium in (53.1, 52.9, 53.0, 52.8, 53.1, 52.9, 53.0, 52.8):
        radar = scan(premium)
        if radar and radar.get("ictBaseArmed"):
            armed = radar
    assert armed is not None
    return armed


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_aug17_base_arms_then_launches_symmetrically_near_57(_open, side):
    settings = Settings()
    clock, scan, _advance = _scanner(side, settings)
    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", clock),
    ):
        armed = _arm_base(scan)
        assert armed["ictBasePremium"] == pytest.approx(52.8)
        assert armed["ictArmedBaseSamples"] >= 6
        assert armed["ictArmedBaseSpanSeconds"] >= 15
        assert armed["tradeable"] is False

        assert not scan(53.8, 0).get("ictArmedBaseLaunch")
        assert not scan(54.5, 0).get("ictArmedBaseLaunch")
        assert not scan(55.2, 0).get("ictArmedBaseLaunch")
        launch = scan(57.0, 0)

        assert launch["ictBaseArmed"] is True
        assert launch["ictArmedBaseLaunch"] is True
        assert launch["ictFirstLift"] is False
        assert launch["tradeable"] is True
        assert launch["momentType"] == "armed_base_launch"
        assert launch["ictBaseRelativeMovePct"] == pytest.approx(8.0, abs=0.2)
        assert launch["volume"] == 27_127_300
        ready, reason = first_lift_entry_readiness(
            snap=_snapshot(side),
            alert=launch,
        )
        assert ready is True
        assert reason == "armed_base_option_led_ready"


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_aug17_real_selector_selects_armed_launch_only_at_57_without_full_budget(
    _open, side,
):
    settings = Settings(
        best_trades_only_enabled=False,
        edge_engine_enabled=False,
    )
    clock, scan, _advance = _scanner(side, settings)
    snap = _snapshot(side)
    # Reproduce the lagging bearish 5m chart from the live ₹57 launch. The stronger
    # ATM premium/base proof must pass the real selector without chart alignment.
    state = AutoTraderState()

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.trade_selector.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", clock),
    ):
        armed = _arm_base(scan)
        snap.explosionAlerts = [armed]
        assert find_best_entry({"NIFTY": snap}, state) is None

        for premium in (53.8, 54.5, 55.2):
            scan(premium, 0)
        launch = scan(57.0, 0)
        snap.explosionAlerts = [launch]
        selected = find_best_entry({"NIFTY": snap}, state)

    assert launch["ictArmedBaseLaunch"] is True
    assert launch["ictFirstLift"] is False
    assert selected is not None
    assert selected.mode == "explosion"
    assert selected.side == side
    assert selected.strike == 24300.0
    assert selected.premium == pytest.approx(57.0)
    assert selected.alert["ictArmedBaseLaunch"] is True
    assert _top_rank_full_budget_lots_allowed(
        enabled=True,
        allocation=RankedAllocation(
            rank=1,
            budgetInr=100_000.0,
            remainingBeforeInr=100_000.0,
            cashReserveInr=0.0,
            capitalBaseInr=100_000.0,
            committedInr=0.0,
            weight=1.0,
        ),
        strict_first_lift=bool(selected.alert.get("ictFirstLift")),
        top_explosion_max=True,
        faded_rip=False,
        post_win_capped=False,
    ) is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_weak_armed_launch_cannot_bypass_adverse_chart(_open, side):
    settings = Settings(
        best_trades_only_enabled=False,
        edge_engine_enabled=False,
    )
    clock, scan, _advance = _scanner(side, settings)
    snap = _snapshot(side)
    state = AutoTraderState()

    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.trade_selector.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", clock),
    ):
        _arm_base(scan)
        for premium in (53.8, 54.5, 55.2):
            scan(premium, 0)
        launch = scan(57.0, 0)
        launch["volume"] = 0
        launch["absoluteVolume"] = 0
        launch["orderflowConfirmed"] = False
        launch["optionCvdBuying"] = False
        snap.explosionAlerts = [launch]
        ready, reason = first_lift_entry_readiness(snap=snap, alert=launch)
        selected = find_best_entry({"NIFTY": snap}, state)

    assert launch["ictArmedBaseLaunch"] is True
    assert ready is False
    assert reason.startswith("armed_base_orderflow_below_")
    assert selected is None


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_aug17_sticky_denominator_survives_rest_ws_observations(_open):
    settings = Settings()
    clock, scan, _advance = _scanner(Side.CALL, settings)
    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", clock),
    ):
        _arm_base(scan)
        observations = []
        for premium, volume in (
            (57.0, 0),
            (59.80, 27_127_300),
            (64.65, 0),
            (63.50, 27_127_300),
        ):
            radar = scan(premium, volume)
            assert radar is not None
            observations.append(radar)

    assert {row["ictBasePremium"] for row in observations} == {52.8}
    assert [row["ictBaseRelativeMovePct"] for row in observations] == pytest.approx(
        [8.0, 13.3, 22.4, 20.3],
        abs=0.2,
    )


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_armed_base_without_launch_velocity_is_not_tradeable(_open):
    settings = Settings()
    clock, scan, _advance = _scanner(Side.CALL, settings)
    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", clock),
    ):
        _arm_base(scan)
        weak = None
        for premium in (53.3, 53.6, 53.9, 54.2, 54.5, 54.8, 55.1, 55.4):
            weak = scan(premium, 0)
        assert weak is not None
        ready, _reason = first_lift_entry_readiness(
            snap=_snapshot(Side.CALL),
            alert=weak,
        )

    assert weak["ictBaseArmed"] is True
    assert weak["ictArmedBaseLaunch"] is False
    assert weak["tradeable"] is False
    assert ready is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
def test_otm_armed_base_launch_never_becomes_entry_ready(_open):
    settings = Settings(explosion_shallow_otm_history_steps=1)
    clock, scan, _advance = _scanner(Side.CALL, settings)
    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
        patch.object(explosion_detector, "datetime", clock),
    ):
        # 24300 CE is one-step OTM while spot/ATM are 24200, so history is retained.
        for premium in (53.1, 52.9, 53.0, 52.8, 53.1, 52.9, 53.0, 52.8):
            scan(premium, spot=24200.0)
        for premium in (53.8, 54.5, 55.2):
            scan(premium, 0, spot=24200.0)
        launch = scan(57.0, 0, spot=24200.0)
        assert launch is not None and launch["ictArmedBaseLaunch"] is True
        ready, reason = first_lift_entry_readiness(
            snap=_snapshot(Side.CALL, spot=24200.0, atm=24200.0),
            alert=launch,
        )

    assert ready is False
    assert reason == "armed_base_requires_atm_itm_otm"


def test_expired_contract_base_rearms_from_genuinely_new_samples():
    settings = Settings(ict_armed_base_horizon_seconds=60.0)
    side = Side.PUT
    key = _open_key("NIFTY", 24300.0, side)
    start = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(start + timedelta(seconds=i * 3), 52.8 + (i % 2) * 0.2) for i in range(7)],
        maxlen=1200,
    )

    first = armed_base_anchor("NIFTY", 24300.0, side, 53.0, settings=settings)
    assert first["basePremium"] == 52.8
    expiry = datetime.fromisoformat(first["expiresAt"])
    new_start = expiry + timedelta(seconds=1)
    _local_base_hist[key].extend(
        (new_start + timedelta(seconds=i * 3), 61.0 + (i % 2) * 0.2)
        for i in range(8)
    )

    second = armed_base_anchor("NIFTY", 24300.0, side, 61.2, settings=settings)
    assert second["armed"] is True
    assert second["basePremium"] == 61.0
    assert second["armedAt"] != first["armedAt"]


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_close_consumes_anchor_and_new_higher_base_rearms_without_expiry(side):
    settings = Settings(
        ict_armed_base_horizon_seconds=1800.0,
        explosion_post_peak_reentry_guard_enabled=True,
        explosion_post_peak_reentry_lookback_seconds=1800,
        explosion_post_peak_reentry_min_peak_points=20.0,
        explosion_post_peak_reentry_base_samples=3,
        explosion_post_peak_reentry_base_span_seconds=6.0,
        explosion_post_peak_reentry_min_reacceleration_pct=8.0,
        explosion_post_peak_reentry_min_velocity_3s=1.5,
    )
    key = _open_key("NIFTY", 24300.0, side)
    start = datetime.now(IST) - timedelta(seconds=30)
    _local_base_hist[key] = deque(
        [(start + timedelta(seconds=i * 3), 52.8 + (i % 2) * 0.2) for i in range(8)],
        maxlen=1200,
    )
    first = armed_base_anchor("NIFTY", 24300.0, side, 57.0, settings=settings)
    assert first["armed"] is True
    assert first["basePremium"] == pytest.approx(52.8)

    closed_at = start + timedelta(seconds=30)
    consumed = consume_armed_base_anchor(
        "NIFTY", 24300.0, side, closed_at=closed_at,
    )
    assert consumed["consumed"] is True
    assert key not in _armed_base_anchors
    assert _armed_base_reset_after[key] == closed_at

    # A same-timestamp print and one exhausted-high print cannot rebuild the base.
    _record = explosion_detector._record_local_base
    _record(key, closed_at, 79.0)
    _record(key, closed_at + timedelta(seconds=3), 79.2)
    immediate = armed_base_anchor(
        "NIFTY", 24300.0, side, 79.2, settings=settings,
    )
    assert immediate["armed"] is False

    prior = PaperTrade(
        id=f"first-{side.value.lower()}",
        symbol="NIFTY",
        side=side,
        strike=24300.0,
        entryPremium=57.0,
        currentPremium=68.0,
        lots=1,
        openedAt=start + timedelta(seconds=24),
        closedAt=closed_at,
        status="CLOSED",
        exitReason="explosion_peak_capture",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=715.0,
        pnlPoints=11.0,
        bestPnlPoints=23.0,
        maxLtp=80.0,
        entryContext={"selectionMode": "explosion", "ictArmedBaseLaunch": True},
    )
    state = AutoTraderState(closedPaperTrades=[prior])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, immediate_meta = exhausted_ftv_reentry_blocked(
            state,
            symbol="NIFTY",
            side=side,
            strike=24300.0,
            premium=79.2,
            velocity_3s=3.0,
        )
    assert blocked is True
    assert immediate_meta["newBaseReacceleration"] is False

    # A genuinely new, higher post-close coil can re-arm in seconds, not 1,800s.
    for i, premium in enumerate((65.0, 65.2, 64.9, 65.1, 65.0, 65.2, 64.9, 65.1)):
        _record(key, closed_at + timedelta(seconds=6 + i * 3), premium)
    launch_at = closed_at + timedelta(seconds=33)
    _record(key, launch_at, 70.2)
    second = armed_base_anchor(
        "NIFTY", 24300.0, side, 70.2, settings=settings,
    )

    assert second["armed"] is True
    assert second["basePremium"] == pytest.approx(64.9)
    assert datetime.fromisoformat(second["armedAt"]) < closed_at + timedelta(seconds=60)
    assert datetime.fromisoformat(second["expiresAt"]) > closed_at + timedelta(seconds=1700)
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings,
    ):
        blocked, reset_meta = exhausted_ftv_reentry_blocked(
            state,
            symbol="NIFTY",
            side=side,
            strike=24300.0,
            premium=70.2,
            velocity_3s=3.0,
        )
    assert blocked is False
    assert reset_meta["newBaseReacceleration"] is True


def test_restored_tape_rebuilds_anchor_and_reset_hook_clears_it():
    settings = Settings()
    key = _open_key("NIFTY", 24300.0, Side.CALL)
    start = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    _local_base_hist[key] = deque(
        [(start + timedelta(seconds=i * 3), 52.8 + (i % 2) * 0.1) for i in range(7)],
        maxlen=1200,
    )

    restored = armed_base_anchor(
        "NIFTY", 24300.0, Side.CALL, 53.0, settings=settings,
    )
    assert restored["armed"] is True
    assert key in _armed_base_anchors

    reset_detector_state_for_tests()
    assert _armed_base_anchors == {}
