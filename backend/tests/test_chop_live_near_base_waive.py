"""Chop-live hard blocks waive for Sep917 / Oct near-base V/FTV pad (CE + PE)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.chop_live_guards import chop_live_entry_blocked
from app.models.schemas import AutoTraderState, MarketPhase, Regime, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap():
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        regime=Regime.CHOP,
    )


def _state():
    return AutoTraderState(dailyStrategy={"dayMode": "CHOP DAY"})


@patch("app.engines.chop_live_guards.chop_live_guard_day_active", return_value=True)
@patch("app.engines.chop_live_guards.get_settings")
@patch("app.config.get_settings")
def test_chop_live_waives_immature_for_v_rip_near_base(
    mock_cfg_settings, mock_chop_settings, _day,
):
    from tests.mock_defaults import settings_mock

    s = settings_mock(
        chop_live_hard_block_worst_day=False,
        chop_live_waive_near_base_sep917_shape=True,
        chop_live_guards_enabled=True,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        best_trade_sep917_base_shape_align_enabled=True,
        best_trade_base_first_enabled=True,
        best_trade_new_base_moment_enabled=True,
    )
    mock_cfg_settings.return_value = s
    mock_chop_settings.return_value = s
    cand = SimpleNamespace(
        mode="explosion",
        side=Side.CALL,
        symbol="NIFTY",
        strike=22700.0,
        alert={
            "tier": "ELITE",
            "momentType": "v_rip_session_low",
            "ictBaseReadinessReason": "v_rip_session_low_ready",
            "localBaseMovePct": 8.0,
        },
        pretrade_meta={},
        explosion_event=SimpleNamespace(
            tier="ELITE",
            daily_move_pct=12.0,
            peak_move_pct=12.0,
            explosion_score=95.0,
            velocity_3s=0.2,
            velocity_9s=0.1,
            side=Side.CALL,
            symbol="NIFTY",
            strike=22700.0,
        ),
        snap=_snap(),
    )
    blocked, reason, meta = chop_live_entry_blocked(
        cand, _snap(), _state(), snapshots={"NIFTY": _snap()},
    )
    assert blocked is False
    assert reason == "ok"
    assert meta.get("chopLiveNearBaseWaive")
