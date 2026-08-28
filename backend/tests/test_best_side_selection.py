"""Best-side selection — dominant CE/PE leg all session + power hour flip."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.best_side_selection import (
    best_side_fading_rank_waive,
    best_side_rank_adjustment,
    dominant_side_flip_bypass,
    dominant_side_qualifies_power_hour,
    resolve_dominant_side,
    resolve_global_best_side,
    side_is_dominant,
    side_velocity_metrics,
    snapshots_have_dominant_side_surge,
)
from app.engines.directional_lock import (
    check_directional_side_lock,
    record_trade_side,
    reset_directional_lock,
)
from app.engines.explosion_detector import ExplosionEvent
from app.engines.power_hour_guards import (
    candidate_qualifies_power_hour_top_trade,
    snapshots_have_power_hour_top_signal,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    base = dict(
        best_side_selection_enabled=True,
        best_side_min_velocity_3s=2.0,
        best_side_min_velocity_ratio=1.4,
        best_side_min_explosion_score=45.0,
        best_side_power_hour_min_velocity_3s=1.8,
        best_side_power_hour_min_velocity_ratio=1.3,
        best_side_directional_lock_bypass_enabled=True,
        best_side_power_hour_bypass_enabled=True,
        best_side_rank_bonus=25.0,
        best_side_counter_rank_penalty=18.0,
        best_side_global_rank_bonus=15.0,
        best_side_fading_waive_bonus=20.0,
        whipsaw_single_side_surge_bypass_enabled=True,
        whipsaw_dominant_velocity_min=2.5,
        whipsaw_dominant_velocity_ratio=1.6,
        directional_side_lock_enabled=True,
        top_moments_only_enabled=True,
        top_moments_min_grade="A",
    )
    base.update(overrides)
    return Settings(**base)


def _snap(
    *,
    call_v3: float = 0.0,
    put_v3: float = 0.0,
    call_score: float = 0.0,
    put_score: float = 0.0,
    chart_dir: str = "BEARISH",
    bias: str = "BEARISH",
) -> SymbolSnapshot:
    alerts = []
    if call_v3 > 0 or call_score > 0:
        alerts.append(
            {
                "side": "CALL",
                "strike": 24150.0,
                "tier": "BUILDING",
                "velocity3s": call_v3,
                "explosionScore": call_score,
                "tradeable": True,
            }
        )
    if put_v3 > 0 or put_score > 0:
        alerts.append(
            {
                "side": "PUT",
                "strike": 24050.0,
                "tier": "BUILDING",
                "velocity3s": put_v3,
                "explosionScore": put_score,
                "tradeable": True,
            }
        )
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24180.0,
        atmStrike=24150.0,
        breadth=Breadth(bias=bias, aligned=True),
        spotChart=SpotChart(direction=chart_dir, momentum5Pct=-0.05),
        explosionAlerts=alerts,
        explosiveRunnerWatchlist=[
            {"side": "CALL", "premiumVelocityPct": call_v3, "score": call_score},
            {"side": "PUT", "premiumVelocityPct": put_v3, "score": put_score},
        ],
    )


@patch("app.engines.best_side_selection.get_settings")
def test_side_velocity_metrics_picks_call_dominant(mock_settings):
    mock_settings.return_value = _settings()
    metrics = side_velocity_metrics(_snap(call_v3=3.2, put_v3=0.4, call_score=52.0))
    assert metrics["dominantSide"] == "CALL"
    assert metrics["dominantVelocity3s"] == 3.2


@patch("app.engines.best_side_selection.get_settings")
def test_resolve_dominant_side_call_after_3pm_rip(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(call_v3=2.5, put_v3=0.3, call_score=48.0)
    side, meta = resolve_dominant_side(snap, power_hour=True)
    assert side == "CALL"
    assert meta.get("velocityOk") is True


@patch("app.engines.best_side_selection.get_settings")
@patch("app.engines.directional_lock.get_settings")
def test_directional_lock_bypass_put_to_call_on_dominant_side(
    mock_dir_settings,
    mock_best_settings,
):
    s = _settings()
    mock_dir_settings.return_value = s
    mock_best_settings.return_value = s
    reset_directional_lock()
    snap_put = _snap(put_v3=2.0, put_score=50.0)
    record_trade_side("NIFTY", Side.PUT, snap_put)

    snap_call = _snap(call_v3=2.8, put_v3=0.2, call_score=55.0, chart_dir="BEARISH")
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        premium=115.0,
        velocity_3s=2.8,
        velocity_9s=3.1,
        velocity_15s=2.0,
        volume_surge=2.5,
        explosion_score=55.0,
        tier="BUILDING",
        reason="vertical_rip",
        daily_move_pct=12.0,
        peak_move_pct=18.0,
    )
    candidate = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        score=55.0,
        tier="BUILDING",
        explosion_event=event,
        alert={"velocity3s": 2.8, "explosionScore": 55.0, "tier": "BUILDING"},
    )
    blocked, reason = check_directional_side_lock(
        "NIFTY", Side.CALL, snap_call, tier="BUILDING", candidate=candidate,
    )
    assert blocked is False, reason


@patch("app.engines.best_side_selection.get_settings")
def test_dominant_side_qualifies_power_hour_building(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(call_v3=2.2, put_v3=0.1, call_score=50.0)
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        premium=115.0,
        velocity_3s=2.2,
        velocity_9s=2.5,
        velocity_15s=1.8,
        volume_surge=2.0,
        explosion_score=50.0,
        tier="BUILDING",
        reason="afternoon_breakout",
        daily_move_pct=10.0,
        peak_move_pct=15.0,
    )
    candidate = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        snap=snap,
        explosion_event=event,
        tier="BUILDING",
        score=50.0,
        alert={"velocity3s": 2.2, "explosionScore": 50.0},
    )
    assert dominant_side_qualifies_power_hour(candidate) is True


@patch("app.engines.best_side_selection.get_settings")
@patch("app.engines.power_hour_guards.get_settings")
def test_power_hour_session_lift_on_dominant_surge(mock_ph_settings, mock_best_settings):
    s = _settings()
    mock_ph_settings.return_value = s
    mock_best_settings.return_value = s
    snaps = {"NIFTY": _snap(call_v3=2.5, put_v3=0.2, call_score=52.0)}
    assert snapshots_have_dominant_side_surge(snaps, power_hour=True) is True
    assert snapshots_have_power_hour_top_signal(snaps) is True


@patch("app.engines.best_side_selection.get_settings")
def test_best_side_rank_bonus_prefers_dominant_leg(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(call_v3=3.0, put_v3=0.2, call_score=60.0)
    call_c = SimpleNamespace(symbol="NIFTY", side=Side.CALL, snap=snap)
    put_c = SimpleNamespace(symbol="NIFTY", side=Side.PUT, snap=snap)
    snaps = {"NIFTY": snap}
    call_adj = best_side_rank_adjustment(call_c, snaps)
    put_adj = best_side_rank_adjustment(put_c, snaps)
    assert call_adj > put_adj
    assert call_adj >= 25.0


@patch("app.engines.best_side_selection.get_settings")
def test_global_best_side_across_indices(mock_settings):
    mock_settings.return_value = _settings()
    nifty = _snap(call_v3=2.5, put_v3=0.2, call_score=50.0)
    sensex = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        explosionAlerts=[
            {"side": "PUT", "velocity3s": 1.0, "explosionScore": 30.0, "tier": "BUILDING"},
        ],
    )
    sym, side, rank, _ = resolve_global_best_side(
        {"NIFTY": nifty, "SENSEX": sensex}, power_hour=True,
    )
    assert sym == "NIFTY"
    assert side == "CALL"
    assert rank > 0


@patch("app.engines.best_side_selection.get_settings")
def test_fading_waive_on_dominant_side(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(call_v3=2.6, put_v3=0.1, call_score=48.0)
    cand = SimpleNamespace(symbol="NIFTY", side=Side.CALL, snap=snap)
    assert best_side_fading_rank_waive(cand, snap) == 20.0


@patch("app.engines.best_side_selection.get_settings")
def test_weak_opposite_side_not_dominant(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(call_v3=0.5, put_v3=2.8, put_score=60.0)
    ok, _ = side_is_dominant(Side.CALL, snap)
    assert ok is False
    flip_ok, _, _ = dominant_side_flip_bypass("NIFTY", Side.CALL, snap)
    assert flip_ok is False
