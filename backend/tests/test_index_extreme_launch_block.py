"""Pre-entry index-extreme + premium launch momentum (Nov25 83600 PE class)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.execution_order_preflight import execution_order_preflight_blocked
from app.engines.index_extreme_launch_block import index_extreme_launch_preflight_blocked
from app.models.schemas import MarketPhase, PremiumChart, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap_sensex_at_high(*, mom5: float = 0.07, direction: str = "BULLISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=84147.0,
        spotChart=SpotChart(
            direction=direction,
            spot=84147.0,
            momentum5Pct=mom5,
            macdBias="BEARISH",
            rsi=66.0,
        ),
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_blocks_put_at_session_high_weak_index_mom(mock_ext):
    mock_ext.return_value = {"hi": 84166.99, "lo": 83380.75, "last": 84147.43, "open": 83436.0}
    settings = Settings()
    settings.pre_entry_index_extreme_block_enabled = True
    settings.execution_order_preflight_min_live_score_recheck = False
    snap = _snap_sensex_at_high(mom5=0.07, direction="BULLISH")
    prem = PremiumChart(lastPremium=200.0, momentum5Pct=2.0, momentum3Pct=0.5)
    with patch(
        "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
        return_value=(False, "slide_too_small", {}),
    ):
        blocked, reason, meta = index_extreme_launch_preflight_blocked(
            Side.PUT,
            snap,
            premium_chart=prem,
            alert={"symbol": "SENSEX"},
            settings=settings,
        )
    assert blocked is True
    assert reason in (
        "exec_preflight_put_at_session_high_weak_index",
        "exec_preflight_put_bullish_chart_at_high",
    )
    assert meta.get("offSessionHighPct", 99) < 1.0


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_blocks_call_at_session_low_weak_index_mom(mock_ext):
    mock_ext.return_value = {"hi": 25000.0, "lo": 24800.0, "last": 24802.0, "open": 24900.0}
    settings = Settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24802.0,
        spotChart=SpotChart(direction="BEARISH", spot=24802.0, momentum5Pct=-0.01),
    )
    with patch(
        "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
        return_value=(False, "rally_too_small", {}),
    ):
        blocked, reason, _ = index_extreme_launch_preflight_blocked(
            Side.CALL,
            snap,
            premium_chart=PremiumChart(lastPremium=120.0, momentum5Pct=2.0),
            alert={"symbol": "NIFTY"},
            settings=settings,
        )
    assert blocked is True
    assert reason == "exec_preflight_call_at_session_low_weak_index"


def test_blocks_high_premium_weak_premium_mom5_without_snap():
    settings = Settings()
    blocked, reason, _ = index_extreme_launch_preflight_blocked(
        Side.PUT,
        None,
        premium_chart=PremiumChart(lastPremium=429.0, momentum5Pct=0.5),
        settings=settings,
    )
    assert blocked is True
    assert reason == "exec_preflight_weak_premium_launch_mom5"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_put_at_high_waived_when_slide_flip_ok(mock_ext):
    mock_ext.return_value = {"hi": 84166.0, "lo": 83380.0, "last": 84147.0, "open": 83400.0}
    snap = _snap_sensex_at_high(mom5=0.02, direction="NEUTRAL")
    prem = PremiumChart(lastPremium=200.0, momentum5Pct=3.5)
    with patch(
        "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
        return_value=(True, "index_slide_side_flip", {"slidePoints": 200}),
    ):
        blocked, reason, _ = index_extreme_launch_preflight_blocked(
            Side.PUT,
            snap,
            premium_chart=prem,
            alert={"symbol": "SENSEX"},
            settings=Settings(),
        )
    assert blocked is False
    assert reason == "ok"


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_preflight_wires_index_extreme_block(mock_ext):
    mock_ext.return_value = {"hi": 84166.0, "lo": 83380.0, "last": 84147.0, "open": 83400.0}
    settings = Settings()
    settings.execution_order_preflight_min_live_score_recheck = False
    cand = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=83600.0,
        alert={"symbol": "SENSEX", "side": "PUT", "strike": 83600.0},
        explosion_event=None,
    )
    snap = _snap_sensex_at_high(mom5=0.07, direction="BULLISH")
    prem = PremiumChart(lastPremium=429.35, momentum5Pct=0.715, momentum3Pct=0.4)
    with patch(
        "app.engines.index_rally_side_flip.index_rally_side_flip_bypass",
        return_value=(False, "no_slide", {}),
    ):
        blocked, reason, meta = execution_order_preflight_blocked(
            cand, snap, premium_chart=prem, settings=settings,
        )
    assert blocked is True
    assert "exec_preflight_put" in reason or reason == "exec_preflight_weak_premium_launch_mom5"
    assert meta.get("indexExtremeLaunch")