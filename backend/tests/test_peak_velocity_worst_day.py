"""Peak velocity bypass on worst-day breakout gate + faded rip caution."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import app.engines.explosion_detector as explosion_detector
from app.engines.explosion_detector import (
    ExplosionEvent,
    _open_key,
    effective_breakout_velocities,
)
from app.engines.explosion_entry_guards import (
    cap_faded_rip_lots,
    detect_faded_vertical_rip,
)
from app.engines.worst_day_guard import worst_day_allows_candidate
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings() -> MagicMock:
    s = MagicMock()
    s.worst_day_breakout_min_rank = 68.0
    s.worst_day_breakout_min_velocity_3s = 2.5
    s.worst_day_breakout_min_symbol_tqs = 45.0
    s.worst_day_breakout_require_chart_align = True
    s.worst_day_breakout_peak_velocity_bypass_enabled = True
    s.worst_day_breakout_tiers_csv = "ELITE,EXPLODING"
    s.peak_move_explosion_min_pct = 35.0
    s.velocity_peak_decay_seconds = 180
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.explosion_faded_rip_caution_enabled = True
    s.explosion_faded_rip_min_peak_pct = 35.0
    s.explosion_faded_rip_max_live_velocity_3s = 0.5
    s.explosion_faded_rip_lot_cap = 8
    s.explosion_faded_rip_tighter_stop_mult = 0.85
    return s


def _seed_peak_velocity(symbol: str, strike: float, side: Side, peak_v3: float) -> None:
    explosion_detector._session_date = datetime.now(IST).strftime("%Y-%m-%d")
    explosion_detector._peak_velocity[_open_key(symbol, strike, side)] = (
        peak_v3,
        datetime.now(IST),
    )


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77400.0,
        atmStrike=77500.0,
        regime=Regime.CHOP,
        tradeQualityScore=63.0,
        breadth=Breadth(bias="BULLISH", score=60, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05, macdBias="BULLISH"),
    )


class _Cand:
    def __init__(self, event: ExplosionEvent):
        self.mode = "explosion"
        self.tier = event.tier
        self.score = event.explosion_score
        self.symbol = event.symbol
        self.side = event.side
        self.strike = event.strike
        self.premium = event.premium
        self.explosion_event = event
        self.snap = _snap()


@patch("app.config.get_settings")
def test_effective_breakout_velocity_uses_peak_when_faded(mock_settings):
    mock_settings.return_value = _settings()
    _seed_peak_velocity("SENSEX", 77600.0, Side.CALL, 5.4)

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77600.0,
        premium=41.0,
        velocity_3s=-3.2,
        velocity_9s=-1.0,
        velocity_15s=0.5,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="EXPLODING",
        reason="fade",
        daily_move_pct=70.0,
        peak_move_pct=58.0,
    )
    v3, v9, meta = effective_breakout_velocities(event)
    assert meta.get("peakVelocityBypass") is True
    assert v3 >= 5.0
    assert v9 >= 2.5


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
@patch("app.config.get_settings")
def test_worst_day_allows_exploding_call_on_peak_velocity_bypass(mock_settings, _policy):
    mock_settings.return_value = _settings()
    _seed_peak_velocity("SENSEX", 77600.0, Side.CALL, 5.4)

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77600.0,
        premium=41.0,
        velocity_3s=-3.2,
        velocity_9s=-1.0,
        velocity_15s=0.5,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="EXPLODING",
        reason="fade",
        daily_move_pct=30.0,
        peak_move_pct=58.0,
    )
    ok, reason, meta = worst_day_allows_candidate(
        _Cand(event), AutoTraderState(), {"SENSEX": _snap()}, policy="BREAKOUT_ONLY",
    )
    assert ok is True, reason
    assert meta.get("peakVelocityBypass") is True


@patch("app.config.get_settings")
def test_detect_faded_vertical_rip_and_lot_cap(mock_settings):
    mock_settings.return_value = _settings()
    _seed_peak_velocity("SENSEX", 77600.0, Side.CALL, 5.4)

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77600.0,
        premium=41.0,
        velocity_3s=-2.0,
        velocity_9s=-1.0,
        velocity_15s=0.5,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="fade",
        daily_move_pct=92.0,
        peak_move_pct=58.0,
    )
    faded, meta = detect_faded_vertical_rip(event, _snap())
    assert faded is True
    assert meta.get("fadedRipCaution") is True
    assert cap_faded_rip_lots(15) == 8
