"""Flat->vertical setup quality scorer."""

from unittest.mock import MagicMock

from app.engines.ict_breakout_monitor import flat_vertical_quality


def _settings():
    s = MagicMock()
    s.ict_flat_base_max_range_pct = 8.0
    s.elite_local_base_max_move_pct = 40.0
    return s


def _q(**kw):
    base = dict(
        flat=True, flat_dev=1.0, base_len=12, base_rel_move=25.0,
        local_swing_base=False, displacement=True, velocity_3s=3.0,
        fvg=True, vol_awaken=True, volume_surge=3.5, early_min=28.0, settings=_settings(),
    )
    base.update(kw)
    return flat_vertical_quality(**base)


def test_textbook_flat_vertical_is_top_grade():
    q, grade = _q()
    assert q >= 85 and grade == "A+"


def test_tighter_longer_coil_scores_higher():
    tight, _ = _q(flat_dev=0.5, base_len=14)
    loose, _ = _q(flat_dev=7.5, base_len=4)
    assert tight > loose


def test_late_chase_scores_lower_than_near_base():
    near, _ = _q(base_rel_move=25.0)
    chase, _ = _q(base_rel_move=90.0)
    assert near > chase


def test_no_heat_no_volume_downgrades():
    cold, grade = _q(displacement=False, velocity_3s=0.5, fvg=False, vol_awaken=False, volume_surge=1.0)
    assert cold < 70 and grade in ("B", "C")


def test_v_base_scores_below_tight_flat():
    v_base, _ = flat_vertical_quality(
        flat=False, flat_dev=0.0, base_len=10, base_rel_move=25.0, local_swing_base=True,
        displacement=True, velocity_3s=3.0, fvg=True, vol_awaken=True, volume_surge=3.5,
        early_min=28.0, settings=_settings(),
    )
    tight_flat, _ = _q(flat_dev=0.5)
    assert v_base < tight_flat


def test_no_base_zero():
    q, grade = flat_vertical_quality(
        flat=False, flat_dev=0.0, base_len=0, base_rel_move=0.0, local_swing_base=False,
        displacement=False, velocity_3s=0.0, fvg=False, vol_awaken=False, volume_surge=1.0,
        early_min=28.0, settings=_settings(),
    )
    assert q == 0.0 and grade == ""
