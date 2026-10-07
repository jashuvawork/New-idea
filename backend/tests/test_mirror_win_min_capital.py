"""CE↔PE mirror arms on capital-scaled trail wins (Oct 7 SENSEX 72600 CE +₹542 → NIFTY CE chase)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.pe_win_ce_mirror import (
    mirror_win_min_pnl_inr,
    pe_win_ce_mirror_armed,
    pe_win_ce_mirror_put_chase_blocked,
    session_put_win_meta,
)
from app.engines.put_slide_ce_mirror import (
    ce_win_pe_mirror_armed,
    ce_win_pe_mirror_call_chase_blocked,
    session_call_win_meta,
)
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _win(side: str, symbol: str, pnl: float, minutes_ago: float = 2.0) -> SimpleNamespace:
    return SimpleNamespace(
        status="CLOSED",
        side=side,
        symbol=symbol,
        pnl_inr=pnl,
        exit_reason="explosion_peak_keep_trail",
        closed_at=datetime.now(IST) - timedelta(minutes=minutes_ago),
    )


def _settings(capital: float = 200_000.0, **overrides) -> Settings:
    return Settings(
        max_sizing_capital_inr=capital,
        fallback_capital_inr=capital,
        **overrides,
    )


@pytest.mark.parametrize(
    "capital,expected",
    [(200_000.0, 400.0), (150_000.0, 300.0), (50_000.0, 250.0), (1_000_000.0, 1000.0)],
)
@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_min_win_scales_with_capital_floor_and_cap(side, capital, expected):
    assert mirror_win_min_pnl_inr(side, settings=_settings(capital)) == pytest.approx(expected)


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_min_win_falls_back_to_fixed_inr_when_pct_disabled(side):
    s = _settings(mirror_win_min_capital_pct=0.0)
    assert mirror_win_min_pnl_inr(side, settings=s) == pytest.approx(1000.0)


@patch("app.engines.put_slide_ce_mirror._collect_session_trades")
def test_ce_modest_trail_win_counts_as_call_win(mock_trades):
    mock_trades.return_value = [_win("CALL", "SENSEX", 541.8)]
    ok, meta = session_call_win_meta(SimpleNamespace(), settings=_settings())
    assert ok is True
    assert meta["callWinSymbol"] == "SENSEX"


@patch("app.engines.pe_win_ce_mirror._collect_session_trades")
def test_pe_modest_trail_win_counts_as_put_win(mock_trades):
    mock_trades.return_value = [_win("PUT", "SENSEX", 541.8)]
    ok, meta = session_put_win_meta(SimpleNamespace(), settings=_settings())
    assert ok is True
    assert meta["putWinSymbol"] == "SENSEX"


@pytest.mark.parametrize(
    "side,patch_path,fn",
    [
        ("CALL", "app.engines.put_slide_ce_mirror._collect_session_trades", session_call_win_meta),
        ("PUT", "app.engines.pe_win_ce_mirror._collect_session_trades", session_put_win_meta),
    ],
)
def test_scratch_exit_does_not_count_as_win(side, patch_path, fn):
    with patch(patch_path, return_value=[_win(side, "SENSEX", 120.0)]):
        ok, _ = fn(SimpleNamespace(), settings=_settings())
    assert ok is False


@patch("app.engines.put_slide_ce_mirror.put_slide_entry_unlock_armed", return_value=(False, "", {}))
@patch("app.engines.put_slide_ce_mirror._collect_session_trades")
def test_nifty_ce_chase_blocked_after_modest_sensex_ce_win(mock_trades, _mock_unlock):
    mock_trades.return_value = [_win("CALL", "SENSEX", 541.8, minutes_ago=5.0)]
    candidate = SimpleNamespace(mode="explosion", side=Side.CALL, symbol="NIFTY", strike=22700.0)
    blocked, reason, meta = ce_win_pe_mirror_call_chase_blocked(
        candidate, SimpleNamespace(), {}, settings=_settings(),
    )
    assert blocked is True
    assert reason == "ce_win_pe_mirror_block_cross_index_call"
    assert meta["callWinSymbol"] == "SENSEX"


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_armed", return_value=(False, "", {}))
@patch("app.engines.pe_win_ce_mirror._collect_session_trades")
def test_pe_mirror_nifty_pe_chase_blocked_after_modest_sensex_pe_win(mock_trades, _mock_unlock):
    mock_trades.return_value = [_win("PUT", "SENSEX", 541.8, minutes_ago=5.0)]
    candidate = SimpleNamespace(mode="explosion", side=Side.PUT, symbol="NIFTY", strike=22700.0)
    blocked, reason, meta = pe_win_ce_mirror_put_chase_blocked(
        candidate, SimpleNamespace(), {}, settings=_settings(),
    )
    assert blocked is True
    assert reason == "pe_win_ce_mirror_block_cross_index_put"
    assert meta["putWinSymbol"] == "SENSEX"


@patch(
    "app.engines.put_slide_ce_mirror._soft_index_slide_ok",
    return_value=(True, "ce_win_pe_mirror_soft_slide", {}),
)
@patch("app.engines.put_slide_ce_mirror._collect_session_trades")
def test_pe_leg_arms_after_modest_ce_win(mock_trades, _mock_slide):
    mock_trades.return_value = [_win("CALL", "SENSEX", 541.8)]
    armed, reason, _meta = ce_win_pe_mirror_armed(
        SimpleNamespace(), SimpleNamespace(), "NIFTY", settings=_settings(),
    )
    assert armed is True
    assert reason == "ce_win_pe_mirror"


@patch(
    "app.engines.pe_win_ce_mirror._soft_index_rally_ok",
    return_value=(True, "pe_win_ce_mirror_soft_rally", {}),
)
@patch("app.engines.pe_win_ce_mirror._collect_session_trades")
def test_ce_leg_arms_after_modest_pe_win(mock_trades, _mock_rally):
    mock_trades.return_value = [_win("PUT", "SENSEX", 541.8)]
    armed, reason, _meta = pe_win_ce_mirror_armed(
        SimpleNamespace(), SimpleNamespace(), "NIFTY", settings=_settings(),
    )
    assert armed is True
    assert reason == "pe_win_ce_mirror"


@pytest.mark.parametrize(
    "side,patch_path,fn",
    [
        ("CALL", "app.engines.put_slide_ce_mirror._collect_session_trades", ce_win_pe_mirror_call_chase_blocked),
        ("PUT", "app.engines.pe_win_ce_mirror._collect_session_trades", pe_win_ce_mirror_put_chase_blocked),
    ],
)
def test_fixed_inr_only_keeps_old_behaviour(side, patch_path, fn):
    candidate = SimpleNamespace(mode="explosion", side=Side(side), symbol="NIFTY", strike=22700.0)
    with (
        patch(patch_path, return_value=[_win(side, "SENSEX", 541.8)]),
        patch("app.engines.put_slide_ce_mirror.put_slide_entry_unlock_armed", return_value=(False, "", {})),
        patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_armed", return_value=(False, "", {})),
    ):
        blocked, _reason, _meta = fn(
            candidate, SimpleNamespace(), {}, settings=_settings(mirror_win_min_capital_pct=0.0),
        )
    assert blocked is False
