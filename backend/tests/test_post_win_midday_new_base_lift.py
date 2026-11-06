"""Post-win midday consolidation base → same-strike second lift (Nov 6 24650 CE @13:00)."""

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.elite_score_engine import elite_entry_allowed
from app.engines.explosion_detector import (
    _local_base_hist,
    _open_key,
    post_close_local_base_consolidation,
)
from app.engines.session_mode_feedback import (
    same_strike_post_win_fresh_base_reentry,
    stamp_post_win_fresh_base_lift_alert,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _seed_midday_base_hist(
    *,
    closed_at: datetime,
    base_premium: float = 151.0,
    lift_premium: float = 163.0,
) -> None:
    key = _open_key("NIFTY", 24650.0, Side.CALL)
    _local_base_hist[key] = deque(maxlen=5000)
    t0 = closed_at + timedelta(minutes=5)
    # ~45m chop near base (10s samples)
    for i in range(270):
        ts = t0 + timedelta(seconds=10 * i)
        prem = base_premium + (0.4 if i % 7 == 0 else 0.0)
        _local_base_hist[key].append((ts, prem))
    # lift tail (inside 45s exclude window)
    now = t0 + timedelta(seconds=10 * 270)
    for j in range(6):
        ts = now + timedelta(seconds=3 * j)
        step = (lift_premium - base_premium) * (j + 1) / 6.0
        _local_base_hist[key].append((ts, base_premium + step))


def _nov6_win() -> PaperTrade:
    closed = datetime(2026, 11, 6, 12, 15, 38, tzinfo=IST)
    return PaperTrade(
        id="nov6-24650-win",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24650.0,
        entryPremium=145.67,
        currentPremium=169.7,
        lots=10,
        openedAt=closed - timedelta(minutes=80),
        closedAt=closed,
        status="CLOSED",
        exitReason="explosion_trail_sl",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=18981.0,
        entryContext={"selectionMode": "explosion"},
    )


def test_post_close_local_base_consolidation_spans_midday_chop():
    closed = datetime(2026, 11, 6, 12, 15, 38, tzinfo=IST)
    _seed_midday_base_hist(closed_at=closed, lift_premium=162.0)
    ok, meta = post_close_local_base_consolidation(
        "NIFTY",
        24650.0,
        Side.CALL,
        closed_at=closed,
        current_premium=162.0,
        min_consolidation_span_seconds=90.0,
    )
    assert ok is True
    assert float(meta["consolidationSpanSeconds"]) >= 90.0
    assert 6.0 <= float(meta["reaccelerationPct"]) <= 22.0
    _local_base_hist.clear()


def test_same_strike_fresh_base_midday_uses_consolidation_fallback():
    closed = datetime(2026, 11, 6, 12, 15, 38, tzinfo=IST)
    lift_at = datetime(2026, 11, 6, 13, 0, 10, tzinfo=IST)
    _seed_midday_base_hist(closed_at=closed, lift_premium=165.0)
    settings = Settings(
        post_win_fresh_base_midday_min_age_seconds=1800.0,
        post_win_fresh_base_min_local_pad_pct=8.0,
        post_win_new_local_base_max_pad_pct=22.0,
    )
    state = AutoTraderState(closedPaperTrades=[_nov6_win()], openPaperTrades=[])

    with patch("app.engines.session_mode_feedback.get_settings", return_value=settings):
        with patch(
            "app.engines.explosion_detector.post_close_base_reacceleration",
            return_value=(False, {"newBaseReacceleration": False}),
        ):
            with patch(
                "app.engines.session_mode_feedback.datetime"
            ) as mock_dt:
                mock_dt.now.return_value = lift_at
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                ok, meta = same_strike_post_win_fresh_base_reentry(
                    state,
                    symbol="NIFTY",
                    side=Side.CALL,
                    strike=24650.0,
                    premium=165.0,
                    velocity_3s=2.0,
                    alert={"premiumMomentum5Pct": 1.2},
                )
    assert ok is True
    assert meta["reason"] == "fresh_base_reentry"
    assert meta.get("postWinMiddayBaseMode") is True
    _local_base_hist.clear()


def test_stamp_post_win_fresh_base_sets_first_lift_local_base():
    alert: dict = {}
    stamp_post_win_fresh_base_lift_alert(alert, {"reaccelerationPct": 11.5})
    assert alert["momentType"] == "first_lift_local_base"
    assert alert["firstLift"] is True
    assert alert["localBaseMovePct"] == 11.5


def test_elite_waives_v_rip_shallow_when_post_win_fresh_base_in_pad():
    settings = Settings(post_win_fresh_base_waive_v_rip_shallow_enabled=True)
    proven = {
        "newBaseReacceleration": True,
        "reaccelerationPct": 12.0,
        "basePremium": 151.0,
        "velocity3s": 2.0,
    }
    state = AutoTraderState(closedPaperTrades=[_nov6_win()], openPaperTrades=[])
    evidence = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24650.0,
        "premium": 169.0,
        "velocity3s": 2.0,
        "flatThenVertical": False,
        "vRipReady": True,
        "activeBreakout": True,
        "armedBaseLaunch": False,
        "firstLift": False,
        "localBaseMovePct": 12.0,
        "flatVerticalQuality": 79.0,
        "explosionScore": 82.0,
        "volumeAwaken": True,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
        "tier": "ELITE",
    }
    with patch(
        "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
        return_value=(True, proven),
    ):
        ok, reason, assessment = elite_entry_allowed(
            evidence,
            {"grade": "A", "rankScore": 70.0},
            settings=settings,
            state=state,
        )
    assert ok is True, reason
    assert assessment.get("sameStrikePostWinFreshBase") is True
