"""Open setup book must not drift without updating open_setup_policy.py."""

from app.config import Settings
from app.engines.open_setup_policy import (
    OPEN_SETUP_FROZEN_DEFAULTS,
    OPEN_SETUP_POLICY_ID,
    _open_setup_modules_paper_free,
    open_setup_policy_status,
    verify_open_setup_policy,
)


def test_open_setup_policy_defaults_aligned():
    settings = Settings()
    ok, drift = verify_open_setup_policy(settings)
    assert ok, drift


def test_open_setup_policy_status_snapshot():
    status = open_setup_policy_status(Settings())
    assert status["policyId"] == OPEN_SETUP_POLICY_ID
    assert status["aligned"] is True
    assert status["drift"] == []
    assert status["confirmedSession"] is None
    assert status["readyForLiveOpenBook"] is False
    assert status["execution"]["liveUsesSameOpenBook"] is True
    snap = status["snapshot"]
    assert snap["windowsIst"]["openSetupStart"] == "09:15"
    assert snap["windowsIst"]["openCautionUntil"] == "09:45"
    assert snap["sessionBooksIst"]["normalBookPostOpen"] == "09:45–15:45"
    assert snap["windowsIst"]["openRipFadeBypassUntil"] == "10:30"
    assert snap["frozenFields"] == OPEN_SETUP_FROZEN_DEFAULTS


def test_open_setup_modules_no_paper_live_branch():
    assert _open_setup_modules_paper_free() is True


def test_ready_for_live_when_confirmed_and_aligned():
    settings = Settings(open_setup_policy_confirmed_session="2026-11-06")
    status = open_setup_policy_status(settings)
    assert status["readyForLiveOpenBook"] is True
