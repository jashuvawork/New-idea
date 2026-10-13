"""EOD replay live explosion book: anchored entries, dual-side slots, per-side stop cooldown."""

from datetime import datetime, timedelta
from typing import Any, Callable
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.eod_local_base_replay import _simulate_trade_from_entry, replay_local_base_day
from app.engines.index_tick_helpers import (
    _session_extremes,
    index_session_extremes,
    install_replay_session_extremes,
    restore_replay_session_extremes,
)

IST = ZoneInfo("Asia/Kolkata")
DATE = "2026-10-01"
STRIKE = 22500.0
OPPOSITE = {"CALL": "PUT", "PUT": "CALL"}


def _at(hhmmss: str) -> datetime:
    return datetime.fromisoformat(f"{DATE}T{hhmmss}").replace(tzinfo=IST)


def _tape(premium: Callable[[str, int], float], *, start: str = "10:00:00", minutes: int = 30) -> list[dict[str, Any]]:
    t0 = _at(start)
    batches = []
    for i in range(minutes * 6):
        ts = t0 + timedelta(seconds=10 * i)
        spot = 22500.0 + i * 0.5
        batches.append({
            "ts": ts.isoformat(),
            "contracts": [
                {
                    "key": f"NIFTY:{side}:{STRIKE:g}",
                    "symbol": "NIFTY",
                    "side": side,
                    "strike": STRIKE,
                    "premium": premium(side, i),
                    "oi": 100000,
                    "spot": spot,
                    "atmStrike": STRIKE,
                }
                for side in ("CALL", "PUT")
            ],
        })
    return batches


def _settings(**overrides: Any) -> Settings:
    base = {
        "eod_replay_live_explosion_book_enabled": True,
        "selector_best_only_enabled": True,
        "selector_best_only_dual_side_enabled": True,
        "explosion_cooldown_per_side_enabled": True,
        "explosion_reentry_cooldown_seconds": 600,
        "eod_replay_live_session_gates_enabled": False,
        "session_loss_pause_enabled": False,
        "open_side_confirmation_enabled": False,
        "elite_trade_engine_enabled": False,
        "daily_loss_stop_inr": 10_000_000.0,
        "radar_archive_dir": "",
    }
    base.update(overrides)
    return Settings().model_copy(update=base)


def _scripted_exit(tr, premium, tier, units, live_velocity_3s=0.0):
    if premium <= tr.entryPremium * 0.8:
        return "adaptive_stop_loss", (premium - tr.entryPremium) * units
    return None, 0.0


def _anchor(side: str, hhmmss: str) -> dict[str, Any]:
    return {
        "symbol": "NIFTY",
        "side": side,
        "strike": STRIKE,
        "ts": _at(hhmmss),
        "tier": "ELITE",
        "source": "live_entered",
        "liveGated": True,
    }


def _replay(batches, anchors, settings) -> dict[str, Any]:
    with patch("app.engines.eod_local_base_replay._load_batches", return_value=batches), \
         patch("app.engines.explosion_profit.evaluate_explosion_exit", side_effect=_scripted_exit):
        return replay_local_base_day(DATE, settings=settings, anchored_entries=anchors)


def _outcomes(report) -> list[tuple[str, str]]:
    return [(a["key"].split(":")[1], a["outcome"]) for a in report["anchors"]]


@pytest.mark.parametrize("first", ["CALL", "PUT"])
def test_dual_side_book_runs_ce_and_pe_together_one_leg_per_side(first):
    second = OPPOSITE[first]
    report = _replay(
        _tape(lambda side, i: 100.0 + 0.2 * i),
        [_anchor(first, "10:05:00"), _anchor(second, "10:05:30"), _anchor(first, "10:06:00")],
        _settings(),
    )

    assert report["mode"] == "anchored_live_entries"
    assert _outcomes(report) == [
        (first, "entered"),
        (second, "entered"),
        (first, "best_only_dual_side_same_side_open"),
    ]
    legs = {t["side"]: t for t in report["trades"]}
    assert legs[second]["concurrentWith"] == [f"NIFTY:{first}:{STRIKE:g}"]
    assert "concurrentWith" not in legs[first]


@pytest.mark.parametrize("first", ["CALL", "PUT"])
def test_single_slot_book_blocks_opposite_side_while_leg_open(first):
    report = _replay(
        _tape(lambda side, i: 100.0 + 0.2 * i),
        [_anchor(first, "10:05:00"), _anchor(OPPOSITE[first], "10:05:30")],
        _settings(selector_best_only_dual_side_enabled=False),
    )

    assert _outcomes(report) == [(first, "entered"), (OPPOSITE[first], "single_position_open")]


def _crash_side(stopped: str) -> Callable[[str, int], float]:
    def premium(side: str, i: int) -> float:
        if side == stopped and 30 <= i:
            return 70.0
        return 100.0 + 0.1 * i
    return premium


@pytest.mark.parametrize("stopped", ["CALL", "PUT"])
def test_per_side_stop_cooldown_blocks_only_the_stopped_side(stopped):
    other = OPPOSITE[stopped]
    report = _replay(
        _tape(_crash_side(stopped)),
        [_anchor(stopped, "10:04:00"), _anchor(stopped, "10:10:00"), _anchor(other, "10:10:00")],
        _settings(),
    )

    first = report["trades"][0]
    assert (first["side"], first["exitReason"], first["exitAt"]) == (stopped, "adaptive_stop_loss", "10:05:00")
    assert _outcomes(report) == [
        (stopped, "entered"),
        (stopped, "explosion_cooldown"),
        (other, "entered"),
    ]


@pytest.mark.parametrize("stopped", ["CALL", "PUT"])
def test_symbol_wide_stop_cooldown_blocks_both_sides_when_per_side_off(stopped):
    report = _replay(
        _tape(_crash_side(stopped)),
        [_anchor(stopped, "10:04:00"), _anchor(OPPOSITE[stopped], "10:10:00")],
        _settings(explosion_cooldown_per_side_enabled=False),
    )

    assert _outcomes(report) == [(stopped, "entered"), (OPPOSITE[stopped], "explosion_cooldown")]


@pytest.mark.parametrize("stopped", ["CALL", "PUT"])
def test_daily_loss_stop_admits_only_expiry_bypass_anchors(stopped):
    other = OPPOSITE[stopped]
    bypass = {**_anchor(stopped, "10:20:00"), "dailyLossStopBypass": True}
    report = _replay(
        _tape(_crash_side(stopped)),
        [_anchor(stopped, "10:04:00"), _anchor(other, "10:08:00"), bypass],
        _settings(daily_loss_stop_inr=100.0, expiry_daily_loss_stop_bypass_enabled=True),
    )

    assert _outcomes(report) == [
        (stopped, "entered"),
        (other, "portfolio_limit_or_daily_loss_stop"),
        (stopped, "entered"),
    ]
    assert [t["anchorTs"] for t in report["trades"]] == ["10:04:00", "10:20:00"]


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_anchor_without_tape_near_entry_is_reported(side):
    report = _replay(
        _tape(lambda s, i: 100.0, start="10:00:00", minutes=5),
        [_anchor(side, "09:30:00")],
        _settings(),
    )

    assert _outcomes(report) == [(side, "anchor_no_tape_near_entry")]
    assert report["trades"] == []


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_anchor_enters_on_nearest_tape_sample_across_a_gap(side):
    gapped = [b for b in _tape(lambda s, i: 100.0 + 0.2 * i) if not ("10:05:10" <= b["ts"][11:19] < "10:08:00")]
    report = _replay(gapped, [_anchor(side, "10:05:04")], _settings())

    assert _outcomes(report) == [(side, "entered")]
    assert report["trades"][0]["entryAt"] == "10:05:00"


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_exit_walk_sees_tape_index_and_scaled_velocity(side):
    entry = _at("10:00:00")
    forward = [(entry + timedelta(seconds=12 * k), 100.0 + 12.0 * k) for k in range(4)]
    spots = [(entry + timedelta(seconds=12 * k - 12), 22500.0 + 10.0 * k) for k in range(5)]
    seen: list[tuple[float, float, Any]] = []

    def capture(tr, premium, tier, units, live_velocity_3s=0.0):
        seen.append((live_velocity_3s, index_session_extremes("NIFTY").get("last"),
                     tr.entryContext.get("spotAtEntry")))
        return None, 0.0

    extremes = {"NIFTY": {"date": DATE, "open": 22490.0, "hi": 22500.0, "lo": 22490.0, "last": 22500.0}}
    token = install_replay_session_extremes(extremes)
    try:
        with patch("app.engines.explosion_profit.evaluate_explosion_exit", side_effect=capture):
            _simulate_trade_from_entry(
                symbol="NIFTY", side=side, strike=STRIKE, tier="ELITE", entry_ts=entry,
                entry_premium=100.0, base_premium=90.0, forward=forward,
                settings=_settings(), entry_ctx={}, spot_series=spots,
                session_extremes=extremes,
            )
        assert extremes["NIFTY"]["last"] == 22500.0
    finally:
        restore_replay_session_extremes(token)

    assert [round(v, 3) for v, _last, _spot in seen[1:]] == [3.0, 3.0, 3.0]
    assert [last for _v, last, _spot in seen] == [22510.0, 22520.0, 22530.0, 22540.0]
    assert {spot for _v, _last, spot in seen} == {22510.0}


def test_replay_extremes_do_not_leak_into_live_index_view():
    _session_extremes["NIFTY"] = {"date": DATE, "open": 1.0, "hi": 1.0, "lo": 1.0, "last": 1.0}
    try:
        report = _replay(_tape(lambda side, i: 100.0 + 0.2 * i), [_anchor("CALL", "10:05:00")], _settings())
        assert report["trades"]
        assert index_session_extremes("NIFTY")["last"] == 1.0
    finally:
        _session_extremes.pop("NIFTY", None)
