"""Plain chop stand-down: tight caps, rally carve-out, afternoon halt (CE/PE session)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.chop_day_guards import (
    daily_trade_cap,
    plain_chop_afternoon_standdown_active,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=24000.0,
        atmStrike=24000.0,
        dataAvailable=True,
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias="NEUTRAL", score=55.0, aligned=False),
    )


@patch("app.engines.chop_day_guards.get_settings")
@patch("app.engines.chop_day_guards.is_chop_session", return_value=True)
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=False)
def test_daily_trade_cap_tight_on_plain_chop(mock_exp, mock_chop, mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.daily_max_trades_chop = 3
    s.daily_max_trades_pre10_chop = 3
    s.daily_max_trades_chop_rally = 10
    s.chop_rally_day_modes_csv = "CHOP + RALLY,MOMENTUM RALLY"
    s.plain_chop_day_modes_csv = "CHOP DAY,CHOP (PRE-10)"
    mock_settings.return_value = s
    state = AutoTraderState()
    snaps = {"NIFTY": _snap()}

    with (
        patch("app.engines.chop_day_guards.before_primary_window", return_value=False),
        patch(
            "app.engines.chop_day_guards.resolve_session_day_mode",
            return_value="CHOP DAY",
        ),
    ):
        cap, label = daily_trade_cap(state, snaps)
    assert cap == 3
    assert label == "chop_day"


@patch("app.engines.chop_day_guards.get_settings")
@patch("app.engines.chop_day_guards.is_chop_session", return_value=True)
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=False)
def test_daily_trade_cap_higher_on_chop_rally(mock_exp, mock_chop, mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.daily_max_trades_chop = 3
    s.daily_max_trades_chop_rally = 10
    s.chop_rally_day_modes_csv = "CHOP + RALLY,MOMENTUM RALLY"
    mock_settings.return_value = s
    state = AutoTraderState()
    snaps = {"NIFTY": _snap()}

    with (
        patch("app.engines.chop_day_guards.before_primary_window", return_value=False),
        patch(
            "app.engines.chop_day_guards.resolve_session_day_mode",
            return_value="CHOP + RALLY",
        ),
    ):
        cap, label = daily_trade_cap(state, snaps)
    assert cap == 10
    assert label == "chop_rally"


@patch("app.engines.chop_day_guards.get_settings")
def test_plain_chop_afternoon_standdown_blocks_after_cutoff(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.plain_chop_afternoon_standdown_enabled = True
    s.plain_chop_afternoon_standdown_after_minute = 13 * 60 + 30
    s.plain_chop_day_modes_csv = "CHOP DAY,CHOP (PRE-10)"
    mock_settings.return_value = s
    snaps = {"NIFTY": _snap()}

    with (
        patch(
            "app.engines.chop_day_guards.resolve_session_day_mode",
            return_value="CHOP DAY",
        ),
        patch("app.engines.chop_day_guards._minutes_now", return_value=12 * 60 + 0),
    ):
        blocked, reason, _ = plain_chop_afternoon_standdown_active(snaps)
    assert blocked is False

    with (
        patch(
            "app.engines.chop_day_guards.resolve_session_day_mode",
            return_value="CHOP DAY",
        ),
        patch("app.engines.chop_day_guards._minutes_now", return_value=14 * 60),
    ):
        blocked, reason, _ = plain_chop_afternoon_standdown_active(snaps)
    assert blocked is True
    assert reason == "plain_chop_afternoon_standdown"


@patch("app.engines.chop_day_guards.get_settings")
def test_chop_rally_afternoon_not_standdown(mock_settings):
    s = MagicMock()
    s.chop_day_guards_enabled = True
    s.plain_chop_afternoon_standdown_enabled = True
    s.plain_chop_afternoon_standdown_after_minute = 810
    mock_settings.return_value = s
    snaps = {"NIFTY": _snap()}
    with (
        patch(
            "app.engines.chop_day_guards.resolve_session_day_mode",
            return_value="CHOP + RALLY",
        ),
        patch("app.engines.chop_day_guards._minutes_now", return_value=14 * 60),
    ):
        blocked, reason, _ = plain_chop_afternoon_standdown_active(snaps)
    assert blocked is False
    assert reason == "ok"


def test_settings_defaults_plain_chop_discipline():
    from app.config import Settings

    s = Settings()
    assert s.daily_max_trades_chop == 3
    assert s.daily_max_trades_pre10_chop == 3
    assert s.daily_max_trades_chop_rally == 10
    assert s.chop_post_win_afternoon_block_enabled is True
    assert s.plain_chop_afternoon_standdown_enabled is True