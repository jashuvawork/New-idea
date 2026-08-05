"""Recent-window local base (Aug5 NIFTY 24500 PE): measure entry/chase from the recent
~30-min swing low, not the far full-session low.

The premium ran to a ~180 high early, dumped to a ~40 morning low, then based ~64-70
before the current leg. At LTP 72 the move is ~9-13% off the ~64 local base — near base,
NOT the ~80% chase it reads as off the ~40 session low.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import (
    local_base_premium,
    local_base_relative_move_pct,
    reset_detector_state_for_tests,
)
from app.engines.explosion_entry_guards import effective_local_base_move_pct
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _seed(key="NIFTY:PUT:24500.0"):
    reset_detector_state_for_tests()
    now = datetime.now(IST)
    dq = ed.deque(maxlen=ed.LOCAL_BASE_HIST_MAXLEN)
    # (minutes-ago, premium): far 40 dip OUTSIDE the 30-min window; ~64 base inside it.
    for mins, p in [(45, 40), (40, 42), (28, 66), (20, 64), (15, 68), (10, 66), (5, 70)]:
        dq.append((now - timedelta(minutes=mins), float(p)))
    dq.append((now, 72.0))
    ed._local_base_hist[key] = dq


def test_local_base_uses_recent_swing_low_not_session_low():
    _seed()
    base = local_base_premium("NIFTY", 24500.0, Side.PUT)
    # ~64 recent base, NOT the far 40 morning dip (outside the 30-min window)
    assert 60.0 <= base <= 68.0


def test_local_base_move_reads_near_base_not_chase():
    _seed()
    move = local_base_relative_move_pct("NIFTY", 24500.0, Side.PUT, 72.0)
    # ~9-13% off the local base — near base, well under the ~70% chase ceiling
    assert 5.0 <= move <= 20.0


def test_effective_local_base_move_prefers_recent_window():
    """effective_local_base_move_pct uses the recent local base (near-base %), not the
    ~80% off-session-low that would flag a chase — no ICT flat base needed."""
    _seed()
    event = SimpleNamespace(
        symbol="NIFTY", strike=24500.0, side=Side.PUT, premium=72.0,
        daily_move_pct=80.0, peak_move_pct=80.0,
    )
    # ICT flat-base absent (choppy base) → must still measure off the recent local base.
    move = effective_local_base_move_pct(event, ict=None)
    assert 5.0 <= move <= 20.0, f"expected near-base %, got {move}"


def test_no_local_base_history_falls_back():
    """With no local-base history, the recent-window path is skipped (returns to the
    legacy off-low / day% fallback path)."""
    reset_detector_state_for_tests()
    event = SimpleNamespace(
        symbol="NIFTY", strike=24500.0, side=Side.PUT, premium=72.0,
        daily_move_pct=0.0, peak_move_pct=0.0,
    )
    # No history recorded → recent path returns -1 → falls through (0.0 here, no off-low).
    assert effective_local_base_move_pct(event, ict=None) == 0.0
