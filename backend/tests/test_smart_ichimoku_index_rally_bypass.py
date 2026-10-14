"""Smart Ichimoku cloud gate waived on a confirmed index rally/slide (Oct 13 NIFTY open V-rip)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.smart_ichimoku import ichimoku_break_supports_side
from app.models.schemas import Breadth, ChartAnalysis, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
SESSION_LO, SESSION_HI = 22300.0, 22720.0


def _settings(**overrides) -> Settings:
    base = dict(
        october_frozen_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        smart_ichimoku_flat_vertical_confirm_enabled=True,
        smart_ichimoku_index_rally_bypass_enabled=True,
        index_rally_side_flip_enabled=True,
    )
    base.update(overrides)
    return Settings(**base)


def _case(side: Side, *, move_pts: float = 200.0, aligned: bool = True):
    """Lagging cloud against the side while the index moves hard with it."""
    bull = side == Side.CALL
    spot = SESSION_LO + move_pts if bull else SESSION_HI - move_pts
    up = bull == aligned
    ich = {
        "priceVsCloud": "BELOW" if bull else "ABOVE",
        "breakSide": "NONE",
        "breakProbability": 0.0,
        "breakConfirmed": False,
        "smartBias": "BEARISH" if bull else "BULLISH",
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=round(spot / 50) * 50,
        breadth=Breadth(bias="BULLISH" if bull else "BEARISH"),
        spotChart=SpotChart(
            direction="BULLISH" if bull else "BEARISH",
            spot=spot,
            rsi=62.0 if up else 38.0,
            macdBias="BULLISH" if up else "BEARISH",
            macdHistogram=2.5 if up else -2.5,
            momentum5Pct=0.15 if up else -0.15,
        ),
        chartAnalysis=ChartAnalysis(consensus="NEUTRAL", ichimoku=ich),
    )
    return snap, spot


def _run(side: Side, s: Settings, **kw):
    snap, spot = _case(side, **kw)
    with patch("app.engines.smart_ichimoku.get_settings", lambda: s), patch(
        "app.config.get_settings", lambda: s
    ), patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(SESSION_HI, SESSION_LO, spot),
    ):
        return ichimoku_break_supports_side(side, snap, require_confirmed=True)


BLOCKED = {Side.CALL: "smart_ichimoku_cloud_below_not_above", Side.PUT: "smart_ichimoku_cloud_above_not_below"}
WAIVED = {
    Side.CALL: "smart_ichimoku_waived_index_rally_side_flip",
    Side.PUT: "smart_ichimoku_waived_index_slide_side_flip",
}


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_legacy_cloud_gate_blocks_confirmed_index_move(side):
    ok, reason = _run(side, _settings(smart_ichimoku_index_rally_bypass_enabled=False))
    assert (ok, reason) == (False, BLOCKED[side])


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_confirmed_index_move_waives_lagging_cloud(side):
    ok, reason = _run(side, _settings())
    assert (ok, reason) == (True, WAIVED[side])


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_small_move_keeps_cloud_gate(side):
    ok, reason = _run(side, _settings(), move_pts=20.0)
    assert (ok, reason) == (False, BLOCKED[side])


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_momentum_against_side_keeps_cloud_gate(side):
    ok, reason = _run(side, _settings(), aligned=False)
    assert (ok, reason) == (False, BLOCKED[side])


def test_flag_off_by_default_and_on_in_frozen_overlay():
    from pathlib import Path

    assert Settings().smart_ichimoku_index_rally_bypass_enabled is False
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "SMART_ICHIMOKU_INDEX_RALLY_BYPASS_ENABLED=true" in overlay.read_text()
