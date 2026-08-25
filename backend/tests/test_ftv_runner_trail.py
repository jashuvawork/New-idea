"""FTV runner %-of-peak-gain trail: V/FTV moves bank close to their best TP.

V/FTV moments run in big % off the local base (e.g. Rs68 -> Rs140 = +106%). The absolute
stage ladder under-protects modest-but-real % moves; this trails a consistent fraction
behind the peak GAIN so every real move locks near its top, while mega runners still ride.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.moment_stage_trail import (
    build_moment_stage_plan,
    ftv_runner_pct_floor,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _runner_trade(entry=68.0, best=0.0):
    plan = build_moment_stage_plan(
        entry_premium=entry, base_premium=50.0, velocity_3s=3.0, volume_surge=2.5,
        session_move_pct=30.0, flat_then_vertical=True, max_profit=True,
    )
    ctx = {
        "momentType": "flat_then_vertical", "ictFlatThenVertical": True,
        "maxProfitCapture": True, "ictBasePremium": 50.0, "velocity3s": 3.0,
    }
    if plan:
        ctx.update(plan)
    return PaperTrade(
        id="r", symbol="SENSEX", side=Side.CALL, strike=77600.0,
        entryPremium=entry, currentPremium=entry, lots=10,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        bestPnlPoints=best, entryContext=ctx,
    )


def test_pct_floor_keeps_fraction_of_peak_gain():
    t = _runner_trade(best=72.0)  # +106% peak on a Rs68 entry
    floor = ftv_runner_pct_floor(t, 72.0)
    assert floor is not None
    # keep 75% of the 72pt peak gain (~25% giveback from peak)
    assert abs(floor - 72.0 * 0.75) < 0.5


def test_pct_floor_not_armed_below_threshold():
    t = _runner_trade(best=10.0)  # +14.7% < 25% arm
    assert ftv_runner_pct_floor(t, 10.0) is None


def test_pct_floor_only_for_runner_moments():
    t = _runner_trade(best=72.0)
    t.entryContext = {"momentType": "scalp"}  # not an FTV/max-profit runner
    assert ftv_runner_pct_floor(t, 72.0) is None


def _sim(path):
    t = _runner_trade()
    best = 0.0
    peak = t.entryPremium
    for p in path:
        t.currentPremium = p
        best = max(best, p - t.entryPremium)
        t.bestPnlPoints = best
        peak = max(peak, p)
        t.entryContext["liveVelocity3s"] = 2.0 if p >= peak else -0.8
        reason, _ = evaluate_explosion_exit(
            t, p, "ELITE", 20, live_velocity_3s=(2.0 if p >= peak else -0.8),
        )
        if reason:
            return p, best, reason
    return path[-1], best, "no_exit"


def test_modest_forty_pct_move_banks_most_of_it():
    """A +40% move that reverses must NOT give the whole gain back (was ~+4%)."""
    entry = 68.0
    up = [entry + 1.5 * i for i in range(1, 19)]   # -> ~95 (+40%)
    down = [95 - 2 * i for i in range(1, 15)]
    exit_p, best, reason = _sim(up + down)
    kept = (exit_p - entry) / best if best else 0
    assert kept >= 0.6  # banks the majority of the peak, not a token slice


def test_hundred_pct_move_rides_and_banks_near_top():
    entry = 68.0
    up = [entry + i for i in range(1, 73)]          # -> ~140 (+106%)
    down = [140 - 3 * i for i in range(1, 16)]
    exit_p, best, reason = _sim(up + down)
    assert best >= 65  # rode the full ~106% move (not shaken out early)
    kept = (exit_p - entry) / best
    assert kept >= 0.6


def test_learned_keep_ratio_overrides_default():
    """A stamped learned keep-ratio drives the trail ONLY when apply is explicitly enabled.

    EOD-learning application is disabled by default (see config); enable it here to exercise
    the code path.
    """
    from unittest.mock import MagicMock

    s = MagicMock()
    s.ftv_runner_pct_trail_enabled = True
    s.ftv_runner_pct_trail_arm_pct = 25.0
    s.ftv_runner_pct_trail_keep_ratio = 0.72
    s.eod_learning_apply_enabled = True

    base = _runner_trade(best=72.0)
    base.entryContext["learnedTrailKeepRatio"] = 0.85  # high-hit mover: ride hard
    floor_learned = ftv_runner_pct_floor(base, 72.0, settings=s)
    assert abs(floor_learned - 72.0 * 0.85) < 0.5

    tight = _runner_trade(best=72.0)
    tight.entryContext["learnedTrailKeepRatio"] = 0.60  # low-hit: tighten
    floor_tight = ftv_runner_pct_floor(tight, 72.0, settings=s)
    assert abs(floor_tight - 72.0 * 0.60) < 0.5
    assert floor_learned > floor_tight

    # With apply DISABLED (default), the learned override is ignored -> static default keep.
    s.eod_learning_apply_enabled = False
    off = _runner_trade(best=72.0)
    off.entryContext["learnedTrailKeepRatio"] = 0.85
    assert abs(ftv_runner_pct_floor(off, 72.0, settings=s) - 72.0 * 0.72) < 0.5
