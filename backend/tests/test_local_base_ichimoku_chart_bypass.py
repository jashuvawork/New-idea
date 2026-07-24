"""Local base overrides gap-down bearish session chart (call_vs_bearish_chart)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.local_base_chart_bypass import (
    ichimoku_supports_side,
    local_base_ichimoku_chart_bypass,
    local_base_overrides_session_chart,
    local_base_overrides_side_bias,
    local_base_structure_active,
)
from app.engines.rally_capture import (
    breadth_blocks_explosion_side,
    chart_blocks_explosion_side,
)
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.local_base_overrides_session_chart_enabled = True
    s.local_base_ichimoku_chart_bypass_enabled = True
    s.local_base_chart_bypass_require_ichimoku = False
    s.local_base_ichimoku_require_cloud = False
    s.local_base_ichimoku_max_adverse_mom5_pct = 0.12
    s.local_base_chart_bypass_min_score = 38.0
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.local_base_chart_bypass_radar_min_move_pct = 28.0
    s.local_base_overrides_bearish_breadth = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _bearish_gap_chart(*, mom5=0.01):
    return SpotChart(
        direction="BEARISH",
        momentum5Pct=mom5,
        momentum15Pct=-0.35,
        momentum30Pct=-0.55,
        trendStrength=70,
        emaBias="BEARISH",
        candleBias="NEUTRAL",
        orPosition="BELOW",
        macdBias="BEARISH",
        rsi=42,
        spot=23680.0,
    )


def _snap(*, alert=None, ichimoku_cloud="BEARISH"):
    """Default: bearish Ichimoku — local base alone must still lift the chart block."""
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.TREND_EXPANSION,
        spot=23680.0,
        atmStrike=23700.0,
        tradeQualityScore=55,
        breadth=Breadth(bias="BEARISH", score=40, aligned=False),
        spotChart=_bearish_gap_chart(),
        chartAnalysis=ChartAnalysis(
            consensus="BEARISH",
            ichimoku={
                "cloudBias": ichimoku_cloud,
                "tkCross": "BEARISH",
                "priceVsCloud": "BELOW",
            },
        ),
        explosionAlerts=[alert or {
            "side": "CALL",
            "strike": 23700.0,
            "tier": "EXPLODING",
            "explosionScore": 98.4,
            "dailyMovePct": 32.0,
            "peakMovePct": 32.0,
            "ictFlatThenVertical": True,
            "ictBreakout": True,
            "ictBaseRelativeMovePct": 30.0,
            "ictPattern": "flat_then_vertical",
            "premium": 148.0,
            "tradeable": True,
        }],
    )


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_ichimoku_supports_call_when_cloud_bullish(mock_s):
    mock_s.return_value = _settings()
    assert ichimoku_supports_side(Side.CALL, _snap(ichimoku_cloud="BULLISH")) is True


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_local_base_alone_lifts_call_vs_bearish_without_ichimoku(mock_s):
    """Jul24 23700 CE: EXPLODING off local base, Ichimoku still bearish after gap-down."""
    mock_s.return_value = _settings()
    snap = _snap(ichimoku_cloud="BEARISH")
    assert local_base_overrides_session_chart(
        Side.CALL, snap, alert=snap.explosionAlerts[0],
    ) is True


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_exploding_early_window_without_ict_flags(mock_s):
    """Radar sometimes lags ICT flags — EXPLODING + 15-40% move still counts."""
    mock_s.return_value = _settings()
    alert = {
        "side": "CALL",
        "strike": 23700.0,
        "tier": "EXPLODING",
        "explosionScore": 98.4,
        "dailyMovePct": 28.86,
        "peakMovePct": 28.86,
        "ictFlatThenVertical": False,
        "ictBreakout": False,
        "ictBaseRelativeMovePct": 0,
        "ictPattern": "watch",
        "tradeable": True,
    }
    snap = _snap(alert=alert)
    assert local_base_structure_active(Side.CALL, snap, alert=alert) is True
    assert local_base_ichimoku_chart_bypass(Side.CALL, snap, alert=alert) is True


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_bypass_rejects_without_local_base(mock_s):
    mock_s.return_value = _settings()
    alert = {
        "side": "CALL",
        "tier": "BUILDING",
        "explosionScore": 30.0,
        "dailyMovePct": 5.0,
        "ictFlatThenVertical": False,
        "ictBreakout": False,
        "ictBaseRelativeMovePct": 0,
        "ictPattern": "watch",
    }
    snap = _snap(alert=alert)
    assert local_base_ichimoku_chart_bypass(Side.CALL, snap, alert=alert) is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_bypass_rejects_hard_live_dump(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    snap.spotChart = _bearish_gap_chart(mom5=-0.20)
    assert local_base_ichimoku_chart_bypass(
        Side.CALL, snap, alert=snap.explosionAlerts[0],
    ) is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_require_ichimoku_when_flag_on(mock_s):
    mock_s.return_value = _settings(local_base_chart_bypass_require_ichimoku=True)
    snap = _snap(ichimoku_cloud="BEARISH")
    assert local_base_overrides_session_chart(
        Side.CALL, snap, alert=snap.explosionAlerts[0],
    ) is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_chart_blocks_explosion_lifted_for_23700_profile(mock_s):
    mock_s.return_value = _settings()
    snap = _snap()
    event = SimpleNamespace(
        side=Side.CALL,
        tier="EXPLODING",
        daily_move_pct=28.86,
        peak_move_pct=28.86,
        velocity_3s=3.0,
        velocity_9s=2.5,
        volume_surge=2.0,
        explosion_score=98.4,
        symbol="NIFTY",
        strike=23700.0,
        premium=148.0,
        reason="",
        volume=0,
    )
    with patch(
        "app.engines.vertical_rip_bypass.qualifies_for_vertical_rip_bypass",
        return_value=False,
    ), patch(
        "app.engines.morning_premium_capture.premium_led_explosion_bypass",
        return_value=False,
    ):
        blocked, reason = chart_blocks_explosion_side(
            Side.CALL,
            snap.spotChart,
            "EXPLODING",
            event=event,
            breadth_bias="BEARISH",
            snap=snap,
        )
    assert blocked is False


@patch("app.engines.aligned_side_guard.get_settings")
@patch("app.engines.local_base_chart_bypass.get_settings")
def test_breadth_hard_block_lifted_for_local_base_call(mock_lb, mock_ag):
    from app.engines.aligned_side_guard import breadth_hard_blocks_side

    s = _settings()
    s.breadth_hard_side_block_enabled = True
    mock_lb.return_value = s
    mock_ag.return_value = s
    snap = _snap()
    with patch(
        "app.engines.extreme_explosion_moment.is_extreme_explosion_all_in_bypass",
        return_value=False,
    ), patch(
        "app.engines.vertical_rip_bypass.vertical_rip_bypasses_hard_breadth",
        return_value=False,
    ), patch(
        "app.engines.aligned_side_guard.chart_mtf_breadth_bypass_active",
        return_value=(False, {}),
    ):
        blocked, reason = breadth_hard_blocks_side(
            Side.CALL, "BEARISH", snap=snap, alert=snap.explosionAlerts[0],
        )
    assert blocked is False


@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.rally_capture.get_settings")
def test_explosion_breadth_block_lifted_for_local_base_call(mock_rc, mock_lb):
    """Jul24 top CALL miss: explosion_call_vs_bearish_breadth on 23700 CE."""
    s = _settings()
    s.explosion_breadth_alignment_enabled = True
    mock_lb.return_value = s
    mock_rc.return_value = s
    snap = _snap()
    with patch(
        "app.engines.vertical_rip_bypass.qualifies_for_vertical_rip_bypass",
        return_value=False,
    ):
        blocked, reason = breadth_blocks_explosion_side(
            Side.CALL, "BEARISH", "EXPLODING", snap=snap, alert=snap.explosionAlerts[0],
        )
    assert blocked is False
    assert local_base_overrides_side_bias(
        Side.CALL, snap, alert=snap.explosionAlerts[0],
    ) is True


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_market_opposes_lifted_for_local_base_call(mock_lb):
    from app.engines.morning_premium_capture import _market_opposes_side

    mock_lb.return_value = _settings()
    snap = _snap()
    assert _market_opposes_side(
        Side.CALL, "BEARISH", snap.spotChart, snap=snap, alert=snap.explosionAlerts[0],
    ) is False
    # Without snap, still opposes (legacy path).
    assert _market_opposes_side(Side.CALL, "BEARISH", snap.spotChart) is True


@patch("app.engines.directional_lock.get_settings")
@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.aligned_side_guard.get_settings")
def test_directional_lock_lifted_for_local_base_call(mock_ag, mock_lb, mock_dl):
    from app.engines.directional_lock import check_directional_side_lock

    s = _settings()
    s.directional_side_lock_enabled = True
    s.breadth_hard_side_block_enabled = True
    mock_ag.return_value = s
    mock_lb.return_value = s
    mock_dl.return_value = s
    snap = _snap()
    candidate = SimpleNamespace(
        side=Side.CALL,
        alert=snap.explosionAlerts[0],
        explosion_event=None,
    )
    with patch(
        "app.engines.extreme_explosion_moment.is_extreme_explosion_all_in_bypass",
        return_value=False,
    ), patch(
        "app.engines.vertical_rip_bypass.vertical_rip_bypasses_hard_breadth",
        return_value=False,
    ), patch(
        "app.engines.aligned_side_guard.chart_mtf_breadth_bypass_active",
        return_value=(False, {}),
    ):
        blocked, reason = check_directional_side_lock(
            "NIFTY", Side.CALL, snap, tier="EXPLODING", candidate=candidate,
        )
    assert blocked is False


@patch("app.engines.local_base_chart_bypass.get_settings")
def test_bad_day_and_worst_day_alignment_via_local_base(mock_lb):
    from app.engines.bad_day_routing import _breadth_aligned as bad_aligned
    from app.engines.worst_day_guard import _breadth_aligned as worst_aligned

    mock_lb.return_value = _settings()
    snap = _snap()
    candidate = SimpleNamespace(
        side=Side.CALL,
        alert=snap.explosionAlerts[0],
        explosion_event=None,
    )
    assert bad_aligned(candidate, snap) is True
    assert worst_aligned(candidate, snap) is True
