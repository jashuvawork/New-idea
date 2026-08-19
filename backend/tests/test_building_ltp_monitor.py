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
