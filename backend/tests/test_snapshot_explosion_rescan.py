"""WS-overlay explosion rescan — catch vertical premium rips between REST rebuilds."""

from unittest.mock import patch

from app.engines.explosion_detector import (
    refresh_snapshot_explosion_alerts,
    scan_snapshot_explosions,
    _history,
    _session_open,
    _session_peak,
    _tier_sticky,
)
from app.models.schemas import HeatmapStrike, Side, SpotChart, SymbolSnapshot


def _settings():
    from unittest.mock import MagicMock
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 400.0
    s.explosion_max_premium_inr = 400.0
    s.open_premium_explosion_enabled = True
    s.open_premium_min_move_pct = 15.0
    s.all_day_explosion_session_move_min_pct = 25.0
    s.all_day_explosion_min_score = 38.0
    s.expiry_atm_tier_velocity_mult = 1.0
    s.explosion_entry_earliest_hour = 9
    s.explosion_entry_earliest_minute = 15
    s.open_caution_until_hour = 9
    s.open_caution_until_minute = 45
    s.explosion_volume_awaken_min = 5000
    s.ict_breakout_monitor_enabled = False
    return s


def _snap(strike: float, put_ltp: float) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-07-15T12:57:00+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        spot=24071.0,
        atmStrike=24100.0,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.49, trendStrength=35.0),
        heatmap=[
            HeatmapStrike(strike=strike, putLtp=put_ltp, putOi=5000),
        ],
    )


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_snapshot_rescan_detects_put_vertical_rip(mock_settings, _open_window):
    mock_settings.return_value = _settings()
    _history.clear()
    _session_open.clear()
    _session_peak.clear()
    _tier_sticky.clear()

    snap = _snap(24000.0, 80.0)
    scan_snapshot_explosions(snap)
    snap.heatmap[0].putLtp = 168.0
    events = scan_snapshot_explosions(snap)

    puts = [e for e in events if e.side == Side.PUT and e.strike == 24000.0]
    assert puts, "expected PUT 24000 explosion after vertical rip"
    assert puts[0].daily_move_pct >= 50
    assert puts[0].tier in ("EXPLODING", "ELITE")


@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=True)
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=False)
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=False)
@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_refresh_snapshot_explosion_alerts_updates_list(
    mock_settings, _open_window, _morning, _afternoon, _all_day,
):
    mock_settings.return_value = _settings()
    _history.clear()
    _session_open.clear()
    _session_peak.clear()
    _tier_sticky.clear()

    snap = _snap(24000.0, 85.0)
    scan_snapshot_explosions(snap)
    snap.heatmap[0].putLtp = 170.0
    refresh_snapshot_explosion_alerts(snap)
    assert snap.explosionAlerts
    top = snap.explosionAlerts[0]
    assert top["side"] == "PUT"
    assert top["strike"] == 24000.0
