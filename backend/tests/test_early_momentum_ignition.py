"""Early momentum-ignition at the local base — catch the FTV before the ~15% floor (opt-in)."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.ict_breakout_monitor import (
    _early_momentum_ignition_at_base_readiness,
)


def _settings(**over):
    s = SimpleNamespace(
        early_momentum_ignition_enabled=True,
        early_momentum_ignition_min_move_pct=1.0,
        early_momentum_ignition_max_move_pct=10.0,
        early_momentum_ignition_min_velocity_3s=1.0,
        early_momentum_ignition_min_vol_surge=2.0,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _event(side="CALL", tier="ELITE", v3=2.0, v9=1.4, vol_surge=2.5, strike=24150.0):
    return SimpleNamespace(
        side=side, tier=tier, velocity_3s=v3, velocity_9s=v9,
        volume_surge=vol_surge, strike=strike,
        base_relative_move_pct=6.0,
    )


def _ict(base_move=6.0, armed=True):
    return SimpleNamespace(
        base_armed=armed, local_swing_base=armed,
        base_relative_move_pct=base_move, volume_awakening=True,
    )


def _snap(spot=24200.0, atm=24200.0, symbol="NIFTY"):
    return SimpleNamespace(symbol=symbol, spot=spot, atmStrike=atm)


def test_ignition_fires_near_base_with_acceleration_and_volume():
    """The Aug31 24150 CE shape: ELITE, ~6% off base, v3>v9, volume → early entry."""
    with patch("app.engines.ict_breakout_monitor.get_settings", return_value=_settings()):
        ok, reason = _early_momentum_ignition_at_base_readiness(
            snap=_snap(), event=_event(v3=2.0, v9=1.4), ict=_ict(6.0),
            alert={"tier": "ELITE"}, settings=_settings(),
        )
    assert ok is True
    assert reason == "early_momentum_ignition_at_base"


def test_disabled_by_default_is_noop():
    s = _settings(early_momentum_ignition_enabled=False)
    ok, reason = _early_momentum_ignition_at_base_readiness(
        snap=_snap(), event=_event(), ict=_ict(), alert={"tier": "ELITE"}, settings=s,
    )
    assert ok is False
    assert reason == ""


def test_does_not_fire_when_fading_v3_below_v9():
    """A fading blip (v3 < v9) is not an ignition."""
    ok, _ = _early_momentum_ignition_at_base_readiness(
        snap=_snap(), event=_event(v3=1.1, v9=2.5), ict=_ict(6.0),
        alert={"tier": "ELITE"}, settings=_settings(),
    )
    assert ok is False


def test_does_not_fire_past_max_move_band():
    """Already 18% off base = late chase, not near-base ignition."""
    ok, _ = _early_momentum_ignition_at_base_readiness(
        snap=_snap(), event=_event(), ict=_ict(18.0),
        alert={"tier": "ELITE", "ictBaseRelativeMovePct": 18.0}, settings=_settings(),
    )
    assert ok is False


def test_requires_top_tier():
    ok, _ = _early_momentum_ignition_at_base_readiness(
        snap=_snap(), event=_event(tier="BUILDING"), ict=_ict(6.0),
        alert={"tier": "BUILDING"}, settings=_settings(),
    )
    assert ok is False


def test_requires_volume_or_cvd():
    ev = _event(vol_surge=0.5)
    ict = _ict(6.0)
    ict.volume_awakening = False
    ok, _ = _early_momentum_ignition_at_base_readiness(
        snap=_snap(), event=ev, ict=ict,
        alert={"tier": "ELITE"}, settings=_settings(),
    )
    assert ok is False


def test_requires_atm_itm_not_otm():
    """Deep OTM CALL (strike far above spot) must not fire early."""
    ok, reason = _early_momentum_ignition_at_base_readiness(
        snap=_snap(spot=24000.0, atm=24000.0),
        event=_event(strike=24600.0), ict=_ict(6.0),
        alert={"tier": "ELITE"}, settings=_settings(),
    )
    assert ok is False
    assert reason == "early_ignition_requires_atm_itm"


def test_symmetric_for_put():
    with patch("app.engines.ict_breakout_monitor.get_settings", return_value=_settings()):
        ok, reason = _early_momentum_ignition_at_base_readiness(
            snap=_snap(spot=24200.0, atm=24200.0),
            event=_event(side="PUT", strike=24200.0, v3=2.0, v9=1.4),
            ict=_ict(6.0), alert={"tier": "EXPLODING"}, settings=_settings(),
        )
    assert ok is True
    assert reason == "early_momentum_ignition_at_base"
