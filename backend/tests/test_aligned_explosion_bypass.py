"""Tests for aligned explosion rip bypass gates."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.aligned_explosion_bypass import (
    entry_interval_gap_seconds,
    is_aligned_explosion_rip,
)
from app.engines.directional_lock import (
    check_directional_side_lock,
    record_trade_side,
    reset_directional_lock,
)
from app.engines.explosion_detector import ExplosionEvent
from app.engines.pretrade_validator import check_min_entry_interval
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(bias: str = "BULLISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77000.0,
        atmStrike=77000.0,
        tradeQualityScore=50.0,
        breadth=Breadth(bias=bias, score=65, aligned=bias != "NEUTRAL"),
        spotChart=SpotChart(direction=bias, spot=77000.0, trendStrength=55.0),
    )


def _event(**kwargs) -> ExplosionEvent:
    defaults = dict(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77000.0,
        premium=140.0,
        velocity_3s=4.5,
        velocity_9s=6.0,
        velocity_15s=8.0,
        volume_surge=2.5,
        explosion_score=72.0,
        tier="EXPLODING",
        reason="rip",
        daily_move_pct=120.0,
    )
    defaults.update(kwargs)
    return ExplosionEvent(**defaults)


def _candidate(event: ExplosionEvent | None = None) -> SimpleNamespace:
    event = event or _event()
    return SimpleNamespace(
        mode="explosion",
        symbol="SENSEX",
        side=event.side,
        strike=event.strike,
        score=event.explosion_score,
        tier=event.tier,
        explosion_event=event,
        snap=_snap(),
    )


@patch("app.engines.aligned_explosion_bypass.get_settings")
def test_aligned_explosion_rip_detects_breadth_aligned_call(mock_settings):
    s = mock_settings.return_value
    s.aligned_explosion_rip_bypass_enabled = True
    s.aligned_explosion_rip_min_score = 55.0
    s.aligned_explosion_rip_min_velocity_3s = 2.0
    s.aligned_explosion_rip_min_velocity_9s = 3.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_min_score = 38.0

    ok, reason = is_aligned_explosion_rip(_candidate(), _snap("BULLISH"))
    assert ok is True
    assert reason == "aligned_explosion_rip"


@patch("app.engines.aligned_explosion_bypass.get_settings")
def test_aligned_explosion_rip_rejects_counter_trend_put_on_bullish(mock_settings):
    s = mock_settings.return_value
    s.aligned_explosion_rip_bypass_enabled = True
    s.aligned_explosion_rip_min_score = 55.0
    s.aligned_explosion_rip_min_velocity_3s = 2.0
    s.aligned_explosion_rip_min_velocity_9s = 3.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_min_score = 38.0

    ok, _ = is_aligned_explosion_rip(_candidate(_event(side=Side.PUT)), _snap("BULLISH"))
    assert ok is False


@patch("app.engines.pretrade_validator.get_settings")
def test_entry_interval_bypass_for_aligned_rip(mock_settings):
    s = mock_settings.return_value
    s.min_seconds_between_entries = 180
    s.post_exit_min_seconds = 120
    s.post_loss_exit_min_seconds = 300
    s.chop_session_entry_interval_seconds = 300
    s.quick_sideways_min_seconds_between_entries = 120
    s.aligned_explosion_rip_interval_seconds = 30

    state = AutoTraderState(
        lastExit={
            "at": datetime.now(IST).isoformat(),
            "pnlInr": 500.0,
        },
    )
    cand = _candidate()
    snaps = {"SENSEX": _snap()}

    with patch(
        "app.engines.aligned_explosion_bypass.is_aligned_explosion_rip",
        return_value=(True, "aligned_explosion_rip"),
    ):
        ok, reason = check_min_entry_interval(state, candidate=cand, snapshots=snaps)
    assert ok is False
    assert "aligned_rip" in reason

    gap = entry_interval_gap_seconds(aligned_rip=True)
    assert gap == 30


@patch("app.engines.directional_lock.get_settings")
def test_directional_lock_bypass_on_aligned_rip(mock_settings):
    s = mock_settings.return_value
    s.directional_side_lock_enabled = True
    s.directional_lock_aligned_rip_bypass_enabled = True
    s.directional_lock_use_chart = True
    s.directional_lock_block_chart_counter = True
    s.directional_switch_min_confirmations = 5
    s.directional_switch_min_velocity_pct = 2.5
    s.directional_switch_min_explosion_score = 55.0
    s.directional_switch_min_runner_score = 60.0
    s.directional_switch_min_trend_strength = 50.0

    reset_directional_lock()
    snap = _snap("BULLISH")
    record_trade_side("SENSEX", Side.PUT, snap)

    blocked, reason = check_directional_side_lock(
        "SENSEX", Side.CALL, snap, tier="EXPLODING", candidate=_candidate(),
    )
    assert blocked is False


@patch("app.engines.expiry_day_guards.get_settings")
def test_expiry_session_enables_faster_entry_scan(mock_settings):
    from app.engines.expiry_day_guards import any_expiry_session_active, refresh_expiry_session
    from app.engines.session_timing import effective_entry_scan_interval_ms
    from app.models.schemas import MarketPhase, SymbolSnapshot
    from datetime import datetime
    from zoneinfo import ZoneInfo

    s = mock_settings.return_value
    s.entry_scan_interval_ms = 2000
    s.expiry_entry_scan_interval_ms = 750
    s.expiry_day_guards_enabled = True
    s.explosion_open_entry_enabled = True
    s.explosion_open_scan_interval_ms = 1000

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=datetime.now(IST).strftime("%Y-%m-%d"),
    )
    refresh_expiry_session({"SENSEX": snap})
    assert any_expiry_session_active() is True
    with patch("app.engines.session_timing.in_open_premium_window", return_value=False):
        assert effective_entry_scan_interval_ms() == 750
