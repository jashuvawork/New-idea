"""Helper-confirmed FTV lane.

"On the radar as BUILDING and suddenly something is helping to go flat->vertical."
When enough INDEPENDENT confirmations agree (strong volume, displacement, premium FVG,
flat->vertical structure, chart-align, breadth-align) on a name at its local base with
positive live velocity, that IS the confirmed FTV -- so it may enter on a lower
quality/score/velocity bar and (BUILDING) override the worst-day / BREAKOUT_ONLY block.
A soft near-miss without a genuine dynamic helper still hits the strict bar.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.ict_breakout_monitor import (
    _helper_confirmed_lift,
    building_rip_bullish_readiness,
    first_lift_entry_readiness,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(direction: str = "BULLISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24000.0,
        atmStrike=24000.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=70.0,
        breadth=Breadth(bias=direction, score=70, aligned=True),
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=0.12 if direction == "BULLISH" else -0.12,
            trendStrength=70,
            emaBias=direction,
            macdBias=direction,
        ),
    )


def _state():
    return SimpleNamespace(
        openPaperTrades=[],
        closedPaperTrades=[],
        calibrationBlocks={"CALL": False, "PUT": False},
    )


def _strong_alert(tier: str = "WATCH", side: str = "CALL") -> dict:
    # Modest quality (61) / score (51) / velocity (1.35) but strong VOLUME confirmation.
    return {
        "id": "x",
        "tradeable": True,
        "tier": tier,
        "side": side,
        "strike": 24000,
        "premium": 120.0,
        "explosionScore": 51.0,
        "velocity3s": 1.35,
        "velocity9s": 1.35,
        "volumeSurge": 4.0,
        "dailyMovePct": 15.0,
        "peakMovePct": 15.0,
        "ictFirstLift": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictScore": 31.0,
        "ictBaseRelativeMovePct": 15.0,
        "flatVerticalQuality": 61.0,
        "ictVolumeAwakening": True,
        "reason": "test",
    }


def _ict(side_move: float = 15.0, v3: float = 1.35, surge: float = 4.0):
    return SimpleNamespace(
        active=True,
        first_lift=True,
        pattern="flat_then_vertical",
        flat_then_vertical=True,
        volume_awakening=True,
        displacement=False,
        premium_fvg=False,
        session_move_pct=side_move,
        velocity_3s=v3,
        volume_surge=surge,
        base_relative_move_pct=side_move,
        base_premium=104.0,
        flat_vertical_quality=61.0,
        local_swing_base=True,
    )


def test_strong_volume_lift_is_helper_confirmed():
    from app.config import get_settings

    ok, count = _helper_confirmed_lift(
        row=_strong_alert(), ict=_ict(), snap=_snap("BULLISH"),
        event=None, settings=get_settings(),
    )
    assert ok is True
    assert count >= 3


def test_soft_near_miss_without_dynamic_helper_is_not_confirmed():
    """Weak volume (surge 2.0), no displacement/FVG -> not a 'sudden help' FTV."""
    from app.config import get_settings

    row = _strong_alert()
    row["volumeSurge"] = 2.0
    ict = _ict(surge=2.0)
    ok, _count = _helper_confirmed_lift(
        row=row, ict=ict, snap=_snap("BULLISH"), event=None, settings=get_settings(),
    )
    assert ok is False


def test_cold_lift_never_confirmed():
    from app.config import get_settings

    row = _strong_alert()
    row["velocity3s"] = 0.0
    ok, _count = _helper_confirmed_lift(
        row=row, ict=_ict(v3=0.0), snap=_snap("BULLISH"),
        event=None, settings=get_settings(),
    )
    assert ok is False


def test_watch_first_lift_enters_on_lowered_bar_when_helper_confirmed():
    with patch(
        "app.engines.dual_mode_strategy.resolve_trading_session_mode",
        return_value=("NORMAL", {}),
    ):
        ok, reason = first_lift_entry_readiness(
            snap=_snap("BULLISH"), ict=_ict(), alert=_strong_alert("WATCH", "CALL"),
            state=_state(),
        )
    assert ok is True, reason


def test_symmetric_put_first_lift_helper_confirmed():
    row = _strong_alert("WATCH", "PUT")
    with patch(
        "app.engines.dual_mode_strategy.resolve_trading_session_mode",
        return_value=("NORMAL", {}),
    ):
        ok, reason = first_lift_entry_readiness(
            snap=_snap("BEARISH"), ict=_ict(), alert=row, state=_state(),
        )
    assert ok is True, reason


def test_helper_confirmed_building_overrides_breakout_only():
    """BUILDING FTV with strong help enters even on a BREAKOUT_ONLY worst day."""
    row = _strong_alert("BUILDING", "CALL")
    with (
        patch(
            "app.engines.worst_day_itm_fade.worst_day_defensive_session_active",
            return_value=True,
        ),
        patch(
            "app.engines.worst_day_guard.session_entry_policy",
            return_value=("BREAKOUT_ONLY", {}),
        ),
        patch(
            "app.engines.dual_mode_strategy.resolve_trading_session_mode",
            return_value=("DEFENSIVE", {}),
        ),
    ):
        ok, reason = building_rip_bullish_readiness(
            snap=_snap("BULLISH"), ict=_ict(), alert=row, state=_state(),
        )
    assert ok is True, reason


def test_unhelped_building_still_blocked_on_breakout_only():
    """Without a dynamic helper, BREAKOUT_ONLY still blocks BUILDING."""
    row = _strong_alert("BUILDING", "CALL")
    row["volumeSurge"] = 2.0
    row["ictVolumeAwakening"] = False
    ict = _ict(surge=2.0)
    ict.volume_awakening = False
    with (
        patch(
            "app.engines.worst_day_itm_fade.worst_day_defensive_session_active",
            return_value=True,
        ),
        patch(
            "app.engines.worst_day_guard.session_entry_policy",
            return_value=("BREAKOUT_ONLY", {}),
        ),
        patch(
            "app.engines.dual_mode_strategy.resolve_trading_session_mode",
            return_value=("NORMAL", {}),
        ),
    ):
        ok, reason = building_rip_bullish_readiness(
            snap=_snap("BULLISH"), ict=ict, alert=row, state=_state(),
        )
    assert ok is False
    assert "worst_day" in reason or "policy" in reason
