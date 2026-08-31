"""Coil-armed session lift — a strongly-ripe near-base coil lifts a chop/worst-day halt (opt-in)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines import top_signal_session_lift as tsl


def _settings(**over):
    s = SimpleNamespace(
        top_signal_session_lift_enabled=True,
        coil_armed_session_lift_enabled=True,
        coil_armed_session_lift_min_readiness=75.0,
        coil_armed_session_lift_max_base_move_pct=12.0,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _alert(side="CALL", coiling=True, predicted="CALL", readiness=80.0,
           base_move=6.0, tier="ELITE", ftv=True):
    return {
        "side": side, "coilCoiling": coiling, "coilPredictedSide": predicted,
        "coilReadinessScore": readiness, "ictBaseRelativeMovePct": base_move,
        "tier": tier, "ictFlatThenVertical": ftv,
    }


def test_ripe_coil_qualifies_when_enabled():
    with patch.object(tsl, "get_settings", return_value=_settings()):
        assert tsl._alert_is_coil_armed_top(_alert()) is True


def test_disabled_by_default():
    with patch.object(tsl, "get_settings", return_value=_settings(coil_armed_session_lift_enabled=False)):
        assert tsl._alert_is_coil_armed_top(_alert()) is False


def test_low_readiness_does_not_lift():
    with patch.object(tsl, "get_settings", return_value=_settings()):
        assert tsl._alert_is_coil_armed_top(_alert(readiness=60.0)) is False


def test_side_mismatch_does_not_lift():
    with patch.object(tsl, "get_settings", return_value=_settings()):
        assert tsl._alert_is_coil_armed_top(_alert(side="CALL", predicted="PUT")) is False


def test_too_far_off_base_does_not_lift():
    with patch.object(tsl, "get_settings", return_value=_settings()):
        assert tsl._alert_is_coil_armed_top(_alert(base_move=20.0)) is False


def test_non_top_tier_without_structure_does_not_lift():
    with patch.object(tsl, "get_settings", return_value=_settings()):
        assert tsl._alert_is_coil_armed_top(_alert(tier="BUILDING", ftv=False)) is False


def test_snapshots_have_coil_armed_top_signal():
    snap = SimpleNamespace(dataAvailable=True, explosionAlerts=[_alert()])
    with patch.object(tsl, "get_settings", return_value=_settings()):
        assert tsl.snapshots_have_coil_armed_top_signal({"NIFTY": snap}) is True
    # disabled → false
    with patch.object(tsl, "get_settings", return_value=_settings(coil_armed_session_lift_enabled=False)):
        assert tsl.snapshots_have_coil_armed_top_signal({"NIFTY": snap}) is False
