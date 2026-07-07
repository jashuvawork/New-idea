"""PM ITM alternate index + slow bounce detection."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import pm_itm_alternate_symbol_active, pm_itm_alternate_symbols
from app.engines.expiry_day_guards import expiry_pm_itm_quick_active
from app.engines.quick_sideways import (
    detect_slow_bounce_signal,
    scan_slow_bounce_setups,
)
from app.engines.worst_day_guard import worst_day_allows_candidate, worst_day_blocks_call_scalp
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    HeatmapStrike,
    MarketPhase,
    Orderflow,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _sensex_snap(spot: float = 78200.0, tqs: float = 30.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-09",
        spot=spot,
        atmStrike=78200.0,
        regime=Regime.CHOP,
        tradeQualityScore=tqs,
        breadth=Breadth(bias="NEUTRAL", score=54, aligned=False),
        orderflow=Orderflow(tickMomentum=-5, deltaVelocity=-8, signedMomentumPct=0.15),
        spotChart=SpotChart(
            direction="NEUTRAL",
            spot=spot,
            momentum5Pct=0.02,
            trendStrength=42,
            emaBias="BEARISH",
            rsi=48.5,
            rsiBias="OVERSOLD",
            macd=-10.0,
            macdSignal=-12.0,
            macdHistogram=2.0,
            macdBias="BEARISH",
        ),
        heatmap=[
            HeatmapStrike(strike=78300.0, putLtp=171.0),
            HeatmapStrike(strike=78200.0, putLtp=130.0),
        ],
    )


class _Cand:
    def __init__(self, **kwargs):
        self.mode = kwargs.get("mode", "slow_bounce")
        self.symbol = kwargs.get("symbol", "SENSEX")
        self.side = kwargs.get("side", Side.PUT)
        self.strike = kwargs.get("strike", 78300.0)
        self.premium = kwargs.get("premium", 171.0)
        self.score = kwargs.get("score", 62.0)
        self.tier = ""
        self.snap = kwargs.get("snap", _sensex_snap())


@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["bearish_sideways"]})
@patch("app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=True)
def test_pm_itm_alternate_sensex_when_nifty_fading(mock_win, mock_exp, mock_alt, mock_fade):
    nifty = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-07",
        spot=24480.0,
        tradeQualityScore=35,
        breadth=Breadth(bias="BEARISH", score=50, aligned=False),
    )
    sensex = _sensex_snap()
    snaps = {"NIFTY": nifty, "SENSEX": sensex}
    state = AutoTraderState()

    assert "SENSEX" in pm_itm_alternate_symbols(state, snaps)
    assert pm_itm_alternate_symbol_active(sensex, state, snaps) is True
    assert expiry_pm_itm_quick_active(sensex, state, snaps) is True
    with patch("app.engines.expiry_day_guards.is_near_expiry_day", return_value=True):
        assert expiry_pm_itm_quick_active(nifty, state, snaps) is True


@patch("app.engines.quick_sideways.get_settings")
def test_detect_slow_bounce_put_signal(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_slow_bounce_enabled = True
    s.quick_sideways_slow_bounce_premium_min_inr = 90.0
    s.expiry_pm_itm_premium_max_inr = 180.0
    s.quick_sideways_slow_bounce_rsi_min = 40.0
    s.quick_sideways_slow_bounce_rsi_max = 55.0
    s.quick_sideways_slow_bounce_macd_hist_min = -15.0

    snap = _sensex_snap()
    ok, reason, meta = detect_slow_bounce_signal(snap, Side.PUT, 78300.0, 171.0)
    assert ok is True
    assert reason == "slow_bounce"
    assert meta["rsi"] == 48.5


@patch("app.engines.quick_sideways._pm_itm_active", return_value=True)
@patch("app.engines.quick_sideways.get_settings")
def test_scan_slow_bounce_finds_78300_pe(mock_settings, mock_pm):
    s = mock_settings.return_value
    s.quick_sideways_slow_bounce_enabled = True
    s.quick_sideways_slow_bounce_premium_min_inr = 90.0
    s.expiry_pm_itm_premium_max_inr = 180.0
    s.quick_sideways_slow_bounce_rsi_min = 40.0
    s.quick_sideways_slow_bounce_rsi_max = 55.0
    s.quick_sideways_slow_bounce_macd_hist_min = -15.0
    s.quick_sideways_slow_bounce_min_tqs = 28.0
    s.quick_sideways_slow_bounce_min_velocity_pct = 0.1
    s.enhanced_velocity_threshold = 1.2
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 300.0

    snap = _sensex_snap()
    setups = scan_slow_bounce_setups("SENSEX", snap, AutoTraderState(), {"SENSEX": snap})
    assert setups
    assert setups[0]["strike"] == 78300.0
    assert setups[0]["mode"] == "slow_bounce"


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_worst_day_blocks_sensex_call_in_bearish_context(mock_policy):
    snap = _sensex_snap()
    snap.breadth = Breadth(bias="NEUTRAL", score=54, aligned=False)
    cand = _Cand(mode="scalp", side=Side.CALL, strike=78500.0, premium=201.0, score=70.0, snap=snap)
    blocked, reason = worst_day_blocks_call_scalp(cand, {"SENSEX": snap}, policy="BREAKOUT_ONLY")
    assert blocked is True
    assert reason == "worst_day_call_blocked_bearish_context"


@patch("app.engines.expiry_day_guards.expiry_pm_itm_quick_active", return_value=True)
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
def test_worst_day_allows_slow_bounce(mock_policy, mock_pm):
    snap = _sensex_snap()
    cand = _Cand(snap=snap, score=62.0)
    ok, reason, _ = worst_day_allows_candidate(cand, AutoTraderState(), {"SENSEX": snap})
    assert ok is True
    assert reason == "ok"
