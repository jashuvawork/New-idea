"""Ensure legacy live-only gates stay off under Oct paper mirror live."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.chop_live_guards import armed_base_shallow_launch_blocked
from app.engines.live_paper_parity import (
    legacy_live_entry_narrowings_active,
    trading_rules_match_paper,
)
from app.models.schemas import Side
from tests.mock_defaults import settings_mock


def _frozen_live_mirror(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        legacy_live_narrow_stack_enabled=False,
        **kwargs,
    )


def test_legacy_live_entry_narrowings_false_on_mirror_live():
    s = _frozen_live_mirror()
    assert trading_rules_match_paper(s) is True
    assert legacy_live_entry_narrowings_active(s) is False


def test_armed_base_shallow_chop_skipped_under_paper_rules():
    settings = _frozen_live_mirror()
    event = SimpleNamespace(
        tier="ELITE",
        localBaseMovePct=8.0,
        peakMovePct=10.0,
        velocity3s=1.0,
        side=Side.CALL,
    )
    cand = SimpleNamespace(mode="explosion", explosion_event=event, alert={})
    snap = MagicMock()
    with patch(
        "app.engines.chop_live_guards.get_settings",
        return_value=settings,
    ), patch(
        "app.engines.explosion_entry_guards._regime_chopish",
        return_value=True,
    ), patch(
        "app.engines.explosion_entry_guards._midday_chop_active",
        return_value=True,
    ), patch(
        "app.engines.explosion_entry_guards._armed_base_launch_active",
        return_value=True,
    ), patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=10.0,
    ), patch(
        "app.engines.ict_breakout_monitor.analyze_explosion_event_ict",
        return_value={},
    ):
        blocked, reason, meta = armed_base_shallow_launch_blocked(cand, snap)
    assert blocked is False
    assert reason == ""
    assert meta.get("octPaperArmedBaseChopSkipped") is True


def test_deployment_status_exposes_top_level_live_paper_profile():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/deployment/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "livePaperProfile" in body
    assert isinstance(body["livePaperProfile"], dict)
    assert "entryGatesMatchPaper" in body["flags"]
    assert body["flags"]["entryGatesMatchPaper"] == body["livePaperProfile"].get(
        "entryGatesMatchPaper"
    )
