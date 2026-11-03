"""Exec chart bypass must see causal rank from pretrade (not only radar alert)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.entry_context import alert_for_execution_chart
from app.engines.pad_lane_capture import post_open_setup_premium_fade_bypass

IST = ZoneInfo("Asia/Kolkata")
POST_OPEN = datetime(2026, 11, 2, 10, 5, tzinfo=IST)


def test_alert_for_execution_chart_merges_causal_ranking():
    cand = SimpleNamespace(
        alert={"symbol": "NIFTY", "side": "CALL", "tier": "ELITE", "firstLift": True},
        pretrade_meta={"causalRanking": {"rankScore": 91.5, "grade": "A"}},
    )
    merged = alert_for_execution_chart(cand)
    assert merged is not None
    assert merged["causalRankScore"] == 91.5
    assert merged["causalGrade"] == "A"


@patch("app.engines.pad_lane_capture.get_settings")
def test_post_open_bypass_uses_merged_causal_rank(mock_settings):
    mock_settings.return_value = MagicMock(
        post_open_setup_premium_fade_fill_enabled=True,
        shallow_otm_local_base_min_move_pct=2.0,
        open_caution_premium_fade_max_local_base_pct=28.0,
        open_caution_premium_fade_min_rank_score=90.0,
        open_caution_premium_fade_allow_grade_s=True,
        open_caution_itm_band_enabled=False,
    )
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 23400.0,
        "tier": "ELITE",
        "firstLift": True,
        "localBaseMovePct": 10.0,
    }
    assert post_open_setup_premium_fade_bypass(
        alert,
        SimpleNamespace(tier="ELITE"),
        when=POST_OPEN,
        causal_rank_score=92.0,
        causal_grade="A",
    )
