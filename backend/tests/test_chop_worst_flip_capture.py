"""Chop/WORST flip capture — CE + PE symmetric (V / FTV / new base after session turn)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.chop_live_guards import chop_live_entry_blocked
from app.engines.chop_worst_flip_capture import (
    chop_worst_flip_chop_live_waive_ok,
    chop_worst_flip_selector_preserve,
    flip_structural_evidence,
    session_flip_supports_side,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _chop_state() -> AutoTraderState:
    return AutoTraderState(
        dailyStrategy={"dayMode": "CHOP + RALLY", "dayType": "WORST"},
        chopGuards={"worstDayGuard": {"isWorst": True}},
    )


def _snap(symbol: str = "SENSEX", *, direction: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=72800.0,
        atmStrike=72800.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="NEUTRAL", score=48.0, aligned=False),
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=-0.08 if direction == "BEARISH" else 0.12,
            trendStrength=50.0,
            emaBias=direction,
            candleBias=direction,
            macdBias="NEUTRAL",
        ),
        explosionAlerts=[],
        suggestedTrades=[],
    )


def _candidate(side: Side, *, session_move: float, v3: float, moment: str) -> SimpleNamespace:
    alert = {
        "tier": "ELITE",
        "side": side.value,
        "symbol": "SENSEX",
        "strike": 72800.0,
        "momentType": moment,
        "vRipReady": moment.startswith("v_rip"),
        "explosionScore": 100.0,
        "velocity3s": v3,
        "dailyMovePct": session_move,
        "peakMovePct": session_move,
        "localBaseMovePct": 10.0,
        "ictBaseArmed": True,
    }
    event = SimpleNamespace(
        daily_move_pct=session_move,
        peak_move_pct=session_move,
        velocity_3s=v3,
        tier="ELITE",
        explosion_score=100.0,
    )
    return SimpleNamespace(
        mode="explosion",
        symbol="SENSEX",
        side=side,
        strike=72800.0,
        alert=alert,
        explosion_event=event,
        pretrade_meta={
            "sessionMovePct": session_move,
            "velocity3s": v3,
            "causalRanking": {
                "evidence": {
                    "momentType": moment,
                    "vRipReady": True,
                    "localBaseMovePct": 10.0,
                },
            },
        },
    )


@patch(
    "app.engines.chop_worst_flip_capture.session_flip_supports_side",
    return_value=(False, "no_flip", {}),
)
def test_extended_v_rip_waive_denied_without_flip(_mock_flip):
    """Oct 14-style: high session move, v3=0, no flip — chop-live must not waive."""
    settings = settings_mock(chop_worst_flip_capture_enabled=True)
    state = _chop_state()
    snap = _snap()
    for side in (Side.PUT, Side.CALL):
        cand = _candidate(side, session_move=29.0, v3=0.0, moment="v_rip_session_low")
        ok, reason = chop_worst_flip_chop_live_waive_ok(
            cand, snap, state, snapshots={"SENSEX": snap}, settings=settings,
        )
        assert not ok, side
        assert reason == "chop_worst_extended_need_active_flip"


@patch(
    "app.engines.chop_worst_flip_capture.session_flip_supports_side",
)
def test_flip_waive_ok_with_velocity_and_structure(mock_flip):
    mock_flip.return_value = (True, "slide_dominant", {"dominantTrendFlipped": True})
    settings = settings_mock(chop_worst_flip_capture_enabled=True)
    state = _chop_state()
    snap = _snap()
    for side, moment in (
        (Side.PUT, "v_rip_session_low"),
        (Side.CALL, "v_rip_session_high"),
    ):
        cand = _candidate(side, session_move=29.0, v3=1.9, moment=moment)
        ok, reason = chop_worst_flip_chop_live_waive_ok(
            cand, snap, state, snapshots={"SENSEX": snap}, settings=settings,
        )
        assert ok, side
        assert "chop_worst_flip" in reason


def test_flip_structural_evidence_ce_pe_parity():
    for moment in ("v_rip_session_low", "v_rip_session_high", "armed_base_launch"):
        assert flip_structural_evidence({"momentType": moment, "tier": "ELITE"}, {})


@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {"dominantTrendFlipped": True, "indexTrendFlip": "slide_dominant"}),
)
def test_session_flip_supports_put_on_slide(_mock_trend):
    snap = _snap(direction="BEARISH")
    ok, tag, _ = session_flip_supports_side("SENSEX", Side.PUT, snap, _chop_state())
    assert ok
    assert "slide" in tag or "flip" in tag or tag == "dominant_trend_flipped"


@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("RALLY", {"dominantTrendFlipped": True, "indexTrendFlip": "rally_dominant"}),
)
def test_session_flip_supports_call_on_rally(_mock_trend):
    snap = _snap(direction="BULLISH")
    ok, tag, _ = session_flip_supports_side("SENSEX", Side.CALL, snap, _chop_state())
    assert ok


@patch(
    "app.engines.chop_worst_flip_capture.chop_worst_context_active",
    return_value=True,
)
@patch(
    "app.engines.chop_worst_flip_capture.session_flip_supports_side",
    return_value=(True, "slide_dominant", {}),
)
def test_selector_preserve_elite_v_rip_outside_open(_mock_side, _mock_ctx):
    settings = settings_mock()
    state = _chop_state()
    snap = _snap()
    alert = {
        "tier": "ELITE",
        "side": "PUT",
        "symbol": "SENSEX",
        "explosionScore": 100.0,
        "velocity3s": 2.0,
        "momentType": "v_rip_session_low",
        "vRipReady": True,
    }
    assert chop_worst_flip_selector_preserve(
        alert, snap, state, {"SENSEX": snap}, settings=settings,
    )


@patch(
    "app.engines.chop_worst_flip_capture.chop_worst_flip_chop_live_waive_ok",
    return_value=(False, ""),
)
def test_chop_live_extended_chase_blocks_when_waive_denied(_mock_waive):
    settings = settings_mock(
        chop_live_guards_enabled=True,
        chop_live_block_extended_chase=True,
        chop_live_extended_chase_min_session_move_pct=28.0,
        chop_live_min_trusted_local_base_pct=15.0,
        live_paper_parity_enabled=False,
    )
    state = _chop_state()
    snap = _snap()
    cand = _candidate(Side.PUT, session_move=30.0, v3=0.0, moment="v_rip_session_low")
    with patch(
        "app.engines.chop_live_guards.chop_live_guard_day_active",
        return_value=True,
    ):
        blocked, reason, meta = chop_live_entry_blocked(
            cand, snap, state, snapshots={"SENSEX": snap},
        )
    assert blocked
    assert reason.startswith("chop_live_extended_chase_pad_")
    assert not meta.get("chopLiveNearBaseWaive")
