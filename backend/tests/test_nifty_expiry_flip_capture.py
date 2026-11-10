"""NIFTY expiry flip-capture waivers — armed flip unlocks near-base capture path."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.nifty_expiry_flip_capture import (
    nifty_expiry_flip_capture_armed,
    nifty_expiry_flip_near_miss_waive,
)
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _expiry_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST).isoformat(),
        marketPhase="LIVE_MARKET",
        spot=25300.0,
        dataAvailable=True,
        optionExpiry=datetime.now(IST).strftime("%Y-%m-%d"),
    )


def test_flip_armed_on_expiry_when_index_rally_bypass_true():
    settings = Settings()
    snap = _expiry_snap()
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "tier": "ELITE",
        "localBaseMovePct": 12.0,
    }
    with patch(
        "app.engines.expiry_day_guards.is_symbol_expiry_day",
        return_value=True,
    ):
        with patch(
            "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
            return_value=(True, "index_rally_side_flip", {"rallyPoints": 50}),
        ):
            armed, reason, meta = nifty_expiry_flip_capture_armed(
                "NIFTY", Side.CALL, snap, alert=alert,
            )
    assert armed is True
    assert reason == "index_rally_side_flip"
    assert meta.get("niftyExpiryFlipCapture") is True


def test_flip_not_armed_when_pad_too_wide():
    settings = Settings()
    snap = _expiry_snap()
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "tier": "ELITE",
        "localBaseMovePct": 40.0,
    }
    with patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True):
        with patch(
            "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
            return_value=(True, "index_rally_side_flip", {}),
        ):
            armed, reason, _ = nifty_expiry_flip_capture_armed(
                "NIFTY", Side.CALL, snap, alert=alert,
            )
    assert armed is False
    assert reason == "pad_out_of_band"


def test_near_miss_waive_when_flip_armed():
    settings = Settings()
    snap = _expiry_snap()
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "tier": "ELITE",
        "localBaseMovePct": 10.0,
    }
    with patch(
        "app.engines.nifty_expiry_flip_capture.nifty_expiry_flip_capture_armed",
        return_value=(True, "index_rally_side_flip", {}),
    ):
        assert nifty_expiry_flip_near_miss_waive(alert, snap=snap, settings=settings) is True


def test_afternoon_opposite_trend_suppresses_put_fade_waiver():
    settings = Settings()
    afternoon = datetime.now(IST).replace(hour=14, minute=0, second=0, microsecond=0)
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=afternoon.isoformat(),
        marketPhase="LIVE_MARKET",
        spot=25300.0,
        dataAvailable=True,
        optionExpiry=afternoon.strftime("%Y-%m-%d"),
    )
    with patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True):
        with patch(
            "app.engines.index_session_dominant_trend.index_trend_features_active",
            return_value=True,
        ):
            with patch(
                "app.engines.index_session_dominant_trend.index_session_dominant_trend",
                return_value=("RALLY", {"dominantTrend": "RALLY"}),
            ):
                from app.engines.nifty_expiry_flip_capture import (
                    nifty_expiry_opposite_trend_fade_waiver_suppressed,
                )

                blocked, reason = nifty_expiry_opposite_trend_fade_waiver_suppressed(
                    "NIFTY",
                    Side.PUT,
                    snap,
                    state=object(),
                    settings=settings,
                    now=afternoon,
                )
    assert blocked is True
    assert "rally" in reason.lower()


def test_nifty_expiry_1m_relief_put_when_slide_armed():
    from app.engines.execution_chart_monitor import resolve_nifty_expiry_1m_fade_relief

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST).isoformat(),
        marketPhase="LIVE_MARKET",
        spot=25300.0,
        dataAvailable=True,
        optionExpiry=datetime.now(IST).strftime("%Y-%m-%d"),
    )
    event = MagicMock(tier="ELITE", daily_move_pct=12.0)
    alert = {"tier": "ELITE", "localBaseMovePct": 12.0}
    with patch("app.engines.expiry_day_guards.is_symbol_expiry_day", return_value=True):
        with patch(
            "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
            return_value=(True, "index_slide_side_flip", {}),
        ):
            ok = resolve_nifty_expiry_1m_fade_relief(
                "NIFTY", Side.PUT, snap, explosion_event=event, alert=alert,
            )
    assert ok is True


def test_exec_premium_shallow_fade_ok_when_flip_bypass():
    settings = Settings()
    event = MagicMock(tier="ELITE", daily_move_pct=10.0)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=80.0,
        premium_momentum_3s=-0.2,
        premium_momentum_5s=-0.3,
        premium_direction="BEARISH",
        explosion_event=event,
        nifty_expiry_flip_bypass=True,
    )
    assert blocked is False
    assert reason == "nifty_expiry_flip_shallow_fade_ok"
