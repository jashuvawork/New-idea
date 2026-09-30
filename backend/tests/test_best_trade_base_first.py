"""Base-first best trades — structural base + new base moments (CE + PE)."""

from types import SimpleNamespace

from app.engines.best_trade_policy import (
    best_trade_base_rank_adjustment,
    symmetric_best_trade_at_base_capture,
    symmetric_new_base_moment_evidence,
)
from app.engines.best_trade_policy import _mid_rip_best_trade_signals
from tests.mock_defaults import settings_mock


def _settings():
    s = settings_mock()
    s.symmetric_best_trade_capture_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.best_trade_base_first_enabled = True
    s.best_trade_new_base_moment_enabled = True
    s.best_trade_disable_mid_rip_when_base_first = True
    return s


def test_new_base_moment_elite_base_ready_near_pad():
    s = _settings()
    ev = {"localBaseMovePct": 14.0, "momentType": "ELITE_BASE_READY"}
    assert symmetric_new_base_moment_evidence(ev, settings=s) is True
    ok, reason = symmetric_best_trade_at_base_capture(ev, settings=s)
    assert ok is True
    assert reason in ("new_base_moment", "structural_base")


def test_new_base_rejected_when_local_too_extended():
    s = _settings()
    ev = {"localBaseMovePct": 45.0, "momentType": "ict_base_armed"}
    assert symmetric_new_base_moment_evidence(ev, settings=s) is False


def test_rank_bonus_at_base_penalty_off_base():
    s = _settings()
    base_c = SimpleNamespace(
        alert={"momentType": "ict_base_armed", "localBaseMovePct": 10.0},
        pretrade_meta={"causalRanking": {"evidence": {"ictBaseArmed": True}}},
        mode="explosion",
    )
    chase_c = SimpleNamespace(
        alert={"momentType": "exploding_signal", "localBaseMovePct": 55.0},
        pretrade_meta={"causalRanking": {"evidence": {"localBaseMovePct": 55.0}}},
        mode="explosion",
    )
    assert best_trade_base_rank_adjustment(base_c, settings=s) > 0
    assert best_trade_base_rank_adjustment(chase_c, settings=s) < 0


def test_mid_rip_disabled_under_base_first():
    s = _settings()
    alert = {"fastVerticalBurst": True, "velocity3s": 5.0, "tier": "ELITE"}
    assert _mid_rip_best_trade_signals(alert, {"eliteScore": 95}, tier="ELITE", settings=s) is False


def test_mid_rip_still_allowed_when_base_first_off():
    s = _settings()
    s.best_trade_base_first_enabled = False
    alert = {"fastVerticalBurst": True, "velocity3s": 5.0, "tier": "ELITE"}
    assert _mid_rip_best_trade_signals(alert, {"eliteScore": 95}, tier="ELITE", settings=s) is True
