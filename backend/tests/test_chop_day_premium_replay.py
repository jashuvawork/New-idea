from scripts.chop_day_premium_replay import chop_day_heuristic


def test_chop_day_heuristic_range_bound() -> None:
    spots = [(None, 25100.0), (None, 25120.0), (None, 25095.0), (None, 25105.0)]
    # inject dummy times via count only — use monotonic list with fake idx
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
    t0 = datetime(2026, 11, 13, 10, 0, tzinfo=IST)
    series = [(t0 + timedelta(minutes=i), 25100 + (i % 3) * 5) for i in range(80)]
    meta = chop_day_heuristic(series)
    assert meta["spotRangePct"] < 1.0
    assert "chopLikely" in meta