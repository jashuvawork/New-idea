"""Explosion-only book: ELITE/EXPLODING only; guarded scalps off."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.trade_selector import _explosion_candidates, find_best_entry
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.explosion_elite_exploding_only = True
    s.explosion_only_trading_enabled = True
    s.explosion_only_allow_guarded_scalp = False
    s.explosion_capture_mode = True
    s.paper_simple_profit_mode = True
    s.aggressive_max_open_scalps = 2
    s.aggressive_min_explosion_score = 50
    s.swing_max_open = 1
    s.swing_trading_enabled = False
    s.edge_engine_enabled = False
    s.best_trades_only_enabled = False
    s.best_trades_explosion_only_after_losses = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(alerts):
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24000.0,
        atmStrike=24000.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=70.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.12,
            trendStrength=70,
            emaBias="BULLISH",
            candleBias="BULLISH",
            macdBias="BULLISH",
        ),
        explosionAlerts=alerts,
        suggestedTrades=[],
    )


def _alert(tier: str, score: float = 90.0):
    return {
        "id": f"{tier}-{score}",
        "tradeable": True,
        "tier": tier,
        "side": "CALL",
        "strike": 24000,
        "premium": 120.0,
        "explosionScore": score,
        "velocity3s": 4.0,
        "velocity9s": 3.0,
        "velocity15s": 2.0,
        "volumeSurge": 2.0,
        "dailyMovePct": 32.0,
        "peakMovePct": 35.0,
        "reason": "test",
        "ictBreakout": True,
        "ictScore": 40,
    }


def test_building_skipped_when_elite_exploding_only():
    settings = _settings(explosion_elite_exploding_only=True)
    snap = _snap([_alert("BUILDING", 95.0)])
    state = SimpleNamespace(openPaperTrades=[], calibrationBlocks={"CALL": False, "PUT": False})
    with patch("app.engines.trade_selector.premium_in_band", return_value=True):
        out = _explosion_candidates("NIFTY", snap, state, settings)
    assert out == []


def test_elite_admitted_when_elite_exploding_only():
    settings = _settings(explosion_elite_exploding_only=True)
    snap = _snap([_alert("ELITE", 95.0)])
    state = SimpleNamespace(
        openPaperTrades=[],
        closedPaperTrades=[],
        calibrationBlocks={"CALL": False, "PUT": False},
    )
    ict = SimpleNamespace(
        active=True,
        pattern="flat_then_vertical",
        score=40.0,
        reasons=[],
        premium_fvg=False,
        flat_then_vertical=True,
        mega_rip=False,
        volume_awakening=False,
        displacement=True,
        session_move_pct=35.0,
        velocity_3s=4.0,
        volume_surge=2.0,
        base_relative_move_pct=28.0,
        base_premium=90.0,
    )

    with (
        patch("app.engines.trade_selector.premium_in_band", return_value=True),
        patch(
            "app.engines.explosion_detector.effective_explosion_min_score",
            return_value=50.0,
        ),
        patch("app.engines.morning_premium_capture.counter_trend_entry_allowed", return_value=True),
        patch("app.engines.winner_entry_guards.chop_weak_explosion_blocks_entry", return_value=(False, "")),
        patch("app.engines.trade_selector.check_explosion_entry", return_value=(True, "ok")),
        patch("app.engines.trade_selector.index_moment_active", return_value=(False, "")),
        patch("app.engines.trade_selector.side_aligned_with_index_moment", return_value=False),
        patch("app.engines.trade_selector.index_moment_rank_bonus", return_value=0),
        patch("app.engines.trade_selector.chart_rank_adjustment", return_value=0),
        patch("app.engines.trade_selector.moneyness_rank_adjustment", return_value=0),
        patch("app.engines.rally_capture.cross_side_chase_blocked", return_value=(False, "")),
        patch("app.engines.rally_capture.runner_strike_rank_bonus", return_value=0),
        patch("app.engines.rally_capture.atm_proximity_rank_bonus", return_value=0),
        patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {})),
        patch("app.engines.ict_breakout_monitor.analyze_explosion_event_ict", return_value=ict),
        patch("app.engines.ict_breakout_monitor.ict_explosion_rank_bonus", return_value=5),
        patch("app.engines.ict_breakout_monitor.late_fade_chase_blocked", return_value=(False, "")),
        patch("app.engines.trade_selector._reentry_blocked", return_value=(False, "ok")),
    ):
        out = _explosion_candidates("NIFTY", snap, state, settings)
    assert len(out) == 1
    assert out[0].tier == "ELITE"
    assert out[0].mode == "explosion"


def test_find_best_entry_skips_scalp_under_explosion_only():
    settings = _settings(
        explosion_only_trading_enabled=True,
        explosion_only_allow_guarded_scalp=False,
    )
    snap = _snap([])
    state = SimpleNamespace(
        openPaperTrades=[],
        calibrationBlocks={"CALL": False, "PUT": False},
        closedPaperTrades=[],
    )
    scalp_cand = MagicMock()
    scalp_cand.mode = "scalp"
    scalp_cand.score = 99.0
    scalp_cand.symbol = "NIFTY"
    scalp_cand.snap = snap
    scalp_cand.pretrade_meta = {}

    with (
        patch("app.engines.trade_selector.get_settings", return_value=settings),
        patch("app.engines.trade_selector._explosion_candidates", return_value=[]),
        patch("app.engines.trade_selector._scalp_candidates", return_value=[scalp_cand]) as scalp_fn,
        patch("app.engines.trade_selector.quick_sideways_enabled", return_value=False),
        patch("app.engines.chop_day_guards.is_chop_session", return_value=False),
        patch("app.engines.pretrade_validator.collect_session_trades", return_value=[]),
    ):
        best = find_best_entry({"NIFTY": snap}, state)

    assert best is None
    scalp_fn.assert_not_called()


def test_default_config_disables_guarded_scalp():
    from app.config import Settings

    s = Settings()
    assert s.explosion_only_trading_enabled is True
    assert s.explosion_only_allow_guarded_scalp is False
    assert s.explosion_elite_exploding_only is True
