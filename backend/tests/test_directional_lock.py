"""Directional lock — aligned default; CE↔PE switch only on full confirmation."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.directional_lock import (
    check_directional_side_lock,
    check_directional_side_lock_simple,
    market_direction,
    record_trade_side,
    reset_directional_lock,
    session_locked_side,
    side_switch_confirmed,
)
from app.models.schemas import (
    Breadth,
    ExplosiveRunner,
    MarketPhase,
    Orderflow,
    RunnerSignal,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.directional_side_lock_enabled = True
    s.directional_sticky_per_symbol = True
    s.directional_lock_use_chart = True
    s.directional_lock_block_chart_counter = True
    s.directional_switch_min_confirmations = 5
    s.directional_switch_min_velocity_pct = 2.5
    s.directional_switch_min_explosion_score = 55.0
    s.directional_switch_min_runner_score = 60.0
    s.directional_switch_min_trend_strength = 50.0
    return s


def _snap(
    symbol: str = "NIFTY",
    bias: str = "BULLISH",
    chart_dir: str = "NEUTRAL",
    *,
    chart: SpotChart | None = None,
    velocity: float = 0.0,
    explosion_side: str = "",
    explosion_score: float = 0.0,
) -> SymbolSnapshot:
    spot_chart = chart or SpotChart(direction=chart_dir)
    snap = SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        breadth=Breadth(bias=bias, aligned=bias in ("BULLISH", "BEARISH")),
        spotChart=spot_chart,
        orderflow=Orderflow(tickMomentum=1.0 if bias == "BULLISH" else -1.0),
    )
    if velocity > 0 and explosion_side:
        snap.topExplosion = {
            "side": explosion_side,
            "velocity3s": velocity,
            "explosionScore": explosion_score,
        }
        snap.explosiveRunner = ExplosiveRunner(
            candidate=True,
            score=explosion_score,
            side=Side.CALL if explosion_side == "CALL" else Side.PUT,
            strike=24000,
            premium=100,
            signal=RunnerSignal(premiumVelocityPct=velocity, score=explosion_score),
        )
        snap.explosiveRunnerWatchlist = [
            {"side": explosion_side, "premiumVelocityPct": velocity, "score": explosion_score},
        ]
    return snap


@patch("app.engines.directional_lock.get_settings", _settings)
def test_aligned_call_on_bullish_passes():
    blocked, reason = check_directional_side_lock("NIFTY", Side.CALL, _snap(bias="BULLISH"))
    assert not blocked
    assert reason == "ok"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_unconfirmed_put_on_bullish_blocked():
    blocked, reason = check_directional_side_lock("NIFTY", Side.PUT, _snap(bias="BULLISH"))
    assert blocked
    assert "needs_confirmation" in reason or "switch" in reason or "hard_block" in reason


@patch("app.engines.directional_lock.get_settings", _settings)
def test_confirmed_bearish_flip_allows_put_switch():
    reset_directional_lock()
    record_trade_side("NIFTY", Side.CALL, _snap(bias="BULLISH"))

    bearish_chart = SpotChart(
        direction="BEARISH",
        emaBias="BEARISH",
        candleBias="BEARISH",
        momentum5Pct=-0.08,
        momentum15Pct=-0.1,
        trendStrength=65,
        belowPoc=True,
    )
    snap = _snap(
        bias="BEARISH",
        chart=bearish_chart,
        velocity=3.5,
        explosion_side="PUT",
        explosion_score=72,
    )
    snap.orderflow = Orderflow(tickMomentum=-2.0, deltaVelocity=-1.0)
    snap.breadth = Breadth(bias="BEARISH", aligned=True)

    confirmed, _, meta = side_switch_confirmed(Side.PUT, snap)
    assert confirmed
    assert len(meta["signals"]) >= 5

    blocked, reason = check_directional_side_lock("NIFTY", Side.PUT, snap)
    assert not blocked


@patch("app.engines.directional_lock.get_settings", _settings)
def test_weak_switch_blocked_while_breadth_still_bullish():
    reset_directional_lock()
    record_trade_side("NIFTY", Side.CALL, _snap(bias="BULLISH"))

    snap = _snap(bias="BULLISH", chart_dir="NEUTRAL", velocity=1.0, explosion_side="PUT", explosion_score=40)
    blocked, reason = check_directional_side_lock("NIFTY", Side.PUT, snap)
    assert blocked
    assert "switch" in reason or "needs_confirmation" in reason or "hard_block" in reason


@patch("app.engines.directional_lock.get_settings", _settings)
def test_market_direction_prefers_breadth():
    assert market_direction(_snap(bias="BULLISH", chart_dir="BEARISH")) == "BULLISH"


@patch("app.engines.directional_lock.get_settings", _settings)
def test_simple_lock_blocks_put_on_bullish_breadth():
    reset_directional_lock()
    blocked, reason = check_directional_side_lock_simple("NIFTY", Side.PUT, "BULLISH")
    assert blocked
    assert "needs_confirmation" in reason or "switch" in reason or "hard_block" in reason


@patch("app.engines.directional_lock.get_settings", _settings)
def test_reset_clears_sticky_lock():
    reset_directional_lock()
    record_trade_side("NIFTY", Side.CALL, _snap(bias="NEUTRAL"))
    assert session_locked_side("NIFTY") == "CALL"
    reset_directional_lock()
    assert session_locked_side("NIFTY") is None
