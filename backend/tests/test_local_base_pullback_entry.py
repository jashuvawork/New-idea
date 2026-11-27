"""Armed-base pullback wait — block chase fills far above ICT base (CE/PE)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app.engines.explosion_detector as ed
from app.engines.explosion_detector import _open_key
from app.engines.local_base_pullback_entry import (
    _base_premium_inr,
    local_base_pullback_blocks_entry,
)
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    PremiumChart,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _seed_session(symbol, strike, side, low, peak):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    key = _open_key(symbol, strike, side)
    ed._session_low[key] = float(low)
    ed._session_peak[key] = float(peak)
    ed._session_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")


def teardown_function(_):
    ed._session_low.clear()
    ed._session_peak.clear()


def _settings():
    s = settings_mock()
    s.local_base_pullback_entry_enabled = True
    s.local_base_pullback_max_chase_inr = 20.0
    s.local_base_pullback_max_chase_pct = 7.0
    s.local_base_pullback_min_drawdown_from_high_pct = 3.0
    return s


def _candidate(**overrides):
    base = dict(
        symbol="SENSEX",
        side=Side.CALL,
        strike=82100.0,
        tier="ELITE",
        mode="explosion",
        premium=582.0,
        alert={"ictBaseArmed": True, "ictBasePremium": 468.25},
        explosion_event=SimpleNamespace(tier="ELITE"),
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "premiumMomentum5Pct": 11.5},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_blocks_nov17_style_chase_above_base_call():
    settings = _settings()
    cand = _candidate()
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        blocked, reason, meta = local_base_pullback_blocks_entry(cand, None, settings=settings)
    assert blocked is True
    assert reason == "local_base_pullback_wait"
    assert meta["chaseAboveBaseInr"] > 20


def test_allows_when_within_chase_cap_put():
    settings = _settings()
    cand = _candidate(
        side=Side.PUT,
        premium=425.0,
        alert={"ictBaseArmed": True, "ictBasePremium": 410.0},
    )
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        blocked, reason, meta = local_base_pullback_blocks_entry(cand, None, settings=settings)
    assert blocked is False
    assert reason == "ok"
    assert meta.get("localBasePullbackFill") == "within_chase_cap"


def test_blocks_armed_launch_on_session_rip_fall_leg():
    settings = _settings()
    settings.local_base_pullback_armed_launch_respect_rip_fall = True
    cand = _candidate(
        side=Side.PUT,
        premium=429.0,
        alert={
            "ictBaseArmed": True,
            "ictArmedBaseLaunch": True,
            "ictBasePremium": 418.0,
        },
        explosion_event=SimpleNamespace(
            tier="ELITE",
            symbol="SENSEX",
            side=Side.PUT,
            strike=83600.0,
            premium=429.0,
            velocity_3s=0.4,
        ),
        liveEntryScoreMeta={"drawdownFromHighPct": -2.0, "premiumMomentum5Pct": 2.0},
    )
    _seed_session("SENSEX", 83600.0, Side.PUT, 175.0, 550.0)
    with patch(
        "app.engines.local_base_pullback_entry.get_settings", return_value=settings,
    ):
        blocked, reason, meta = local_base_pullback_blocks_entry(
            cand, None, settings=settings,
        )
    assert blocked is True
    assert reason == "explosion_session_rip_fall_entry"
    assert "armed_base_launch_waiver" not in (meta.get("localBasePullbackFill") or "")


def test_stale_armed_base_no_launch_waiver_far_above_trough():
    settings = _settings()
    settings.local_base_pullback_armed_launch_stale_trough_blocks_waiver = True
    cand = _candidate(
        side=Side.PUT,
        premium=450.0,
        alert={
            "ictBaseArmed": True,
            "ictArmedBaseLaunch": True,
            "ictBasePremium": 418.0,
            "sessionLowPremium": 175.0,
        },
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "premiumMomentum5Pct": 11.5},
    )
    with patch(
        "app.engines.local_base_pullback_entry.get_settings", return_value=settings,
    ):
        blocked, reason, _ = local_base_pullback_blocks_entry(cand, None, settings=settings)
    assert blocked is True
    assert reason == "local_base_pullback_wait"


def test_allows_armed_base_launch_above_chase_cap_ce_pe():
    settings = _settings()
    for side in (Side.CALL, Side.PUT):
        cand = _candidate(
            side=side,
            premium=57.0,
            alert={
                "ictBaseArmed": True,
                "ictArmedBaseLaunch": True,
                "ictBasePremium": 52.8,
            },
        )
        with patch(
            "app.engines.local_base_pullback_entry.get_settings", return_value=settings,
        ):
            blocked, reason, meta = local_base_pullback_blocks_entry(
                cand, None, settings=settings,
            )
        assert blocked is False
        assert reason == "ok"
        assert meta.get("localBasePullbackFill") == "armed_base_launch_waiver"


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_session_dominant_trend.index_session_dominant_trend",
    return_value=("SLIDE", {}),
)
def test_base_premium_zero_when_ict_vetoed_on_counter_leg(_m0, _m1):
    settings = _settings()
    settings.new_session_base_identify_enabled = True
    settings.ict_armed_base_require_index_participation = True
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.05),
        chartAnalysis=ChartAnalysis(consensus="BEARISH"),
    )
    cand = _candidate(
        symbol="NIFTY",
        side=Side.CALL,
        strike=25750.0,
        premium=232.0,
        alert={
            "symbol": "NIFTY",
            "side": "CALL",
            "strike": 25750.0,
            "ictBasePremium": 210.0,
            "premium": 232.0,
        },
    )
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        assert _base_premium_inr(cand, snap) == 0.0


def test_allows_after_pullback_from_session_high_ce():
    settings = _settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=8.0,
        drawdownFromHighPct=-5.0,
    )
    cand = _candidate(premium=500.0, alert={"ictBaseArmed": True, "ictBasePremium": 468.25})
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        blocked, reason, meta = local_base_pullback_blocks_entry(
            cand, None, premium_chart=chart, settings=settings,
        )
    assert blocked is False
    assert meta.get("localBasePullbackFill") == "pullback_from_high"