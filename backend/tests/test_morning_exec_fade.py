"""Morning exec fade — two-bar confirm before 10:30 IST."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.morning_exec_fade import (
    premium_live_fade_blocks_now,
    premium_mtf_fade_block_reason,
)
from app.engines.session_timing import in_morning_exec_fade_strict_window
from app.models.schemas import TimeframeChartRead

IST = ZoneInfo("Asia/Kolkata")
MORNING = datetime(2026, 11, 19, 10, 5, tzinfo=IST)
AFTERNOON = datetime(2026, 11, 19, 11, 0, tzinfo=IST)


def test_morning_strict_window_bounds():
    s = Settings()
    assert in_morning_exec_fade_strict_window(MORNING)
    assert not in_morning_exec_fade_strict_window(AFTERNOON)


def test_live_fade_single_leg_ok_in_morning():
    assert not premium_live_fade_blocks_now(
        premium_momentum_3s=-0.2,
        premium_momentum_5s=-0.05,
        min_mom=-0.15,
        when=MORNING,
    )


def test_live_fade_blocks_when_both_weak_in_morning():
    assert premium_live_fade_blocks_now(
        premium_momentum_3s=-0.25,
        premium_momentum_5s=-0.22,
        min_mom=-0.15,
        when=MORNING,
    )


def test_mtf_fade_requires_both_tfs_in_morning():
    pm = {
        "1m": TimeframeChartRead(label="1m", direction="BEARISH", momentumPct=-0.4),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=0.1),
    }

    def fade(req, pt):
        if pt and pt.direction == "BEARISH" and pt.momentumPct < -0.15:
            return True, f"exec_mtf_premium_{req}_fading"
        return False, ""

    block, _ = premium_mtf_fade_block_reason(pm, fade_check=fade, when=MORNING)
    assert not block