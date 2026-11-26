"""Block call_rally / fast_bullish fills when live premium 3s momentum is negative."""

from __future__ import annotations

from types import SimpleNamespace

from app.config import Settings
from app.engines.winner_entry_guards import (
    apply_falling_premium_exec_fill_guard,
    fast_bullish_call_rally_exec_lane,
    premium_fading_blocks_entry,
)
from app.models.schemas import PremiumChart, Side


def test_fast_bullish_lane_detects_call_rally_unlock():
    assert fast_bullish_call_rally_exec_lane(
        {
            "fastBullishLocalBase": True,
            "ictBaseReadinessReason": "fast_bullish_local_base_ready",
            "callAtBaseBestTradeReason": "call_rally_unlock",
        }
    )


def test_falling_guard_strips_pe_win_mirror_bypass():
    settings = Settings()
    prem = PremiumChart(momentum3Pct=-0.4, momentum5Pct=0.2, direction="BULLISH")
    alert = {
        "fastBullishLocalBase": True,
        "momentType": "fast_bullish_local_base",
    }
    mirror, pad, meta = apply_falling_premium_exec_fill_guard(
        settings,
        side=Side.CALL,
        premium_chart=prem,
        alert=alert,
        pe_win_mirror_bypass=True,
        premium_fade_pad_lane=True,
    )
    assert mirror is False
    assert meta.get("fallingPremiumExecFillGuard") is True


def test_premium_fading_blocks_negative_mom3_with_pe_win_mirror():
    settings = Settings()
    settings.pe_win_mirror_fade_waiver_requires_nonneg_mom3 = True
    blocked, reason = premium_fading_blocks_entry(
        trade_score=50.0,
        premium_momentum_3s=-0.35,
        premium_momentum_5s=-0.2,
        premium_direction="BULLISH",
        explosion_event=SimpleNamespace(tier="ELITE", daily_move_pct=50.0),
        pe_win_mirror_bypass=True,
    )
    assert blocked is True
    assert reason in ("premium_fading_at_execution", "premium_fading_high_score")