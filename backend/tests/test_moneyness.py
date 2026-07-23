"""ITM / ATM / OTM strike selection tests."""

from unittest.mock import MagicMock, patch

from app.engines.moneyness import (
    classify_moneyness,
    heatmap_moneyness_candidates,
    moneyness_allows,
    moneyness_rank_adjustment,
    resolve_preferred_moneyness,
)
from app.models.schemas import (
    Breadth,
    HeatmapStrike,
    MarketPhase,
    Regime,
    Side,
    SymbolSnapshot,
)

IST = None


def _settings():
    s = MagicMock()
    s.moneyness_selection_enabled = True
    s.trade_moneyness_mode = "AUTO"
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.banknifty_strike_step = 100.0
    s.moneyness_max_otm_steps = 2
    s.moneyness_max_itm_steps = 2
    s.moneyness_explosion_prefer = "OTM"
    s.moneyness_explosion_block_otm = True
    s.moneyness_scalp_chop_prefer = "ITM"
    s.moneyness_high_conf_prefer = "ITM"
    s.moneyness_rank_bonus = 12.0
    s.moneyness_mismatch_penalty = 15.0
    s.high_confidence_min_score = 72.0
    s.bearish_sideways_explosion_min_score = 78.0
    s.min_option_premium_inr = 25.0
    s.max_option_premium_inr = 175.0
    s.chop_day_guards_enabled = True
    s.whipsaw_guards_enabled = True
    return s


def _snap(spot: float = 23950.0, bias: str = "BEARISH") -> SymbolSnapshot:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=23950.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=40.0,
        breadth=Breadth(bias=bias, score=42, aligned=bias == "BEARISH"),
        heatmap=[
            HeatmapStrike(strike=23950.0, callLtp=35.0, putLtp=38.0, liquidityScore=80),
            HeatmapStrike(strike=24050.0, callLtp=48.0, putLtp=62.0, liquidityScore=70),
            HeatmapStrike(strike=23800.0, callLtp=58.0, putLtp=30.0, liquidityScore=65),
        ],
    )


@patch("app.engines.moneyness.get_settings", return_value=_settings())
def test_classify_itm_atm_otm(mock_settings):
    snap = _snap()
    assert classify_moneyness(Side.CALL, 23950, snap.spot, symbol="NIFTY", atm=23950) == "ATM"
    assert classify_moneyness(Side.PUT, 24050, snap.spot, symbol="NIFTY", atm=23950) == "ITM"
    assert classify_moneyness(Side.PUT, 23800, snap.spot, symbol="NIFTY", atm=23950) == "OTM"
    assert classify_moneyness(Side.CALL, 24100, snap.spot, symbol="NIFTY", atm=23950) == "OTM"


@patch("app.engines.moneyness.get_settings", return_value=_settings())
@patch("app.engines.moneyness.is_chop_session", return_value=True)
@patch("app.engines.moneyness.is_bearish_sideways", return_value=True)
def test_chop_prefers_itm_scalp(mock_chop, mock_bs, mock_settings):
    snap = _snap()
    assert resolve_preferred_moneyness("scalp", snap) == "ITM"


@patch("app.engines.moneyness.get_settings", return_value=_settings())
def test_explosion_prefers_otm(mock_settings):
    snap = _snap(bias="BULLISH")
    snap.regime = Regime.TREND_EXPANSION
    assert resolve_preferred_moneyness("explosion", snap) == "OTM"


@patch("app.engines.moneyness.get_settings")
def test_explosion_atm_prefer_hard_blocks_otm(mock_settings):
    """Jul23: explosion prefer ATM must not soft-allow 2-step OTM (76100 PE)."""
    s = _settings()
    s.moneyness_explosion_prefer = "ATM"
    s.moneyness_explosion_block_otm = True
    mock_settings.return_value = s
    snap = _snap(spot=76300.0)
    snap.symbol = "SENSEX"
    snap.atmStrike = 76300.0
    snap.heatmap = []
    # SENSEX PUT 76100 = 2 steps OTM
    ok, reason, meta = moneyness_allows(
        Side.PUT, 76100, snap, mode="explosion", candidate_score=100,
    )
    assert ok is False
    assert reason == "moneyness_explosion_atm_only_otm_blocked"
    assert meta["moneyness"] == "OTM"
    # ATM still allowed
    ok_atm, _, meta_atm = moneyness_allows(
        Side.PUT, 76300, snap, mode="explosion", candidate_score=100,
    )
    assert ok_atm is True
    assert meta_atm["moneyness"] == "ATM"


@patch("app.engines.moneyness.get_settings", return_value=_settings())
@patch("app.engines.moneyness.is_chop_session", return_value=True)
@patch("app.engines.moneyness.is_bearish_sideways", return_value=True)
def test_blocks_otm_scalp_in_chop(mock_bs, mock_chop, mock_settings):
    snap = _snap()
    ok, reason, meta = moneyness_allows(Side.PUT, 23800, snap, mode="scalp", candidate_score=60)
    assert not ok
    # 23800 is 3 steps OTM on NIFTY (150/50) — blocked as too-deep or chop-requires-ITM.
    assert "chop_requires" in reason or "itm" in reason.lower() or "otm_too_deep" in reason
    assert meta["moneyness"] == "OTM"


@patch("app.engines.moneyness.get_settings", return_value=_settings())
@patch("app.engines.moneyness.is_chop_session", return_value=True)
@patch("app.engines.moneyness.is_bearish_sideways", return_value=True)
def test_allows_itm_put_in_bearish_chop(mock_bs, mock_chop, mock_settings):
    snap = _snap()
    ok, reason, meta = moneyness_allows(Side.PUT, 24050, snap, mode="scalp", candidate_score=60)
    assert ok
    assert meta["moneyness"] == "ITM"


@patch("app.engines.moneyness.get_settings", return_value=_settings())
@patch("app.engines.moneyness.is_chop_session", return_value=True)
@patch("app.engines.moneyness.is_bearish_sideways", return_value=True)
def test_heatmap_supplies_itm_puts(mock_bs, mock_chop, mock_settings):
    snap = _snap()
    rows = heatmap_moneyness_candidates("NIFTY", snap)
    assert any(r["side"] == Side.PUT and r["moneyness"] == "ITM" for r in rows)


@patch("app.engines.moneyness.get_settings", return_value=_settings())
def test_rank_bonus_for_aligned_moneyness(mock_settings):
    snap = _snap()
    with patch("app.engines.moneyness.resolve_preferred_moneyness", return_value="OTM"):
        bonus = moneyness_rank_adjustment(Side.CALL, 24100, snap, mode="explosion")
    assert bonus > 0
