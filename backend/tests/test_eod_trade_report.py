"""EOD would-have-traded report — replay a contract with re-entries."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engines.eod_trade_report import replay_contract_trades

IST = ZoneInfo("Asia/Kolkata")


def _series(prems, t0):
    return [(t0 + timedelta(seconds=3 * i), float(p), 77000.0) for i, p in enumerate(prems)]


def test_replay_captures_near_base_runner_with_reentry():
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=IST)
    # Rip 60 -> 130 (near-base entry ~10-25% off base), pull back, then a 2nd leg.
    prems = (
        [60 + 2 * i for i in range(36)]      # 60 -> 130
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
    # Entry near the base (<=25% off base), a real captured move, and a lot count.
    first = trades[0]
    assert first["offBasePct"] <= 25.0
    assert first["lots"] >= 1
    assert first["peakPct"] > 0


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
