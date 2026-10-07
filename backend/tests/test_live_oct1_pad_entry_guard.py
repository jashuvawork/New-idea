"""Oct 1 pad guard — block session-high chase under live paper parity."""

from types import SimpleNamespace

from app.engines.live_oct1_pad_entry_guard import live_oct1_pad_entry_blocked
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock


def test_blocks_oct7_style_chase_at_session_high():
    """NIFTY 22700 CE @ ₹158: local pad % ok but premium at session high."""
    s = settings_mock(
        live_paper_parity_enabled=True,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        best_trade_sep917_base_shape_align_enabled=True,
        best_trade_base_first_enabled=True,
    )
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=158.11,
        alert={
            "tier": "ELITE",
            "momentType": "v_rip_session_low",
            "ictBaseReadinessReason": "v_rip_session_low_ready",
            "localBaseMovePct": 6.8,
            "premium": 158.11,
            "sessionLowPremium": 122.0,
            "sessionPeakPremium": 158.7,
        },
        pretrade_meta={},
        liveEntryScoreMeta={
            "sessionRangePosition": 0.98,
            "drawdownFromHighPct": 0.0,
        },
    )
    blocked, reason, meta = live_oct1_pad_entry_blocked(cand, settings=s)
    assert blocked is True
    assert reason in (
        "live_oct1_chase_at_session_high",
        "live_oct1_chase_session_range_high",
    )
    assert meta.get("nearBaseShape") is True


def test_allows_pad_fill_off_session_high():
    s = settings_mock(
        live_paper_parity_enabled=True,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        best_trade_sep917_base_shape_align_enabled=True,
        best_trade_base_first_enabled=True,
    )
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=124.0,
        alert={
            "tier": "ELITE",
            "momentType": "v_rip_session_low",
            "ictBaseReadinessReason": "v_rip_session_low_ready",
            "localBaseMovePct": 8.0,
            "premium": 124.0,
            "sessionLowPremium": 118.0,
            "sessionPeakPremium": 158.0,
        },
        pretrade_meta={},
        liveEntryScoreMeta={
            "sessionRangePosition": 0.15,
            "drawdownFromHighPct": -21.5,
        },
    )
    blocked, reason, _ = live_oct1_pad_entry_blocked(cand, settings=s)
    assert blocked is False
    assert reason == ""
