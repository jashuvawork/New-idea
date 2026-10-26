"""Selector explosion-pool entry blocks appear in radar funnel (SELECTOR_POOL)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.trade_selector import _record_pool_entry_gate
from app.models.schemas import Side
from app.services.radar_archive import record_top_radars
from app.services.radar_learning import build_funnel_report
from tests.test_radar_learning import _alert, _patch_settings, _settings, _snap

IST = ZoneInfo("Asia/Kolkata")


def test_selector_pool_gate_recorded_in_funnel_report(tmp_path):
    settings = _settings(tmp_path, selector_pool_entry_funnel_enabled=True)
    start = datetime(2026, 10, 26, 10, 15, tzinfo=IST)
    key = "NIFTY:PUT:22500"

    with _patch_settings(settings):
        with patch("app.config.get_settings", return_value=settings):
            record_top_radars(
                {
                    "NIFTY": _snap(
                        alerts=[{**_alert(side="PUT", strike=22500.0), "key": key}],
                    ),
                },
                now=start - timedelta(minutes=5),
                source="rest_snapshot",
            )
            _record_pool_entry_gate(
                "NIFTY",
                Side.PUT,
                22500.0,
                "entry_timing_blocked",
            )
            with patch(
                "app.services.trade_store.get_day_detail",
                return_value={"trades": []},
            ):
                report = build_funnel_report("2026-10-26")

    row = next((r for r in report["rows"] if r["key"] == key), None)
    assert row is not None
    pool_events = [
        ev for ev in row.get("timeline") or [] if ev.get("stage") == "SELECTOR_POOL"
    ]
    assert pool_events
    assert any(ev.get("reason") == "entry_timing_blocked" for ev in pool_events)
