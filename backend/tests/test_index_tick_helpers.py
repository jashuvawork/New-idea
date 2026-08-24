"""Index tick helpers — spot tape that lifts strike premiums."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.index_tick_helpers import (
    clear_index_spike_wake,
    evaluate_index_tick_helpers,
    peek_index_spike_wake,
    recent_index_drift,
    recent_index_spike_thrust,
    reset_index_tick_helpers_for_tests,
    stamp_index_tick_helpers,
)
from app.engines.building_lift_helpers import evaluate_building_lift_helpers
from app.engines.building_ltp_monitor import (
    building_ltp_monitor_due,
    reset_building_ltp_monitor_for_tests,
)
from app.engines.elite_never_block import top_explosion_must_take_active
from app.engines.trade_ranking import ftv_authorization_policy
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from app.services.tick_store import clear as clear_ticks
from app.services.tick_store import record_tick
from app.services.upstox import INDEX_KEYS

IST = ZoneInfo("Asia/Kolkata")


def _snap_put(**chart_kw) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=76900.0,
        atmStrike=76900.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction=chart_kw.get("direction", "BEARISH"),
            momentum5Pct=chart_kw.get("momentum5Pct", -0.16),
            momentum10Pct=chart_kw.get("momentum10Pct", -0.12),
            momentum15Pct=chart_kw.get("momentum15Pct", -0.05),
        ),
        explosionAlerts=[],
    )


def test_index_tick_helpers_confirm_put_on_falling_spot():
    reset_index_tick_helpers_for_tests()
    clear_ticks()
    key = INDEX_KEYS["SENSEX"]
    # Falling index tape → PUT align/spike.
    record_tick(key, 77000.0)
    import time

    time.sleep(0.02)
    # Simulate history with older higher print via direct history inject.
    from app.services import tick_store

    hist = tick_store._tick_history[key.replace(":", "|")]
    # Backdate first tick so velocity span is valid.
    if hist:
        hist[0].received_mono -= 3.0
    record_tick(key, 76950.0)  # ~-0.065% in 3s

    snap = _snap_put()
    board = evaluate_index_tick_helpers(snap=snap, side=Side.PUT)
    assert board.tick_align or board.velocity_3s < 0
    assert "index_mom_turn" in board.helpers or board.mom_align
    assert "index_breadth" in board.helpers
    stamped = stamp_index_tick_helpers({}, board)
    assert "indexSpotMove3s" in stamped
    assert stamped["indexHelpers"]


def test_building_helpers_include_index_board():
    reset_index_tick_helpers_for_tests()
    snap = _snap_put()
    with patch(
        "app.engines.index_tick_helpers.evaluate_index_tick_helpers"
    ) as mock_idx:
        from app.engines.index_tick_helpers import IndexTickHelpers

        mock_idx.return_value = IndexTickHelpers(
            symbol="SENSEX",
            side="PUT",
            velocity_3s=-0.08,
            velocity_9s=-0.12,
            tick_align=True,
            tick_spike=True,
            mom_align=True,
            squeeze_align=False,
            breadth_align=True,
            helpers=["index_tick_spike", "index_mom_turn", "index_breadth"],
            helper_count=3,
            confirming=True,
        )
        board = evaluate_building_lift_helpers(
            snap=snap,
            alert={
                "tier": "BUILDING",
                "side": "PUT",
                "strike": 76900.0,
                "premium": 131.0,
                "velocity3s": 3.5,
                "volumeAwaken": True,
                "volumeSurge": 2.5,
                "ictDisplacement": True,
                "ictFlatThenVertical": True,
                "flatVerticalQuality": 88.0,
            },
            prev_ltp=125.0,
            live_ltp=131.0,
        )
    assert board.index_confirming
    assert "index_tick_spike" in board.helpers
    assert board.helping


@patch("app.engines.elite_never_block.get_settings")
def test_must_take_allows_index_helpers_when_chart_lags(mock_s):
    s = MagicMock()
    s.explosion_top_must_take_enabled = True
    s.explosion_top_must_take_tiers_csv = "ELITE,EXPLODING"
    s.explosion_top_must_take_min_score = 62.0
    s.explosion_top_must_take_require_atm_itm = True
    s.explosion_top_must_take_require_chart_align = True
    s.explosion_top_must_take_allow_index_helpers = True
    s.min_option_premium_inr = 18.0
    mock_s.return_value = s

    # Chart still bullish (lagging) while PUT is ripping — index helpers save it.
    snap_lag = _snap_put(direction="BULLISH", momentum5Pct=0.05, momentum15Pct=0.02)
    from types import SimpleNamespace

    event = SimpleNamespace(
        tier="ELITE",
        side=Side.PUT,
        strike=76900.0,
        premium=130.0,
        explosion_score=80.0,
        symbol="SENSEX",
    )
    with patch("app.engines.elite_never_block._in_near_base_window", return_value=True):
        with patch("app.engines.elite_never_block._is_atm_or_itm", return_value=True):
            with patch(
                "app.engines.index_tick_helpers.evaluate_index_tick_helpers"
            ) as mock_idx:
                from app.engines.index_tick_helpers import IndexTickHelpers

                mock_idx.return_value = IndexTickHelpers(
                    confirming=True,
                    tick_spike=True,
                    helpers=["index_tick_spike", "index_breadth"],
                )
                assert top_explosion_must_take_active(
                    event=event, snap=snap_lag, tier="ELITE",
                ) is True
            with patch(
                "app.engines.index_tick_helpers.evaluate_index_tick_helpers"
            ) as mock_idx:
                from app.engines.index_tick_helpers import IndexTickHelpers

                mock_idx.return_value = IndexTickHelpers(confirming=False)
                assert top_explosion_must_take_active(
                    event=event, snap=snap_lag, tier="ELITE",
                ) is False


def test_top_ftv_a_waives_cvd_accel_when_index_confirms():
    evidence = {
        "mode": "explosion",
        "tier": "ELITE",
        "flatThenVertical": True,
        "activeBreakout": True,
        "firstLift": True,
        "localBaseMovePct": 12.0,
        "explosionScore": 92.0,
        "flatVerticalQuality": 80.0,
        "tqs": 55.0,
        "velocity3s": 3.0,
        "velocity9s": 2.0,
        "cvdBuying": True,
        "cvdAcceleration": False,
        "indexHelpersConfirm": True,
        "indexTickSpike": True,
        "timingAssessment": "GOOD",
    }
    ranking = {"grade": "A"}
    auth = ftv_authorization_policy(
        evidence,
        ranking,
        allocation_rank=1,
        require_allocation_rank_one=True,
        top_ftv_a_index_helpers_waive_cvd_accel=True,
    )
    assert auth.mode == "TOP_FTV_A"
    assert auth.allowed

    # Without index helpers, still blocked on CVD accel.
    evidence2 = dict(evidence)
    evidence2["indexHelpersConfirm"] = False
    evidence2["indexTickSpike"] = False
    auth2 = ftv_authorization_policy(
        evidence2,
        ranking,
        allocation_rank=1,
        require_allocation_rank_one=True,
        top_ftv_a_index_helpers_waive_cvd_accel=True,
    )
    assert auth2.mode is None
    assert "cvd_acceleration" in auth2.reason


def _seed_spikes(symbol: str, values: list[float]) -> None:
    """Inject recent same-window spike moments directly into history."""
    import time as _t

    from app.engines import index_tick_helpers as ith

    now = _t.monotonic()
    ith._spike_history[symbol.upper()].clear()
    for i, v in enumerate(values):
        ith._spike_history[symbol.upper()].append((now - (len(values) - i) * 0.5, v))


def test_recent_index_spike_thrust_detects_same_direction_burst():
    reset_index_tick_helpers_for_tests()
    # Three falling spikes → PUT burst; not a CALL burst.
    _seed_spikes("SENSEX", [-0.05, -0.06, -0.04])
    put = recent_index_spike_thrust("SENSEX", Side.PUT)
    assert put["aligned_count"] == 3
    assert put["burst"] is True
    assert put["net_pct"] < 0
    call = recent_index_spike_thrust("SENSEX", Side.CALL)
    assert call["aligned_count"] == 0
    assert call["burst"] is False


def test_recent_index_spike_thrust_expires_old_moments():
    reset_index_tick_helpers_for_tests()
    import time as _t

    from app.engines import index_tick_helpers as ith

    old = _t.monotonic() - 120.0
    ith._spike_history["SENSEX"].extend([(old, -0.05), (old, -0.06), (old, -0.07)])
    res = recent_index_spike_thrust("SENSEX", Side.PUT, window_seconds=45.0)
    assert res["count"] == 0
    assert res["burst"] is False


def test_spike_burst_becomes_index_helper():
    reset_index_tick_helpers_for_tests()
    clear_ticks()
    _seed_spikes("SENSEX", [-0.05, -0.06, -0.05])
    snap = _snap_put()
    board = evaluate_index_tick_helpers(snap=snap, side=Side.PUT)
    assert board.spike_burst is True
    assert board.spike_burst_count >= 3
    assert "index_spike_burst" in board.helpers
    stamped = stamp_index_tick_helpers({}, board)
    assert stamped["indexSpikeBurst"] is True
    assert stamped["indexSpikeBurstCount"] >= 3


def _seed_ltp(symbol: str, points: list[float], *, step: float = 1.0) -> None:
    """Inject a raw index LTP history (oldest first), spaced `step` seconds apart."""
    import time as _t

    from app.engines import index_tick_helpers as ith

    now = _t.monotonic()
    ith._ltp_history[symbol.upper()].clear()
    n = len(points)
    for i, p in enumerate(points):
        ith._ltp_history[symbol.upper()].append((now - (n - 1 - i) * step, float(p)))


def test_recent_index_drift_detects_steady_down_grind():
    reset_index_tick_helpers_for_tests()
    # SENSEX bleeds ~76900 -> 76840 (-0.078%) over the window — a PUT-fuel grind.
    pts = [76900 - i * 2.0 for i in range(31)]  # 31 ticks, -60 pts total
    _seed_ltp("SENSEX", pts, step=1.5)
    put = recent_index_drift("SENSEX", Side.PUT, window_seconds=45.0)
    assert put["drift"] is True
    assert put["net_pct"] < 0
    # A CALL is NOT aligned with a falling index.
    call = recent_index_drift("SENSEX", Side.CALL, window_seconds=45.0)
    assert call["drift"] is False


def test_recent_index_drift_ignores_chop():
    reset_index_tick_helpers_for_tests()
    # Oscillation that nets ~zero over the window — must not read as a drift.
    pts = [76900 + (8.0 if i % 2 else -8.0) for i in range(31)]
    _seed_ltp("SENSEX", pts, step=1.5)
    assert recent_index_drift("SENSEX", Side.PUT, window_seconds=45.0)["drift"] is False
    assert recent_index_drift("SENSEX", Side.CALL, window_seconds=45.0)["drift"] is False


def test_index_drift_becomes_helper_and_confirms_with_structure():
    reset_index_tick_helpers_for_tests()
    clear_ticks()
    pts = [76950 - i * 2.5 for i in range(31)]  # steady fall
    _seed_ltp("SENSEX", pts, step=1.5)
    snap = _snap_put()  # bearish chart + breadth = structure
    board = evaluate_index_tick_helpers(snap=snap, side=Side.PUT)
    assert board.drift_align is True
    assert "index_drift" in board.helpers
    assert board.confirming is True
    stamped = stamp_index_tick_helpers({}, board)
    assert stamped["indexDrift"] is True
    assert stamped["indexDriftNetPct"] < 0


def _seed_extremes(symbol, hi, lo, last):
    import datetime as _dt

    from app.engines import index_tick_helpers as ith

    ith._session_extremes[symbol.upper()] = {
        "date": _dt.datetime.now(IST).date(),
        "open": lo, "hi": hi, "lo": lo, "last": last,
    }


def test_index_trend_breakout_fires_on_call_new_high_with_thrust():
    from app.engines.index_tick_helpers import index_trend_breakout
    reset_index_tick_helpers_for_tests()
    # SENSEX broke out: session 77440->77600, spot near the high, rising grind (CALL thrust).
    _seed_extremes("SENSEX", hi=77600, lo=77440, last=77590)
    _seed_ltp("SENSEX", [77540 + i * 2.0 for i in range(31)], step=1.5)  # +60pts up grind
    snap = _snap_put(direction="BULLISH", momentum5Pct=0.165, momentum15Pct=0.05)
    snap.spot = 77590.0
    bo = index_trend_breakout("SENSEX", Side.CALL, snap)
    assert bo["breakout"] is True
    assert "near_session_high" in bo["reasons"]
    assert "index_thrust" in bo["reasons"]


def test_index_trend_breakout_rejects_flat_chop():
    from app.engines.index_tick_helpers import index_trend_breakout
    reset_index_tick_helpers_for_tests()
    # Tiny session range + oscillation = chop → no breakout even near the "high".
    _seed_extremes("SENSEX", hi=77460, lo=77440, last=77458)
    _seed_ltp("SENSEX", [77450 + (5 if i % 2 else -5) for i in range(31)], step=1.5)
    snap = _snap_put(direction="BULLISH", momentum5Pct=0.02)
    snap.spot = 77458.0
    assert index_trend_breakout("SENSEX", Side.CALL, snap)["breakout"] is False


def test_index_trend_breakout_rejects_new_high_without_thrust():
    from app.engines.index_tick_helpers import index_trend_breakout
    reset_index_tick_helpers_for_tests()
    # At the high with a real range but NO sustained thrust (flat buffer) → no breakout.
    _seed_extremes("SENSEX", hi=77600, lo=77440, last=77595)
    _seed_ltp("SENSEX", [77595.0 for _ in range(31)], step=1.5)  # flat = no drift/burst
    snap = _snap_put(direction="BULLISH", momentum5Pct=0.165)
    snap.spot = 77595.0
    assert index_trend_breakout("SENSEX", Side.CALL, snap)["breakout"] is False


def test_trend_breakout_seeds_session_hilo_from_snapshot_when_ticks_cold():
    """After a restart the tick tracker is cold — broker session H/L still enables the override."""
    from app.engines.index_tick_helpers import index_trend_breakout
    from app.models.schemas import ChartAnalysis
    reset_index_tick_helpers_for_tests()  # no _session_extremes (cold start)
    _seed_ltp("SENSEX", [77540 + i * 2.0 for i in range(31)], step=1.5)  # rising -> CALL drift
    snap = _snap_put(direction="BULLISH", momentum5Pct=0.165)
    snap.spot = 77590.0
    snap.chartAnalysis = ChartAnalysis(
        institutional={"sessionHigh": 77600.0, "sessionLow": 77440.0}
    )
    bo = index_trend_breakout("SENSEX", Side.CALL, snap)
    assert bo["breakout"] is True
    assert "near_session_high" in bo["reasons"]


def test_index_trend_override_active_scans_symbols():
    from app.engines.index_tick_helpers import index_trend_override_active
    reset_index_tick_helpers_for_tests()
    _seed_extremes("SENSEX", hi=77600, lo=77440, last=77590)
    _seed_ltp("SENSEX", [77540 + i * 2.0 for i in range(31)], step=1.5)
    snap = _snap_put(direction="BULLISH", momentum5Pct=0.165)
    snap.spot = 77590.0
    ok, meta = index_trend_override_active({"SENSEX": snap})
    assert ok is True
    assert meta.get("side") == "CALL"


def test_index_spike_wakes_building_ltp_cycle():
    reset_building_ltp_monitor_for_tests()
    reset_index_tick_helpers_for_tests()
    clear_index_spike_wake()

    snap = _snap_put()
    snap.explosionAlerts = [
        {
            "tier": "BUILDING",
            "side": "PUT",
            "strike": 76900.0,
            "premium": 125.0,
        }
    ]
    snapshots = {"SENSEX": snap}

    # No move yet → not due (first sighting seeds watch).
    with patch(
        "app.engines.building_ltp_monitor.peek_building_ltp_moves",
        return_value=(False, [], {"SENSEX:PUT:76900": 125.0}),
    ):
        with patch(
            "app.engines.building_ltp_monitor.peek_building_helper_flip",
            return_value=(False, []),
        ):
            assert building_ltp_monitor_due(snapshots) is False

    # Index spike pending for SENSEX → wake.
    from app.engines import index_tick_helpers as ith

    ith._pending_wake_symbols.add("SENSEX")
    with patch(
        "app.engines.building_ltp_monitor.peek_building_ltp_moves",
        return_value=(False, [], {"SENSEX:PUT:76900": 125.0}),
    ):
        with patch(
            "app.engines.building_ltp_monitor.peek_building_helper_flip",
            return_value=(False, []),
        ):
            assert building_ltp_monitor_due(snapshots) is True
    # Consumed.
    spiked, _ = peek_index_spike_wake({"SENSEX"})
    assert spiked is False
