"""PM index-confirmed lift waivers — Nov 5 SENSEX 79000 CE extended-session + HTF oppose."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.mtf_chart_analysis import (
    TimeframeChartRead,
    _premium_htf_oppose_allows_entry,
    index_mtf_anchor_aligned,
    validate_mtf_scalp,
)
from app.engines.premium_vertical_chase_guard import (
    index_lift_waives_extended_session_top_block,
    premium_vertical_chase_blocks_entry,
)
from app.models.schemas import PremiumChart, Side, SymbolSnapshot


def _symmetric_settings() -> Settings:
    s = Settings()
    s.premium_vertical_chase_block_enabled = True
    s.premium_vertical_chase_legacy_profile_only = False
    s.symmetric_best_trade_capture_enabled = True
    s.premium_extended_session_chase_block_enabled = True
    s.premium_extended_session_index_lift_waiver_enabled = True
    s.premium_extended_session_index_lift_max_local_pad_pct = 22.0
    s.execution_premium_htf_oppose_index_anchor_bypass_enabled = True
    return s


def test_index_mtf_anchor_aligned_call():
    index_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BULLISH", momentumPct=0.5),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=0.4),
    }
    assert index_mtf_anchor_aligned(Side.CALL, index_mtf)
    index_mtf["5m"] = TimeframeChartRead(label="5m", direction="BEARISH", momentumPct=-1.0)
    assert not index_mtf_anchor_aligned(Side.CALL, index_mtf)


def test_htf_oppose_waived_with_index_anchor_bypass():
    settings = _symmetric_settings()
    premium_mtf = {
        "1h": TimeframeChartRead(label="1h", direction="BEARISH", trendStrength=25.0),
        "4h": TimeframeChartRead(label="4h", direction="BEARISH", trendStrength=22.0),
    }
    ok, reason = _premium_htf_oppose_allows_entry(
        Side.CALL,
        premium_mtf,
        settings,
        index_anchor_htf_bypass=True,
    )
    assert ok and reason == "ok"


@patch("app.engines.index_confirmed_local_base.index_confirmed_local_base", return_value=True)
def test_nov5_shape_extended_session_waiver_allows_fill(mock_iclb):
    settings = _symmetric_settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=95.0,
        drawdownFromHighPct=0.0,
    )
    snap = SimpleNamespace(spot=79200.0, spotChart=MagicMock(), dataAvailable=True)
    cand = SimpleNamespace(
        symbol="SENSEX",
        side=Side.CALL,
        strike=79000.0,
        snap=snap,
        alert={
            "tier": "ELITE",
            "premium": 285.0,
            "sessionPeakPremium": 290.0,
            "sessionLowPremium": 180.0,
            "localBaseMovePct": 12.0,
            "ictFirstLift": True,
        },
        pretrade_meta={
            "causalRanking": {"localBaseMovePct": 12.0, "ictBaseArmed": True},
        },
    )
    with patch(
        "app.engines.premium_vertical_chase_guard._is_afternoon_extended_window",
        return_value=True,
    ), patch(
        "app.engines.premium_vertical_chase_guard._at_structural_base_bypass",
        return_value=(True, "near_base_v"),
    ):
        blocked, reason, meta = premium_vertical_chase_blocks_entry(
            cand, snap, premium_chart=chart, settings=settings,
        )
    assert not blocked, (reason, meta)
    assert meta.get("indexLiftExtendedSessionWaiver") or meta.get("premiumChaseBypass")


@patch("app.engines.index_confirmed_local_base.index_confirmed_local_base", return_value=False)
def test_nov3_pm_session_top_still_blocks_without_index_confirm(mock_iclb):
    """Nov 3 23550 CE @ session top — keep hard block when index is not confirming."""
    settings = _symmetric_settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=95.0,
        drawdownFromHighPct=0.0,
    )
    cand = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23550.0,
        snap=None,
        alert={
            "tier": "ELITE",
            "premium": 180.25,
            "sessionPeakPremium": 195.0,
            "sessionLowPremium": 12.0,
            "localBaseMovePct": 12.0,
        },
        pretrade_meta={"causalRanking": {"localBaseMovePct": 12.0}},
    )
    with patch(
        "app.engines.premium_vertical_chase_guard._is_afternoon_extended_window",
        return_value=True,
    ), patch(
        "app.engines.premium_vertical_chase_guard._at_structural_base_bypass",
        return_value=(True, "near_base_v"),
    ), patch(
        "app.engines.index_tick_helpers.evaluate_index_tick_helpers",
    ) as mock_idx:
        mock_idx.return_value = SimpleNamespace(confirming=False, tick_spike=False)
        blocked, reason, _ = premium_vertical_chase_blocks_entry(
            cand, None, premium_chart=chart, settings=settings,
        )
    assert blocked
    assert reason == "premium_extended_session_near_base_chase"


@patch("app.engines.mtf_chart_analysis.get_settings")
def test_validate_mtf_scalp_htf_bypass_flag(mock_gs):
    settings = Settings()
    settings.execution_mtf_enabled = True
    settings.execution_mtf_min_align = 2
    settings.execution_mtf_block_htf_conflict = False
    settings.execution_chart_premium_check_enabled = False
    mock_gs.return_value = settings
    index_mtf = {
        "1m": TimeframeChartRead(label="1m", direction="BULLISH", momentumPct=0.2),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", momentumPct=0.2),
    }
    premium_mtf = {
        "1h": TimeframeChartRead(label="1h", direction="BEARISH", trendStrength=30.0),
        "4h": TimeframeChartRead(label="4h", direction="BEARISH", trendStrength=30.0),
    }
    ok, reason, _ = validate_mtf_scalp(
        Side.CALL,
        index_mtf,
        premium_mtf,
        index_anchor_htf_bypass=True,
    )
    assert ok, reason
