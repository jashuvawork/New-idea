"""Sep01 NIFTY PUT 23950 — ATM armed-base exec premium fade miss."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.pad_lane_capture import (
    atm_armed_local_base_premium_fade_bypass,
    local_base_premium_fade_bypass,
    resolve_strict_pad_lane_for_entry,
)
from app.engines.spot_direction import premium_blocks_entry
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import MarketPhase, PremiumChart, Side, SpotChart, SymbolSnapshot


def _settings(**overrides):
    s = MagicMock()
    s.shallow_otm_local_base_min_move_pct = 2.0
    s.shallow_otm_local_base_max_move_pct = 25.0
    s.execution_chart_premium_check_enabled = True
    s.execution_chart_min_premium_momentum_pct = 0.0
    s.pad_lane_premium_fade_fill_enabled = True
    s.pad_lane_premium_fade_fill_max_drawdown_pct = -1.2
    s.ftv_premium_fade_fill_enabled = True
    s.ftv_premium_fade_fill_max_drawdown_pct = -0.6
    s.all_day_explosion_extreme_move_min_pct = 999.0
    s.pad_lane_chart_bypass_enabled = True
    s.pad_lane_first_lift_local_base_chart_bypass_enabled = True
    s.pad_lane_armed_base_launch_chart_bypass_enabled = True
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _sep01_put_23950_alert(**overrides) -> dict:
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23950.0,
        "premium": 19.5,
        "tier": "ELITE",
        "moneyness": "ATM",
        "momentType": "armed_base_launch",
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 8.2,
        "ictBaseRelativeMovePct": 8.2,
        "ictBasePremium": 18.3,
        "peakMovePct": 12.0,
    }
    alert.update(overrides)
    return alert


def _explosion_event(**overrides):
    base = SimpleNamespace(
        tier="ELITE",
        daily_move_pct=8.2,
        moneyness="ATM",
        explosion_score=100.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@patch("app.engines.pad_lane_capture.get_settings")
def test_atm_armed_local_base_premium_fade_bypass(mock_settings):
    mock_settings.return_value = _settings()
    alert = _sep01_put_23950_alert()
    event = _explosion_event()

    assert atm_armed_local_base_premium_fade_bypass(alert, event) is True
    assert local_base_premium_fade_bypass(alert, event) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_atm_armed_bypass_rejects_deep_itm(mock_settings):
    mock_settings.return_value = _settings()
    alert = _sep01_put_23950_alert(moneyness="ITM", localBaseMovePct=42.0)
    assert atm_armed_local_base_premium_fade_bypass(alert, _explosion_event(moneyness="ITM")) is False


@patch("app.engines.pad_lane_capture.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_strict_pad_resolves_when_first_lift_unconfirmed(mock_ict, mock_pad):
    mock_pad.return_value = _settings()
    mock_ict.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-09-01T14:37:05+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=52.0,
        spot=23975.0,
        atmStrike=24000.0,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.12, trendStrength=40),
    )
    alert = _sep01_put_23950_alert()
    event = _explosion_event()

    with patch(
        "app.engines.ict_breakout_monitor.first_lift_entry_readiness",
        return_value=(False, "first_lift_structure_not_confirmed"),
    ):
        pad_lane, strict = resolve_strict_pad_lane_for_entry(
            Side.PUT,
            snap,
            mode="explosion",
            explosion_event=event,
            alert=alert,
        )

    assert pad_lane is False
    assert strict is True


@patch("app.engines.winner_entry_guards.get_settings")
def test_premium_fade_allows_atm_armed_base_retest(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-0.9,
        premium_momentum_5s=-0.8,
        explosion_event=_explosion_event(),
        pad_lane_bypass=True,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"


@patch("app.engines.spot_direction.get_settings")
@patch("app.engines.winner_entry_guards.get_settings")
def test_premium_blocks_entry_uses_atm_armed_strict_pad(mock_guard, mock_spot):
    settings = _settings()
    mock_guard.return_value = settings
    mock_spot.return_value = settings
    premium = PremiumChart(
        direction="BEARISH",
        momentum3Pct=-0.9,
        momentum5Pct=-0.8,
        lastPremium=19.5,
    )
    blocked, reason = premium_blocks_entry(
        Side.PUT,
        premium,
        explosion_event=_explosion_event(),
        pad_lane_bypass=True,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"
