"""Every trade places SL at local support (premium base / index structure)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chart_exit_levels import (
    _pick_local_support_pts,
    _premium_local_support_stop_pts,
    compute_chart_exit_levels,
    merge_chart_into_exit_plan,
)
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Side,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(
    *,
    ict_base: float = 0.0,
    pivots: dict | None = None,
    institutional: dict | None = None,
    premium: float = 80.0,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77500.0,
        atmStrike=77500.0,
        breadth=Breadth(bias="BULLISH", score=80, aligned=True),
        topExplosion={
            "side": "CALL",
            "premium": premium,
            "ictBasePremium": ict_base,
            "tier": "ELITE",
        },
        chartAnalysis=ChartAnalysis(
            consensus="BULLISH",
            pivots=pivots or {"S1": 77420.0, "S2": 77350.0, "P": 77480.0},
            fibonacci={"retracement": {"0.382": 77450.0, "0.618": 77380.0}},
            ichimoku={"cloudBottom": 77400.0, "kijun": 77430.0, "tenkan": 77460.0},
            institutional=institutional or {"lastSwingLow": 77390.0, "liquidityPools": [77390.0]},
        ),
    )


def _settings(**overrides):
    s = MagicMock()
    s.chart_exit_levels_enabled = True
    s.scalp_stop_min_points = 2.5
    s.scalp_trail_step_points = 2.0
    s.quick_trail_promote_min_confidence = 46.8
    s.all_day_min_chart_confidence = 48.2
    s.chart_confidence_half_tp_lock_pct = 0.50
    s.chart_exit_max_target_points = 80.0
    s.chart_exit_max_index_structure_pct = 0.04
    s.exit_sl_use_local_support = True
    s.exit_sl_local_support_buffer_pct = 0.02
    s.exit_sl_local_support_min_premium_frac = 0.06
    s.exit_sl_local_support_min_points = 5.0
    s.explosion_stop_max_pct_of_premium = 0.18
    s.explosion_stop_abs_max_points = 40.0
    s.explosion_chart_stop_min_natural_frac = 0.85
    s.chart_confidence_raw_min = 40.0
    s.chart_confidence_raw_max = 200.0
    s.chart_confidence_out_min = 40.0
    s.chart_confidence_out_max = 100.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_pick_local_support_skips_noise_near_structure():
    # 3pt noise + 14pt real support → use 14
    assert _pick_local_support_pts([3.0, 14.0, 22.0], 80.0) == 14.0


def test_pick_local_support_widens_when_all_noise():
    # All below min (~5) → take farthest, not nearest toy
    assert _pick_local_support_pts([2.0, 3.5, 4.0], 80.0) == 4.0


def test_premium_local_support_from_ict_base():
    snap = _snap(ict_base=62.0, premium=80.0)
    pts = _premium_local_support_stop_pts(snap, Side.CALL, 80.0)
    assert pts == 18.0  # 80 - 62


@patch("app.engines.chart_exit_levels.chart_trade_confidence_with_raw")
@patch("app.engines.chart_exit_levels.get_settings")
def test_compute_chart_exit_uses_local_support(mock_settings, mock_conf):
    mock_settings.return_value = _settings()
    mock_conf.return_value = (70.0, 140.0, ["mtf"])

    levels = compute_chart_exit_levels(
        _snap(ict_base=60.0, premium=80.0),
        Side.CALL,
        80.0,
        base_stop=8.0,
        base_target=12.0,
    )
    # Premium local support 20pt + 2% buffer; must clear toy ~8pt
    assert levels.stopPoints >= 18.0, levels.stopPoints
    assert "sl_at_local_support" in levels.sources
    assert "premium_local_support_sl" in levels.sources


@patch("app.engines.chart_exit_levels.compute_chart_exit_levels")
@patch("app.engines.chart_exit_levels.get_settings")
def test_merge_places_sl_at_local_support_not_blend(mock_settings, mock_levels):
    mock_settings.return_value = _settings()
    levels = MagicMock()
    levels.confidence = 90.0
    levels.confidenceRaw = 180.0
    levels.sources = ["sl_at_local_support", "chart_structure_sl", "premium_local_support_sl"]
    levels.promoteToTrailing = True
    levels.stopPoints = 22.0
    levels.targetPoints = 25.0
    levels.targetPoints2 = 35.0
    levels.trailArmPoints = 8.0
    levels.trailKeepRatio = 0.65
    levels.trailStepPoints = 3.5
    levels.microTargetPoints = 3.0
    levels.to_dict.return_value = {"stopPoints": 22.0}
    mock_levels.return_value = levels

    base = {
        "stopPoints": 12.0,
        "targetPoints": 25.0,
        "trailArmPoints": 8.0,
        "trailKeepRatio": 0.65,
        "trailStepPoints": 3.5,
        "microTargetPoints": 3.0,
        "naturalStopPoints": 12.0,
        "reasoning": [],
    }
    merged = merge_chart_into_exit_plan(base, _snap(), Side.CALL, 80.0)
    # max(12, 22) — not a 72% blend toward anything smaller
    assert merged["stopPoints"] >= 22.0, merged["stopPoints"]
    assert merged["localSupportStopPoints"] == 22.0
    assert any("local support" in r.lower() for r in merged["reasoning"])
