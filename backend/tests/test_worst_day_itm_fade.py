from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import check_bad_day_candidate
from app.engines.worst_day_guard import worst_day_allows_candidate
from app.engines.worst_day_itm_fade import (
    check_worst_day_itm_fade_entry,
    in_worst_day_dead_zone,
    is_worst_day_alternate_symbol,
    scan_worst_day_itm_fade_setups,
    worst_day_defensive_session_active,
    worst_day_quick_trade_allowed,
)
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


def _next_week() -> str:
    return (datetime.now(IST) + timedelta(days=7)).strftime("%Y-%m-%d")


def _sensex_snap(spot: float = 77100.0, tqs: float = 44.0, bias: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=_next_week(),
        spot=spot,
        atmStrike=77100.0,
        regime=Regime.CHOP,
        tradeQualityScore=tqs,
        breadth=Breadth(bias=bias, score=54, aligned=bias != "NEUTRAL"),
        orderflow=Orderflow(tickMomentum=-5, deltaVelocity=-8, signedMomentumPct=0.15),
        spotChart=SpotChart(
            direction="BEARISH",
            spot=spot,
            momentum5Pct=-0.02,
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
            HeatmapStrike(strike=77200.0, putLtp=171.0),
            HeatmapStrike(strike=77100.0, putLtp=130.0),
        ],
    )


def _nifty_snap() -> SymbolSnapshot:
    tomorrow = (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=tomorrow,
        spot=24050.0,
        atmStrike=24050.0,
        regime=Regime.CHOP,
        tradeQualityScore=40.0,
        breadth=Breadth(bias="BEARISH", score=30, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.01, trendStrength=20),
    )


class _Cand:
    def __init__(self, **kwargs):
        self.mode = kwargs.get("mode", "worst_day_itm_fade")
        self.symbol = kwargs.get("symbol", "SENSEX")
        self.side = kwargs.get("side", Side.PUT)
        self.strike = kwargs.get("strike", 77200.0)
        self.premium = kwargs.get("premium", 171.0)
        self.score = kwargs.get("score", 62.0)
        self.tier = ""
        self.snap = kwargs.get("snap", _sensex_snap())
        self.pretrade_meta = kwargs.get("pretrade_meta", {})


@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["bearish_sideways"]})
@patch("app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX")
def test_alternate_symbol_sensex_when_nifty_fading(mock_alt, mock_fade):
    snaps = {"NIFTY": _nifty_snap(), "SENSEX": _sensex_snap()}
    state = AutoTraderState()
    assert is_worst_day_alternate_symbol(snaps["SENSEX"], state, snaps) is True
    assert is_worst_day_alternate_symbol(snaps["NIFTY"], state, snaps) is False


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
def test_defensive_session_active_on_bad_day(mock_bd):
    assert worst_day_defensive_session_active(AutoTraderState(), {"SENSEX": _sensex_snap()}) is True


@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=True)
@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX")
@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["bearish_sideways"]})
@patch("app.engines.worst_day_itm_fade.in_worst_day_itm_fade_window", return_value=True)
def test_dead_zone_blocks_itm_fade(mock_win, mock_fade, mock_alt, mock_bd, mock_dz):
    snap = _sensex_snap()
    state = AutoTraderState()
    snaps = {"NIFTY": _nifty_snap(), "SENSEX": snap}
    ok, reason, _ = check_worst_day_itm_fade_entry(
        snap, Side.PUT, 77200.0, 171.0, state=state, snapshots=snaps,
    )
    assert ok is False
    assert reason == "worst_day_dead_zone"


@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=False)
@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX")
@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["bearish_sideways"]})
@patch("app.engines.worst_day_itm_fade.in_worst_day_itm_fade_window", return_value=True)
@patch("app.engines.worst_day_itm_fade.detect_slow_bounce_signal")
def test_itm_fade_allows_aligned_put(mock_sig, mock_win, mock_fade, mock_alt, mock_bd, mock_dz):
    mock_sig.return_value = (True, "slow_bounce", {"rsi": 48.5})
    snap = _sensex_snap()
    state = AutoTraderState()
    snaps = {"NIFTY": _nifty_snap(), "SENSEX": snap}
    ok, reason, meta = check_worst_day_itm_fade_entry(
        snap, Side.PUT, 77200.0, 171.0, state=state, snapshots=snaps,
    )
    assert ok is True
    assert meta.get("signal") == "slow_bounce"


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX")
@patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["bearish_sideways"]})
@patch("app.engines.worst_day_itm_fade.in_worst_day_itm_fade_window", return_value=True)
@patch("app.engines.worst_day_itm_fade.in_worst_day_dead_zone", return_value=False)
@patch("app.engines.worst_day_itm_fade.detect_slow_bounce_signal", return_value=(True, "slow_bounce", {}))
def test_scan_finds_sensex_fade(mock_sig, mock_dz, mock_win, mock_fade, mock_alt, mock_bd):
    snap = _sensex_snap()
    state = AutoTraderState()
    snaps = {"NIFTY": _nifty_snap(), "SENSEX": snap}
    setups = scan_worst_day_itm_fade_setups("SENSEX", snap, state, snaps)
    assert setups
    assert setups[0]["mode"] == "worst_day_itm_fade"
    assert setups[0]["side"] == Side.PUT


@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
@patch("app.engines.worst_day_itm_fade.worst_day_quick_trade_allowed", return_value=(True, "ok"))
def test_worst_day_allows_quick_on_alternate(mock_quick, mock_policy):
    snap = _sensex_snap()
    cand = _Cand(mode="quick_sideways", pretrade_meta={"worstDayQuick": True, "velocityPct": 0.2})
    ok, reason, meta = worst_day_allows_candidate(
        cand, AutoTraderState(), {"SENSEX": snap}, policy="BREAKOUT_ONLY",
    )
    assert ok is True
    assert meta.get("worstDayQuick") is True


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.bad_day_routing.is_bearish_sideways_session", return_value=True)
def test_bad_day_allows_worst_day_itm_fade_on_alternate(mock_bear, mock_bd):
    snap = _sensex_snap()
    cand = _Cand(score=62.0)
    snaps = {"NIFTY": _nifty_snap(), "SENSEX": snap}
    with patch("app.engines.bad_day_routing.fading_expiry_symbols", return_value={"NIFTY": ["x"]}), patch(
        "app.engines.bad_day_routing.alternate_index_for", return_value="SENSEX",
    ):
        ok, reason, meta = check_bad_day_candidate(cand, AutoTraderState(), snaps)
    assert ok is True


@patch("app.engines.worst_day_itm_fade._minutes_now", return_value=11 * 60 + 15)
@patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET")
def test_dead_zone_window(mock_phase, mock_min):
    assert in_worst_day_dead_zone() is True
