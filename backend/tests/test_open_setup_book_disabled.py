"""Open setup book master switch must keep shadow/guards/lanes idle."""

from datetime import datetime

from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.open_index_lane import validate_open_index_lane
from app.engines.open_setup_policy import is_open_setup_book_enabled
from app.engines.open_setup_shadow import open_setup_shadow_select_active
from app.engines.pad_lane_capture import (
    open_caution_premium_fade_bypass,
    post_open_setup_premium_fade_bypass,
)

IST = ZoneInfo("Asia/Kolkata")


def test_defaults_open_book_master_off():
    settings = Settings()
    assert is_open_setup_book_enabled(settings) is False
    assert settings.open_setup_shadow_record_enabled is False
    assert settings.open_setup_guards_enabled is False


def test_shadow_loop_idle_when_book_off(monkeypatch):
    class _Phase:
        value = "LIVE_MARKET"

    monkeypatch.setattr(
        "app.engines.open_setup_shadow.get_market_phase",
        lambda: "LIVE_MARKET",
    )
    active, reason = open_setup_shadow_select_active()
    assert active is False
    assert reason == "open_setup_book_disabled"


def test_open_fade_waivers_off_when_book_disabled():
    when = datetime(2026, 11, 27, 9, 30, tzinfo=IST)
    assert open_caution_premium_fade_bypass(None, when=when) is False
    when_post = datetime(2026, 11, 27, 10, 0, tzinfo=IST)
    assert post_open_setup_premium_fade_bypass(None, when=when_post) is False


def test_open_index_lane_idle_with_defaults():
    class _Cand:
        symbol = "NIFTY"

    ok, reason, _meta = validate_open_index_lane(_Cand(), settings=Settings())
    assert ok is True
    assert reason == "ok"