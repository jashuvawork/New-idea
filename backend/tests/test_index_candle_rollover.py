"""Index candles stepping off the local extreme block the aligned option side."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.index_candle_rollover import index_candle_rollover_blocked
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 23, 9, 28, 20, tzinfo=IST)


def _bar(minute: int, open_: float, high: float, low: float, close: float) -> list:
    ts = datetime(2026, 10, 23, 9, minute, tzinfo=IST).isoformat()
    return [ts, open_, high, low, close, 0]


def _settings(**overrides) -> Settings:
    settings = Settings()
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_call_blocked_when_each_minute_closes_lower_off_the_high():
    candles = [
        _bar(24, 22740, 22750, 22738, 22748),
        _bar(25, 22748, 22763.5, 22746, 22760),
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    blocked, reason, meta = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22745.1, now=NOW, settings=_settings(),
    )
    assert blocked is True
    assert reason == "index_falling_from_local_high"
    assert meta["timeframe"] == "1m"
    assert meta["localHigh"] == 22763.5
    assert meta["givebackFromHighPct"] >= 0.04


def test_put_is_not_blocked_by_the_same_decline():
    candles = [
        _bar(25, 22748, 22763.5, 22746, 22760),
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    blocked, reason, _ = index_candle_rollover_blocked(
        Side.PUT, candles, spot=22745.1, now=NOW, settings=_settings(),
    )
    assert blocked is False
    assert reason == ""


def test_put_blocked_when_each_minute_closes_higher_off_the_low():
    candles = [
        _bar(25, 22760, 22762, 22740, 22742),
        _bar(26, 22742, 22750, 22741, 22748),
        _bar(27, 22748, 22756, 22747, 22755),
        _bar(28, 22755, 22764, 22754, 22762),
    ]
    blocked, reason, meta = index_candle_rollover_blocked(
        Side.PUT, candles, spot=22763.0, now=NOW, settings=_settings(),
    )
    assert blocked is True
    assert reason == "index_rising_from_local_low"
    assert meta["localLow"] == 22740.0


def test_rising_call_is_allowed():
    candles = [
        _bar(25, 22720, 22730, 22718, 22728),
        _bar(26, 22728, 22740, 22727, 22738),
        _bar(27, 22738, 22752, 22736, 22750),
        _bar(28, 22750, 22764, 22749, 22762),
    ]
    blocked, reason, _ = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22762.0, now=NOW, settings=_settings(),
    )
    assert blocked is False
    assert reason == ""


def test_tiny_giveback_does_not_block():
    candles = [
        _bar(26, 22760, 22761, 22759.5, 22760),
        _bar(27, 22760, 22760.2, 22759, 22759.5),
        _bar(28, 22759.5, 22759.6, 22759, 22759.2),
    ]
    blocked, _, _ = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22759.0, now=NOW, settings=_settings(),
    )
    assert blocked is False


def test_five_minute_steps_block_when_one_minute_is_missing():
    candles = [
        _bar(15, 22740, 22764, 22736, 22758),
        _bar(20, 22758, 22760, 22744, 22746),
        _bar(25, 22746, 22748, 22732, 22740),
    ]
    blocked, reason, meta = index_candle_rollover_blocked(
        Side.CALL,
        None,
        candles,
        spot=22730.0,
        now=NOW,
        settings=_settings(),
    )
    assert blocked is True
    assert reason == "index_falling_from_local_high"
    assert meta["timeframe"] == "5m"


def test_flag_off_lets_the_rollover_through():
    candles = [
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    blocked, reason, _ = index_candle_rollover_blocked(
        Side.CALL,
        candles,
        spot=22745.0,
        now=NOW,
        settings=_settings(index_candle_rollover_block_enabled=False),
    )
    assert blocked is False
    assert reason == ""


def test_same_decline_after_0945_does_not_block():
    candles = [
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    later = datetime(2026, 10, 23, 10, 0, tzinfo=IST)
    blocked, reason, _ = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22745.0, now=later, settings=_settings(),
    )
    assert blocked is False
    assert reason == ""


def test_window_ends_at_0945_exactly():
    candles = [
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    at_end = datetime(2026, 10, 23, 9, 45, tzinfo=IST)
    blocked, _, _ = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22745.0, now=at_end, settings=_settings(),
    )
    assert blocked is False
    still_open = datetime(2026, 10, 23, 9, 44, 59, tzinfo=IST)
    blocked_open, reason, _ = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22745.0, now=still_open, settings=_settings(),
    )
    assert blocked_open is True
    assert reason == "index_falling_from_local_high"


def test_before_0915_does_not_block():
    candles = [
        _bar(26, 22760, 22761, 22752, 22754),
        _bar(27, 22754, 22755, 22746, 22748),
        _bar(28, 22748, 22749, 22744, 22746),
    ]
    early = datetime(2026, 10, 23, 9, 14, 59, tzinfo=IST)
    blocked, _, _ = index_candle_rollover_blocked(
        Side.CALL, candles, spot=22745.0, now=early, settings=_settings(),
    )
    assert blocked is False


def test_yesterday_candles_are_ignored():
    stale = [
        ["2026-10-22T15:20:00+05:30", 22600, 22620, 22590, 22610, 0],
        ["2026-10-22T15:21:00+05:30", 22610, 22612, 22580, 22590, 0],
        ["2026-10-22T15:22:00+05:30", 22590, 22592, 22570, 22575, 0],
    ]
    blocked, _, _ = index_candle_rollover_blocked(
        Side.CALL, stale, spot=22745.0, now=NOW, settings=_settings(),
    )
    assert blocked is False
