"""BUILDING radar LTP monitor — take path fires on every meaningful premium tick."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.building_ltp_monitor import (
    building_alerts_on_radar,
    building_ltp_monitor_due,
    mark_building_ltps_seen,
    peek_building_ltp_moves,
    reset_building_ltp_monitor_for_tests,
)
from app.models.schemas import (
    HeatmapStrike,
    MarketPhase,
    Side,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(*, call_ltp: float = 100.0, put_ltp: float = 125.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=76900.0,
        atmStrike=76900.0,
        heatmap=[
            HeatmapStrike(
                strike=76900.0,
                callLtp=call_ltp,
                putLtp=put_ltp,
                callInstrumentKey="NSE_FO|CALL",
                putInstrumentKey="NSE_FO|PUT",
            )
        ],
        explosionAlerts=[
            {
                "tier": "BUILDING",
                "side": "PUT",
                "strike": 76900.0,
                "premium": put_ltp,
                "tradeable": True,
            }
        ],
    )


@patch("app.engines.building_ltp_monitor.get_settings")
@patch("app.engines.building_ltp_monitor.resolve_trade_premium")
def test_building_ltp_monitor_seeds_then_fires_on_move(mock_prem, mock_settings):
    reset_building_ltp_monitor_for_tests()
    mock_settings.return_value = Settings()
    mock_prem.return_value = 125.0
    snaps = {"SENSEX": _snap(put_ltp=125.0)}

    assert building_alerts_on_radar(snaps)
    assert building_ltp_monitor_due(snaps) is False  # seed only

    mock_prem.return_value = 128.0  # +2.4% LTP print
    assert building_ltp_monitor_due(snaps, now_mono=10.0) is True

    moved, keys, live = peek_building_ltp_moves(snaps)
    assert moved is True
    assert any(k.endswith(":PUT:76900") for k in keys)
    assert live["SENSEX:PUT:76900"] == 128.0


@patch("app.engines.building_ltp_monitor.get_settings")
@patch("app.engines.building_ltp_monitor.resolve_trade_premium")
def test_building_ltp_ignores_noise_ticks(mock_prem, mock_settings):
    reset_building_ltp_monitor_for_tests()
    mock_settings.return_value = Settings()
    mock_prem.return_value = 125.0
    snaps = {"SENSEX": _snap(put_ltp=125.0)}
    mark_building_ltps_seen(snaps)

    mock_prem.return_value = 125.02  # below abs/pct floors
    assert building_ltp_monitor_due(snaps, now_mono=10.0) is False


@patch("app.engines.building_ltp_monitor.get_settings")
def test_non_building_radar_not_watched(mock_settings):
    reset_building_ltp_monitor_for_tests()
    mock_settings.return_value = Settings()
    snap = _snap()
    snap.explosionAlerts = [
        {"tier": "WATCH", "side": "PUT", "strike": 76900.0, "premium": 125.0}
    ]
    assert building_alerts_on_radar({"SENSEX": snap}) == []
    assert building_ltp_monitor_due({"SENSEX": snap}) is False


def _building_alert(
    *,
    side: str = "PUT",
    strike: float = 76900.0,
    premium: float = 125.0,
    v3: float = 2.0,
    score: float = 55.0,
    pad: float = 8.0,
) -> dict:
    return {
        "tier": "BUILDING",
        "side": side,
        "strike": strike,
        "premium": premium,
        "tradeable": True,
        "velocity3s": v3,
        "velocity9s": 1.2,
        "explosionScore": score,
        "score": score,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "localBaseMovePct": pad,
        "ictBaseRelativeMovePct": pad,
        "offLowMovePct": pad,
        "dailyMovePct": pad,
        "peakMovePct": pad,
        "ictLocalSwingBase": True,
        "volumeSurge": 2.2,
        "volume": 1_500_000,
    }


@patch("app.engines.building_ltp_monitor.get_settings")
@patch("app.engines.building_ltp_monitor.resolve_trade_premium")
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_scores_all_building_and_picks_best_ready(
    mock_ready, mock_prem, mock_settings,
):
    """X BUILDING names are all scored; only the best ready wins the pick."""
    from app.engines.building_ltp_monitor import (
        apply_building_ltp_best_pick,
        evaluate_all_building_ltp,
        publish_building_scoreboard,
    )
    from app.engines.trade_selector import EntryCandidate
    from app.models.schemas import StrategyType

    reset_building_ltp_monitor_for_tests()
    mock_settings.return_value = Settings()
    mock_prem.side_effect = lambda snap, strike, side, max_age_seconds=2.0: (
        140.0 if abs(float(strike) - 76800) < 1 else 125.0
    )

    def _ready(*, alert=None, **_kwargs):
        alert = alert or {}
        strike = float(alert.get("strike") or 0)
        if abs(strike - 76800) < 1:
            return True, "building_local_base_lift_ready"
        if abs(strike - 76900) < 1:
            return True, "building_rip_bullish_ready"
        return False, "building_rip_velocity3s<1.5"

    mock_ready.side_effect = _ready

    snap = _snap()
    snap.heatmap = [
        HeatmapStrike(
            strike=76800.0,
            callLtp=90.0,
            putLtp=140.0,
            callInstrumentKey="NSE_FO|C76800",
            putInstrumentKey="NSE_FO|P76800",
        ),
        HeatmapStrike(
            strike=76900.0,
            callLtp=100.0,
            putLtp=125.0,
            callInstrumentKey="NSE_FO|C76900",
            putInstrumentKey="NSE_FO|P76900",
        ),
        HeatmapStrike(
            strike=77000.0,
            callLtp=80.0,
            putLtp=110.0,
            callInstrumentKey="NSE_FO|C77000",
            putInstrumentKey="NSE_FO|P77000",
        ),
    ]
    snap.explosionAlerts = [
        _building_alert(strike=76800.0, premium=140.0, v3=2.4, score=60.0, pad=7.0),
        _building_alert(strike=76900.0, premium=125.0, v3=1.6, score=50.0, pad=22.0),
        _building_alert(strike=77000.0, premium=110.0, v3=0.4, score=40.0, pad=3.0),
    ]
    scores = evaluate_all_building_ltp({"SENSEX": snap})
    assert len(scores) == 3
    board = publish_building_scoreboard(scores)
    assert board["readyCount"] == 2
    assert board["bestKey"] == "SENSEX:PUT:76800"
    assert scores[0].is_best_ready is True

    best = EntryCandidate(
        symbol="SENSEX",
        snap=snap,
        mode="explosion",
        score=50.0,
        side=Side.PUT,
        strike=76800.0,
        premium=140.0,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=60.0,
        tqs=55.0,
        tier="BUILDING",
        alert=snap.explosionAlerts[0],
    )
    weaker = EntryCandidate(
        symbol="SENSEX",
        snap=snap,
        mode="explosion",
        score=50.0,
        side=Side.PUT,
        strike=76900.0,
        premium=125.0,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=50.0,
        tqs=55.0,
        tier="BUILDING",
        alert=snap.explosionAlerts[1],
    )
    bonus_best, keep_best = apply_building_ltp_best_pick(best)
    bonus_weak, keep_weak = apply_building_ltp_best_pick(weaker)
    assert keep_best is True and bonus_best >= 40.0
    assert keep_weak is False and bonus_weak == 0.0
