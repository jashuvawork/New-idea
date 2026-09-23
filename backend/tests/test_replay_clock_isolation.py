"""EOD replay clock must not shift live-thread session gates."""

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.eod_local_base_replay import _ReplayDateTime, _install_replay_clock, _restore_replay_clock
from app.engines.power_hour_guards import in_power_hour_window

IST = ZoneInfo("Asia/Kolkata")


def test_replay_clock_does_not_leak_to_other_threads():
    import app.engines.power_hour_guards as power_hour

    original_phase = power_hour.get_market_phase
    live_seen: list[bool] = []
    replay_seen: list[bool] = []

    def live_thread():
        power_hour.get_market_phase = lambda: "LIVE_MARKET"
        live_seen.append(in_power_hour_window())

    def replay_thread():
        power_hour.get_market_phase = lambda: "LIVE_MARKET"
        _ReplayDateTime.current = datetime(2026, 8, 28, 15, 5, 0, tzinfo=IST)
        saved = _install_replay_clock(_ReplayDateTime)
        try:
            replay_seen.append(in_power_hour_window())
        finally:
            _restore_replay_clock(saved)

    try:
        t_replay = threading.Thread(target=replay_thread)
        t_live = threading.Thread(target=live_thread)
        t_replay.start()
        t_live.start()
        t_replay.join()
        t_live.join()
    finally:
        power_hour.get_market_phase = original_phase

    assert replay_seen == [True]
    assert live_seen == [False]
