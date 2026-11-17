"""Armed-base pullback wait — block chase fills far above ICT base (CE/PE)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.local_base_pullback_entry import local_base_pullback_blocks_entry
from app.models.schemas import PremiumChart, Side
from tests.mock_defaults import settings_mock


def _settings():
    s = settings_mock()
    s.local_base_pullback_entry_enabled = True
    s.local_base_pullback_max_chase_inr = 20.0
    s.local_base_pullback_max_chase_pct = 7.0
    s.local_base_pullback_min_drawdown_from_high_pct = 3.0
    return s


def _candidate(**overrides):
    base = dict(
        symbol="SENSEX",
        side=Side.CALL,
        strike=82100.0,
        tier="ELITE",
        mode="explosion",
        premium=582.0,
        alert={"ictBaseArmed": True, "ictBasePremium": 468.25},
        explosion_event=SimpleNamespace(tier="ELITE"),
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "premiumMomentum5Pct": 11.5},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_blocks_nov17_style_chase_above_base_call():
    settings = _settings()
    cand = _candidate()
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        blocked, reason, meta = local_base_pullback_blocks_entry(cand, None, settings=settings)
    assert blocked is True
    assert reason == "local_base_pullback_wait"
    assert meta["chaseAboveBaseInr"] > 20


def test_allows_when_within_chase_cap_put():
    settings = _settings()
    cand = _candidate(
        side=Side.PUT,
        premium=425.0,
        alert={"ictBaseArmed": True, "ictBasePremium": 410.0},
    )
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        blocked, reason, meta = local_base_pullback_blocks_entry(cand, None, settings=settings)
    assert blocked is False
    assert reason == "ok"
    assert meta.get("localBasePullbackFill") == "within_chase_cap"


def test_allows_after_pullback_from_session_high_ce():
    settings = _settings()
    chart = PremiumChart(
        direction="BULLISH",
        momentum5Pct=8.0,
        drawdownFromHighPct=-5.0,
    )
    cand = _candidate(premium=500.0, alert={"ictBaseArmed": True, "ictBasePremium": 468.25})
    with patch("app.engines.local_base_pullback_entry.get_settings", return_value=settings):
        blocked, reason, meta = local_base_pullback_blocks_entry(
            cand, None, premium_chart=chart, settings=settings,
        )
    assert blocked is False
    assert meta.get("localBasePullbackFill") == "pullback_from_high"