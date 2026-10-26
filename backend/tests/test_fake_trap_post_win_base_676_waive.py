"""Post-win fake-trap waived on #676-style base capture."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import detect_fake_explosion_trap
from app.engines.pretrade_validator import TradeRecord
from app.models.schemas import MarketPhase, Regime, Side, SpotChart, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _snap_call_base() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.TREND_EXPANSION,
        spot=22520.0,
        atmStrike=22500.0,
        spotChart=SpotChart(
            direction="BULLISH",
            timeframe="5m",
            barCount=51,
            momentum5Pct=0.1,
            orPosition="ABOVE",
        ),
    )


@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.pretrade_validator.collect_session_trades")
def test_post_win_cold_velocity_waived_on_call_676_base(
    mock_collect, mock_settings, mock_money_settings,
):
    s = settings_mock()
    s.fake_explosion_trap_post_win_velocity_block_enabled = True
    s.fake_explosion_trap_post_win_midday_min_velocity_3s = 1.0
    s.fake_explosion_trap_post_win_waive_on_base_capture_eligible_enabled = True
    mock_settings.return_value = s
    mock_money_settings.return_value = s

    snap = _snap_call_base()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=22450.0,
        premium=180.0,
        velocity_3s=-0.35,
        velocity_9s=-0.2,
        velocity_15s=-0.2,
        volume_surge=2.0,
        explosion_score=95.0,
        tier="ELITE",
        reason="armed_base_launch",
        daily_move_pct=10.0,
        peak_move_pct=10.0,
    )
    cand = MagicMock()
    cand.mode = "explosion"
    cand.symbol = "NIFTY"
    cand.side = Side.CALL
    cand.strike = 22450.0
    cand.score = 160.0
    cand.explosion_event = event
    cand.snap = snap
    cand.alert = {
        "tier": "ELITE",
        "armedBaseLaunch": True,
        "firstLift": True,
        "ictFirstLift": True,
        "localBaseMovePct": 8.0,
        "ictBaseRelativeMovePct": 8.0,
        "activeBreakout": True,
    }

    mock_collect.return_value = [
        TradeRecord(
            symbol="NIFTY",
            side="CALL",
            pnl_inr=5089.0,
            exit_reason="explosion_profit_ladder_peak_keep",
            strike=22500.0,
        )
    ]

    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True):
        blocked, reason, meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(),
        )

    assert blocked is False
    assert meta.get("postWinBaseCaptureWaived") is True
    assert reason == "ok"
    assert meta.get("postWinBaseCapture676FullLots") is True


@patch("app.engines.moneyness.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.pretrade_validator.collect_session_trades")
def test_post_win_cold_velocity_still_blocks_non_676_chase(
    mock_collect, mock_settings, mock_money_settings,
):
    s = settings_mock()
    s.fake_explosion_trap_post_win_velocity_block_enabled = True
    s.fake_explosion_trap_post_win_midday_min_velocity_3s = 1.0
    s.fake_explosion_trap_post_win_waive_on_base_capture_eligible_enabled = True
    mock_settings.return_value = s
    mock_money_settings.return_value = s

    snap = _snap_call_base()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=120.0,
        velocity_3s=-0.35,
        velocity_9s=-0.2,
        velocity_15s=-0.2,
        volume_surge=2.0,
        explosion_score=90.0,
        tier="ELITE",
        reason="flat_then_vertical",
        daily_move_pct=25.0,
        peak_move_pct=25.0,
    )
    cand = MagicMock()
    cand.mode = "explosion"
    cand.symbol = "NIFTY"
    cand.side = Side.CALL
    cand.strike = 22700.0
    cand.explosion_event = event
    cand.snap = snap
    cand.alert = {
        "tier": "ELITE",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 22.0,
        "ictBaseRelativeMovePct": 22.0,
    }

    mock_collect.return_value = [
        TradeRecord(
            symbol="NIFTY",
            side="CALL",
            pnl_inr=3000.0,
            exit_reason="explosion_stage_trail",
            strike=22500.0,
        )
    ]

    with patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True):
        blocked, reason, _meta = detect_fake_explosion_trap(
            cand, snap, state=MagicMock(),
        )

    assert blocked is True
    assert reason.startswith("fake_explosion_trap_")
