"""CHOP+RALLY CE building capture window — Sep21 CALL 23450 base miss fix."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.building_ltp_monitor import (
    BuildingLtpScore,
    publish_building_scoreboard,
    reset_building_ltp_monitor_for_tests,
)
from app.engines.pe_win_ce_mirror import chop_rally_ce_building_capture_ok


def _alert(**overrides):
    base = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 23450.0,
        "tier": "BUILDING",
        "explosionScore": 58.0,
        "localBaseMovePct": 12.8,
        "ictBaseRelativeMovePct": 12.8,
        "volumeAwaken": True,
        "ictBuildingRipReady": True,
        "buildingRipBullish": True,
        "tradeable": False,
    }
    base.update(overrides)
    return base


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_chop_rally_capture_ok_near_base_scoreboard_ready(_unlock):
    reset_building_ltp_monitor_for_tests()
    publish_building_scoreboard(
        [
            BuildingLtpScore(
                key="NIFTY:CALL:23450",
                symbol="NIFTY",
                side="CALL",
                strike=23450.0,
                ltp=46.8,
                tier="BUILDING",
                ready=True,
                ready_reason="building_rip_bullish_ready",
                score=88.0,
                explosion_score=58.0,
                velocity_3s=1.5,
                velocity_9s=1.2,
                local_move_pct=12.8,
                off_low_move_pct=12.8,
                volume_awaken=True,
                is_best_ready=True,
            )
        ]
    )
    settings = Settings()
    snap = MagicMock(symbol="NIFTY", tradeQualityScore=55.0)
    state = MagicMock(dailyStrategy={"dayMode": "CHOP + RALLY"})
    assert chop_rally_ce_building_capture_ok(
        _alert(),
        snap,
        state,
        day_mode="CHOP + RALLY",
        readiness_reason="building_rip_bullish_ready",
        settings=settings,
    ) is True


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_chop_rally_capture_rejects_chase_past_15pct(_unlock):
    reset_building_ltp_monitor_for_tests()
    publish_building_scoreboard(
        [
            BuildingLtpScore(
                key="NIFTY:CALL:23450",
                symbol="NIFTY",
                side="CALL",
                strike=23450.0,
                ltp=64.0,
                tier="BUILDING",
                ready=True,
                ready_reason="building_rip_bullish_ready",
                score=70.0,
                explosion_score=70.0,
                velocity_3s=2.0,
                velocity_9s=1.5,
                local_move_pct=38.0,
                off_low_move_pct=38.0,
                volume_awaken=True,
                is_best_ready=True,
            )
        ]
    )
    settings = Settings()
    snap = MagicMock(symbol="NIFTY")
    state = MagicMock(dailyStrategy={"dayMode": "CHOP + RALLY"})
    assert chop_rally_ce_building_capture_ok(
        _alert(localBaseMovePct=38.0, ictBaseRelativeMovePct=38.0),
        snap,
        state,
        day_mode="CHOP + RALLY",
        settings=settings,
    ) is False


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=True)
def test_chop_rally_capture_requires_scoreboard_ready(_unlock):
    reset_building_ltp_monitor_for_tests()
    settings = Settings()
    snap = MagicMock(symbol="NIFTY")
    state = MagicMock(dailyStrategy={"dayMode": "CHOP + RALLY"})
    assert chop_rally_ce_building_capture_ok(
        _alert(),
        snap,
        state,
        day_mode="CHOP + RALLY",
        settings=settings,
    ) is False


def test_chop_rally_capture_wrong_day_mode():
    reset_building_ltp_monitor_for_tests()
    settings = Settings()
    snap = MagicMock(symbol="NIFTY")
    state = MagicMock(dailyStrategy={"dayMode": "CHOP DAY"})
    assert chop_rally_ce_building_capture_ok(
        _alert(),
        snap,
        state,
        day_mode="CHOP DAY",
        settings=settings,
    ) is False


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_fingerprint", return_value=False)
def test_chop_rally_capture_requires_rally_fingerprint(_unlock):
    reset_building_ltp_monitor_for_tests()
    publish_building_scoreboard(
        [
            BuildingLtpScore(
                key="NIFTY:CALL:23450",
                symbol="NIFTY",
                side="CALL",
                strike=23450.0,
                ltp=46.8,
                tier="BUILDING",
                ready=True,
                ready_reason="building_rip_bullish_ready",
                score=88.0,
                explosion_score=58.0,
                velocity_3s=1.5,
                velocity_9s=1.2,
                local_move_pct=12.8,
                off_low_move_pct=12.8,
                volume_awaken=True,
                is_best_ready=True,
            )
        ]
    )
    settings = Settings()
    snap = MagicMock(symbol="NIFTY")
    state = MagicMock(dailyStrategy={"dayMode": "CHOP + RALLY"})
    assert chop_rally_ce_building_capture_ok(
        _alert(),
        snap,
        state,
        day_mode="CHOP + RALLY",
        settings=settings,
    ) is False
