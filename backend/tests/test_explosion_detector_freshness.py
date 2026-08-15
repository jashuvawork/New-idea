"""Explosion detector session and feed-freshness regressions."""

from collections import deque
from datetime import datetime, timedelta

import app.engines.explosion_detector as detector
from app.models.schemas import Side


def test_first_record_of_new_session_drops_previous_day_history():
    old = datetime.now(detector.IST) - timedelta(days=1)
    key = detector._strike_key(24300.0, Side.CALL)
    detector._history["NIFTY"] = {
        key: deque([(old, 80.0, 1000.0)], maxlen=detector.MAX_HISTORY),
    }
    detector._session_date = old.strftime("%Y-%m-%d")

    detector._record("NIFTY", 24300.0, Side.CALL, 100.0, 1200.0)

    rows = list(detector._history["NIFTY"][key])
    assert len(rows) == 1
    assert rows[0][1] == 100.0


def test_velocity_rejects_stale_samples_after_feed_gap():
    now = datetime.now(detector.IST)
    history = deque([
        (now - timedelta(minutes=2), 100.0, 1000.0),
        (now, 120.0, 1200.0),
    ])

    assert detector._velocity(history, 1) == 0.0


def test_velocity_keeps_fresh_poll_move():
    now = datetime.now(detector.IST)
    history = deque([
        (now - timedelta(seconds=3), 100.0, 1000.0),
        (now, 103.0, 1200.0),
    ])

    assert detector._velocity(history, 1) == 3.0
