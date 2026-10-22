"""Hard ₹450 tradeable ceiling + live exit margin-rejection backoff."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.auto_trader import _live_exit_order_submission_blocked
from app.engines.premium_filter import (
    explosion_tradeable_max_premium_inr,
    premium_in_band,
    premium_reject_reason,
)
from app.services.order_executor import live_order_fill_margin_blocked

IST = ZoneInfo("Asia/Kolkata")


def test_settings_default_tradeable_ceiling_is_450():
    s = Settings()
    assert explosion_tradeable_max_premium_inr(s) == 450.0
    assert s.expiry_itm_explosion_scan_max_premium_inr == 450.0


def test_premium_filter_rejects_sensex_style_758_ltp():
    assert premium_in_band(758.8, mode="explosion", peak_move_pct=35.0) is False
    assert premium_reject_reason(758.8, mode="explosion") == "premium_above_450"


def test_premium_filter_accepts_up_to_450():
    assert premium_in_band(450.0, mode="explosion", peak_move_pct=35.0) is True
    assert premium_in_band(449.5, mode="default") is True


def test_live_order_fill_margin_blocked_detects_upstox_message():
    fill = {
        "status": "rejected",
        "statusMessage": "You need additional margin of Rs. 1024000.00 to place this order",
    }
    assert live_order_fill_margin_blocked(fill) is True


def test_live_exit_submission_blocked_after_margin_reject():
    settings = Settings()
    broker_ctx = {"brokerExitMarginBlocked": True}
    assert _live_exit_order_submission_blocked(broker_ctx, settings) is True


def test_tradeable_max_ignores_magicmock_missing_ict_cap():
    """Partial MagicMock settings must not collapse ceiling to float(mock)==1."""
    s = MagicMock()
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 300.0
    s.explosion_max_premium_inr = 400.0
    assert explosion_tradeable_max_premium_inr(s) == 300.0
    with patch("app.engines.premium_filter.get_settings", return_value=s):
        assert premium_in_band(16.0, mode="explosion", peak_move_pct=33.0) is True


def test_live_exit_submission_throttled_after_generic_reject():
    settings = Settings()
    settings.live_exit_order_retry_seconds = 90
    broker_ctx = {
        "brokerExitRejectedAt": (datetime.now(IST) - timedelta(seconds=10)).isoformat(),
    }
    assert _live_exit_order_submission_blocked(broker_ctx, settings) is True
    broker_ctx["brokerExitRejectedAt"] = (
        datetime.now(IST) - timedelta(seconds=120)
    ).isoformat()
    assert _live_exit_order_submission_blocked(broker_ctx, settings) is False
