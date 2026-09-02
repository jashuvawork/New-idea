"""Bullish local-base pad session bypass — Aug27 afternoon armed_base_launch miss."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from tests.fixtures.radar_archives import ensure_aug27_archive
from app.engines.bullish_local_base import (
    alert_is_bullish_local_base_pad_entry,
    snapshots_have_bullish_local_base_pad,
)
from app.engines.elite_never_block import top_explosion_must_take_active
from app.engines.expiry_day_guards import check_expiry_entry_allowed
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE = "/tmp/radar/radar-2026-08-27.zip"


def _aug27_archive_path() -> Path:
    return ensure_aug27_archive(ARCHIVE)


def _settings(**overrides) -> Settings:
    cfg = Settings()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _load_afternoon_alert() -> tuple[dict, dict]:
    archive = _aug27_archive_path()
    with zipfile.ZipFile(archive) as zf:
        row = next(
            r
            for r in json.loads(zf.read("all_radars.json"))
            if r.get("key") == "SENSEX:PUT:77300"
        )
    return dict(row["alert"]), dict(row.get("context") or {})


def _snap(ctx: dict) -> SymbolSnapshot:
    sc = ctx.get("spotChart") or {}
    alert, _ = _load_afternoon_alert()
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 27, 12, 43, 41, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 77350),
        atmStrike=float(ctx.get("atmStrike") or 77300),
        tradeQualityScore=float(ctx.get("tradeQualityScore") or 53.5),
        optionExpiry="2026-08-27",
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction=sc.get("direction", "BEARISH"),
            momentum5Pct=float(sc.get("momentum5Pct") or -0.2),
            recommendedSide="PUT",
        ),
        explosionAlerts=[alert],
    )


@patch("app.engines.bullish_local_base.get_settings")
def test_afternoon_alert_qualifies_as_bullish_pad_entry(mock_settings):
    mock_settings.return_value = _settings()
    alert, ctx = _load_afternoon_alert()
    snap = _snap(ctx)
    assert alert_is_bullish_local_base_pad_entry(alert, snap) is True
    assert snapshots_have_bullish_local_base_pad({"SENSEX": snap}) is True


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.bullish_local_base.get_settings")
def test_afternoon_pad_must_take_at_21pct_local_base(mock_bull, mock_enb):
    cfg = _settings()
    mock_bull.return_value = cfg
    mock_enb.return_value = cfg
    alert, ctx = _load_afternoon_alert()
    snap = _snap(ctx)
    event = SimpleNamespace(
        side=Side.PUT,
        strike=77300.0,
        tier="ELITE",
        explosion_score=100.0,
        premium=83.95,
        local_base_move_pct=21.1,
    )
    assert top_explosion_must_take_active(
        tier="ELITE", event=event, alert=alert, snap=snap,
    ) is True


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=True)
@patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False)
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.expiry_day_guards.predict_worst_expiry_day", return_value=(True, 65.0, ["chop"]))
@patch("app.engines.expiry_day_guards.expiry_trades_cap_reached", return_value=(False, ""))
@patch("app.engines.expiry_day_guards._session_declining", return_value=True)
@patch("app.engines.bullish_local_base.get_settings")
def test_declining_halt_lifts_for_bullish_afternoon_pad(
    mock_bull,
    _declining,
    _cap,
    _worst,
    _expiry_sess,
    _eve,
    _morning,
    mock_expiry_settings,
):
    cfg = _settings(expiry_morning_only=True)
    mock_bull.return_value = cfg
    mock_expiry_settings.return_value = cfg
    alert, ctx = _load_afternoon_alert()
    snap = _snap(ctx)
    ok, reason, meta = check_expiry_entry_allowed(AutoTraderState(), {"SENSEX": snap})
    assert ok is True, (reason, meta)


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=False)
@patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False)
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.expiry_day_guards.predict_worst_expiry_day", return_value=(False, 0.0, []))
@patch("app.engines.expiry_day_guards.expiry_trades_cap_reached", return_value=(False, ""))
@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=False)
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
@patch("app.engines.bullish_local_base.get_settings")
def test_expiry_afternoon_wait_lifts_for_bullish_pad(
    mock_bull,
    _aft,
    _all_day,
    _cap,
    _worst,
    _expiry_sess,
    _eve,
    _morning,
    mock_expiry_settings,
):
    cfg = _settings(expiry_morning_only=True)
    mock_bull.return_value = cfg
    mock_expiry_settings.return_value = cfg
    alert, ctx = _load_afternoon_alert()
    snap = _snap(ctx)
    ok, reason, meta = check_expiry_entry_allowed(AutoTraderState(), {"SENSEX": snap})
    assert ok is True, (reason, meta)
    assert meta.get("expiryAfternoonLocalBasePad") is True
