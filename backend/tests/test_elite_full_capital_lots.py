"""ELITE full-lot uses the full ~₹1.8L capital budget with a proper SL floor."""

from unittest.mock import MagicMock, patch

from app.config import get_settings
from app.engines.capital_allocator import max_lots_for_capital


def test_full_capital_lots_near_1_8l_notional():
    """Cash-affordable lots at ₹66 deploy ~₹1.8L, not the old ~₹80k risk envelope."""
    ep = 66.2
    lots = max_lots_for_capital("SENSEX", ep)
    notional = lots * ep * 20
    assert lots >= 120  # was ~52 under ₹10k/8pt risk sizing
    assert notional >= 160_000
    assert notional <= 190_000


def test_elite_sl_floor_is_wider_than_eight_points():
    s = get_settings()
    assert bool(getattr(s, "elite_full_lot_use_full_capital", True)) is True
    assert float(getattr(s, "elite_full_lot_risk_inr", 0) or 0) == 0.0
    min_pts = float(getattr(s, "elite_full_lot_min_stop_points", 16) or 16)
    min_pct = float(getattr(s, "elite_full_lot_min_stop_pct_of_premium", 0.18) or 0.18)
    floor = max(min_pts, 66.2 * min_pct)
    assert floor >= 16.0
    assert floor > 8.0


@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=135)
def test_eod_replay_uses_full_capital_lots(mock_cap):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.engines.eod_trade_report import replay_contract_trades

    IST = ZoneInfo("Asia/Kolkata")
    t0 = datetime(2026, 8, 20, 10, 0, 0, tzinfo=IST)
    prems = [60 + i for i in range(40)] + [100 - i for i in range(20)]
    series = [
        (t0 + timedelta(seconds=3 * i), float(p), 77000.0) for i, p in enumerate(prems)
    ]
    spot_rel = [(3.0 * i, 77000.0 + i * 6.0) for i in range(len(prems))]
    trades = replay_contract_trades(
        symbol="SENSEX",
        side="CALL",
        strike=77000.0,
        tier="ELITE",
        series=series,
        spot_rel=spot_rel,
        t0=t0,
    )
    assert trades
    first = trades[0]
    assert first["lots"] == 135
    assert first["stopPoints"] >= 16.0
    assert first["notionalInr"] >= 100_000
