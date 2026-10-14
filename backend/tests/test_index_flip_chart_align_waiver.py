"""Confirmed index rally (CE) / slide (PE) clears chart_not_aligned (Oct 14 afternoon flip back)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.index_rally_side_flip import index_flip_waives_chart_align
from app.engines.spot_direction import side_aligned_with_chart
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
SESSION_LO, SESSION_HI = 81000.0, 81600.0


def _settings(**overrides) -> Settings:
    base = dict(
        october_frozen_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        index_rally_side_flip_enabled=True,
        index_flip_chart_align_waiver_enabled=True,
    )
    base.update(overrides)
    return Settings(**base)


def _case(side: Side, *, move_pts: float = 250.0):
    """5m spot direction still reads the prior leg while the index has flipped hard."""
    bull = side == Side.CALL
    spot = SESSION_LO + move_pts if bull else SESSION_HI - move_pts
    m = 0.15 if bull else -0.15
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 10, 14, 13, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=70.0,
        spot=spot,
        atmStrike=round(spot / 100) * 100,
        breadth=Breadth(bias="NEUTRAL"),
        spotChart=SpotChart(
            direction="BEARISH" if bull else "BULLISH",
            spot=spot,
            rsi=58.0 if bull else 42.0,
            macdBias="BULLISH" if bull else "BEARISH",
            macdHistogram=3.0 if bull else -3.0,
            momentum5Pct=m,
            momentum10Pct=m,
            momentum15Pct=m,
        ),
    )
    return snap, spot


def _patched(s: Settings, spot: float):
    return (
        patch("app.config.get_settings", lambda: s),
        patch(
            "app.engines.index_rally_side_flip._session_extremes_and_spot",
            return_value=(SESSION_HI, SESSION_LO, spot),
        ),
    )


def _waives(side: Side, s: Settings, **kw) -> bool:
    snap, spot = _case(side, **kw)
    p1, p2 = _patched(s, spot)
    with p1, p2:
        return index_flip_waives_chart_align(side, snap, settings=s)


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_case_chart_is_not_aligned(side):
    snap, _ = _case(side)
    assert side_aligned_with_chart(side, snap.spotChart) is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_confirmed_flip_waives_chart_align(side):
    assert _waives(side, _settings()) is True


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_waiver_off_by_default(side):
    assert _waives(side, _settings(index_flip_chart_align_waiver_enabled=False)) is False
    assert Settings().index_flip_chart_align_waiver_enabled is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_small_move_does_not_waive(side):
    assert _waives(side, _settings(), move_pts=60.0) is False


def _diagnose_messages(side: Side, s: Settings) -> list[str]:
    from app.engines.auto_trader import AutoTraderState
    from app.engines.trade_selector import diagnose_missed_entries

    snap, spot = _case(side)
    strike = float(snap.atmStrike)
    snap.explosionAlerts = [{
        "symbol": "SENSEX",
        "side": side.value,
        "strike": strike,
        "premium": 300.0,
        "tier": "ELITE",
        "tradeable": True,
        "explosionScore": 90.0,
        "peakMovePct": 20.0,
        "velocity3s": 0.6,
        "velocity9s": 0.4,
    }]
    p1, p2 = _patched(s, spot)
    with p1, p2, patch("app.engines.trade_selector.get_settings", lambda: s), patch(
        "app.engines.pad_lane_capture.pad_lane_early_near_miss_waive", return_value=False,
    ), patch(
        "app.engines.early_radar_pad_capture.alert_has_early_radar_pad_ready", return_value=False,
    ):
        notes = diagnose_missed_entries({"SENSEX": snap}, AutoTraderState())
    return [str(n.get("message", "")) for n in notes]


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_diagnose_drops_chart_not_aligned_on_confirmed_flip(side):
    off = _diagnose_messages(side, _settings(index_flip_chart_align_waiver_enabled=False))
    on = _diagnose_messages(side, _settings())
    assert any("chart_not_aligned" in m for m in off)
    assert all("chart_not_aligned" not in m for m in on)
