"""Position-scaled emergency stop."""

from app.engines.risk_stops import effective_emergency_stop_inr


def test_emergency_scales_with_lots():
    # 60 NIFTY lots × 65 × 2.5pt = 9750 — below ₹12K cap
    cap = effective_emergency_stop_inr(60, 65, 2.5)
    assert cap == 9750.0


def test_emergency_flat_cap_when_small():
    # 10 lots — point budget 1625, cap still min(12000, 1625)
    cap = effective_emergency_stop_inr(10, 65, 2.5)
    assert cap == 1625.0
