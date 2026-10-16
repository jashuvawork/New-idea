"""EOD would-have-traded report — replay a contract with re-entries."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from types import SimpleNamespace

from app.engines.eod_trade_report import (
    _not_post_peak_chase,
    apply_portfolio_limits,
    build_scorecard,
    generate_eod_trade_report,
    replay_contract_trades,
)

IST = ZoneInfo("Asia/Kolkata")


def _series(prems, t0):
    return [(t0 + timedelta(seconds=3 * i), float(p), 77000.0) for i, p in enumerate(prems)]


def test_replay_captures_near_base_runner_with_reentry():
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=IST)
    # Flat base ~66s (so the 45s index drift can confirm while premium is still at the base),
    # then a rip 60 -> 130, a pullback, and a 2nd leg. The near-base window is <=15% off base.
    prems = (
        [60] * 22                              # flat base — drift builds, premium at base
        + [60 + 2 * i for i in range(36)]      # 60 -> 130 rip (enters ~10-15% off base)
        + [130 - 3 * i for i in range(1, 16)]  # -> ~85
        + [85 + 2 * i for i in range(1, 30)]   # 2nd leg 85 -> ~143
        + [143 - 4 * i for i in range(1, 12)]
    )
    series = _series(prems, t0)
    # CALL: spot must rise fast enough that the 45s net drift clears ~0.05% (=> ~40pts/45s).
    spot_rel = [(3.0 * i, 77000.0 + i * 6.0) for i in range(len(prems))]
    trades = replay_contract_trades(
        symbol="SENSEX", side="CALL", strike=77000.0, tier="ELITE",
        series=series, spot_rel=spot_rel, t0=t0,
    )
    assert trades, "expected at least one generated trade"
    # Entry near the base (<=15% off base), a real captured move, and a lot count.
    first = trades[0]
    assert first["offBasePct"] <= 15.0
    assert first["lots"] >= 1
    assert first["peakPct"] > 0


def test_generate_report_unpacks_ranked_targets_and_takes_near_base():
    """End-to-end guard: the ranked target 5-tuple must unpack cleanly (regression:
    the ``want`` set previously unpacked 4 of 5 values and 500'd the live endpoint)."""
    date = "2026-08-20"
    entries = [
        {
            "symbol": "SENSEX", "side": "CALL", "strike": 77000.0, "tier": "ELITE",
            "alert": {"tier": "ELITE"}, "outcome": {"mfePct": 140.0},
        },
    ]
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=IST)
    prems = (
        [60] * 22                              # flat base so drift confirms at the base
        + [60 + 2 * i for i in range(36)]      # 60 -> 130 near-base rip
        + [130 - 3 * i for i in range(1, 16)]
        + [85 + 2 * i for i in range(1, 30)]
    )
    batches = []
    for i, p in enumerate(prems):
        ts = (t0 + timedelta(seconds=3 * i)).isoformat()
        batches.append({
            "ts": ts,
            "contracts": [{
                "symbol": "SENSEX", "side": "CALL", "strike": 77000.0,
                "premium": float(p), "spot": 77000.0 + i * 6.0,
            }],
        })

    with (
        patch(
            "app.services.radar_archive.read_archive_entries",
            return_value=entries,
        ),
        patch(
            "app.services.radar_learning.read_premium_tape",
            return_value=batches,
        ),
    ):
        rep = generate_eod_trade_report(date)

    assert rep["status"] == "ok"
    assert rep["tradeCount"] >= 1
    # Every taken entry is near the base (<=15% off base) — the near-base entry rule.
    assert all(t["offBasePct"] <= 15.0 for t in rep["trades"])
    # The scorecard is present and measures the ELITE lane's near-base recall.
    assert "scorecard" in rep
    assert rep["scorecard"]["byLane"]["ELITE"]["capturedNearBase"] >= 1


def test_replay_no_trade_on_flat_chop():
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=IST)
    prems = [60 + (2 if i % 2 else -2) for i in range(60)]  # oscillate, never a real lift
    series = _series(prems, t0)
    spot_rel = [(3.0 * i, 77000.0 + (2 if i % 2 else -2)) for i in range(len(prems))]
    trades = replay_contract_trades(
        symbol="SENSEX", side="CALL", strike=77000.0, tier="ELITE",
        series=series, spot_rel=spot_rel, t0=t0,
    )
    # A flat chop with no sustained drift/base-lift should not generate a runner trade.
    assert all(t["peakPct"] < 30 for t in trades)


def test_scorecard_measures_early_recall_and_added_losers():
    # Two ELITE opportunities that day (MFE >= 30%); one EXPLODING that did not clear the bar.
    targets = [
        (140.0, "SENSEX", "CALL", 77000.0, "ELITE"),
        (55.0, "NIFTY", "PUT", 24000.0, "ELITE"),
        (12.0, "SENSEX", "CALL", 78000.0, "EXPLODING"),  # below opportunity bar
    ]
    taken = [
        # captured the first opportunity NEAR the base (early) and it won
        {"symbol": "SENSEX", "side": "CALL", "strike": 77000.0, "tier": "ELITE",
         "offBasePct": 11.0, "pnlInr": 5000.0},
        # captured the second opportunity but LATE (off base) — not counted as early recall
        {"symbol": "NIFTY", "side": "PUT", "strike": 24000.0, "tier": "ELITE",
         "offBasePct": 22.0, "pnlInr": 800.0},
        # an added loser that was not one of the opportunities
        {"symbol": "SENSEX", "side": "CALL", "strike": 78000.0, "tier": "ELITE",
         "offBasePct": 13.0, "pnlInr": -1200.0},
    ]
    sc = build_scorecard(targets, taken)
    elite = sc["byLane"]["ELITE"]
    assert elite["opportunities"] == 2
    assert elite["captured"] == 2
    assert elite["capturedNearBase"] == 1  # only the 11%-off entry counts as early
    assert elite["earlyRecall"] == 0.5
    assert elite["addedLosers"] == 1
    assert elite["addedLoserInr"] == -1200.0
    assert sc["overall"]["opportunities"] == 2
    assert sc["byLane"]["EXPLODING"]["opportunities"] == 0


def test_per_trade_loss_cap_bounds_cold_entry():
    from app.config import get_settings

    # A flat base, a brief lift (to trigger entry), then a hard collapse (cold entry that
    # never ignites). With the per-trade cap on, the exit reason is the cap and the loss is
    # bounded to roughly the cap (not the full collapse).
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=IST)
    prems = (
        [40] * 22                              # flat base
        + [40 + 0.6 * i for i in range(12)]    # small lift -> enters near base
        + [46 - 3 * i for i in range(1, 15)]   # hard collapse
    )
    series = _series(prems, t0)
    spot_rel = [(3.0 * i, 77000.0 + i * 6.0) for i in range(len(prems))]
    settings = get_settings()
    trades = replay_contract_trades(
        symbol="SENSEX", side="CALL", strike=77000.0, tier="ELITE",
        series=series, spot_rel=spot_rel, t0=t0, settings=settings,
    )
    assert trades
    cap = float(getattr(settings, "eod_replay_per_trade_max_loss_inr", 0.0))
    if cap > 0:
        capped = [t for t in trades if t["exitReason"] == "explosion_per_trade_loss_cap"]
        assert capped, "expected a per-trade cap exit on the cold collapse"
        # Loss is bounded near the cap (allow one bar of overshoot past the trigger).
        assert capped[0]["pnlInr"] >= -cap * 1.6


def test_post_peak_guard_rejects_chase_after_completed_run():
    t0 = datetime(2026, 8, 20, 11, 40, 0, tzinfo=IST)
    # A run 78 -> 133 (the real move), then a fade/consolidation to ~125 near the top.
    prems = (
        [78 + i * 2 for i in range(28)]        # 78 -> 132 run
        + [132, 130, 128, 126, 125, 125, 125]  # fade + consolidate near the top
    )
    series = [(t0 + timedelta(seconds=20 * i), float(p), 24000.0) for i, p in enumerate(prems)]
    last = len(series) - 1  # entering here = buying 125 near the 132 peak after a +69% run
    assert _not_post_peak_chase(
        series, last, lookback_s=900.0, min_run=0.25, near_top_frac=0.12
    ) is False


def test_post_peak_guard_allows_entry_as_run_starts():
    t0 = datetime(2026, 8, 20, 11, 40, 0, tzinfo=IST)
    # A flat base then just the first ticks up — no completed run in the window yet.
    prems = [70, 70, 71, 70, 71, 72, 73, 74]  # gentle start, <25% run
    series = [(t0 + timedelta(seconds=20 * i), float(p), 24000.0) for i, p in enumerate(prems)]
    last = len(series) - 1
    assert _not_post_peak_chase(
        series, last, lookback_s=900.0, min_run=0.25, near_top_frac=0.12
    ) is True


def _pos(entry_h, exit_h, side, pnl):
    d = datetime(2026, 8, 20, tzinfo=IST)
    return {
        "symbol": "SENSEX", "side": side, "pnlInr": float(pnl),
        "_entryDt": d.replace(hour=entry_h), "_exitDt": d.replace(hour=exit_h),
    }


def test_portfolio_limit_one_slot_is_one_at_a_time():
    # Two overlapping winners (10-12 and 11-13). With 1 slot only the first is taken.
    cands = [_pos(10, 12, "CALL", 5000), _pos(11, 13, "PUT", 4000)]
    s = SimpleNamespace(daily_loss_stop_inr=20_000.0, eod_report_max_concurrent=1,
                        eod_report_same_side_cap=2)
    taken = apply_portfolio_limits(cands, settings=s)
    assert len(taken) == 1


def test_portfolio_limit_two_slots_takes_concurrent_winners():
    cands = [_pos(10, 12, "CALL", 5000), _pos(11, 13, "PUT", 4000)]
    s = SimpleNamespace(daily_loss_stop_inr=20_000.0, eod_report_max_concurrent=2,
                        eod_report_same_side_cap=2)
    taken = apply_portfolio_limits(cands, settings=s)
    assert len(taken) == 2


def test_portfolio_limit_same_side_cap_blocks_third_same_side():
    # Three overlapping CALLs; same-side cap of 2 admits only two even with 3 slots.
    cands = [_pos(10, 14, "CALL", 5000), _pos(11, 14, "CALL", 4000),
             _pos(12, 14, "CALL", 3000)]
    s = SimpleNamespace(daily_loss_stop_inr=20_000.0, eod_report_max_concurrent=3,
                        eod_report_same_side_cap=2)
    taken = apply_portfolio_limits(cands, settings=s)
    assert len(taken) == 2


def test_portfolio_limit_halts_at_daily_loss_stop():
    cands = [_pos(10, 11, "CALL", -6000), _pos(11, 12, "PUT", -6000),
             _pos(12, 13, "CALL", 9000)]
    s = SimpleNamespace(daily_loss_stop_inr=10_000.0, eod_report_max_concurrent=1,
                        eod_report_same_side_cap=2)
    taken = apply_portfolio_limits(cands, settings=s)
    # After two -6000 legs (cum -12000 <= -10000) the day halts; the later winner is skipped.
    assert len(taken) == 2
    assert sum(t["pnlInr"] for t in taken) == -12_000
