"""Open-book capture: aligned lane waiver, rank nudge, fake-trap open bypass."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_entry_guards import detect_fake_explosion_trap
from app.engines.open_index_lane import validate_open_index_lane
from app.engines.open_setup_guards import (
    open_aligned_side_rank_bonus,
    open_counter_trend_side_rank_penalty,
    validate_open_setup_entry,
)
from app.models.schemas import Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
OPEN = datetime(2026, 11, 4, 9, 25, tzinfo=IST)
POST_OPEN = datetime(2026, 11, 4, 9, 50, tzinfo=IST)


def _cand(symbol: str, side: Side, strike: float, *, spot: float, alert: dict | None = None):
    snap = SimpleNamespace(symbol=symbol, spot=spot, dataAvailable=True, timestamp=OPEN)
    return SimpleNamespace(
        symbol=symbol,
        side=side,
        strike=strike,
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        alert=alert
        or {
            "tier": "EXPLODING",
            "ictBaseRelativeMovePct": 8.0,
            "localBaseMovePct": 8.0,
        },
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.open_index_lane.resolve_open_session_expiry_lane_pair")
def test_sensex_call_waives_non_lane_on_bullish_open_when_expiry_ce_is_nifty(
    mock_pair,
    mock_session,
):
    """Nov-4 style: expiry pair CE lane on NIFTY only — SENSEX CALL still allowed when aligned."""
    mock_session.return_value = {"open": 77000.0, "last": 77300.0}
    mock_pair.return_value = (
        "NIFTY",
        "SENSEX",
        {"mode": "expiry_pair", "primaryCeIndex": "NIFTY", "secondaryPeIndex": "SENSEX"},
    )
    s = Settings(
        open_setup_guards_enabled=True,
        open_index_lane_enabled=False,
        open_caution_non_lane_index_blocked=True,
        open_caution_aligned_side_lane_waiver_enabled=True,
        open_caution_side_align_index_enabled=True,
        open_caution_itm_band_enabled=False,
        open_session_expiry_lane_enabled=True,
    )
    cand = _cand("SENSEX", Side.CALL, 77200.0, spot=77300.0)
    snapshots = {
        "SENSEX": SymbolSnapshot(
            symbol="SENSEX",
            timestamp=OPEN,
            marketPhase="LIVE_MARKET",
            spot=77300.0,
            atmStrike=77300.0,
            dataAvailable=True,
        ),
        "NIFTY": SymbolSnapshot(
            symbol="NIFTY",
            timestamp=OPEN,
            marketPhase="LIVE_MARKET",
            spot=24000.0,
            atmStrike=24000.0,
            dataAvailable=True,
        ),
    }
    ok, reason, meta = validate_open_setup_entry(
        cand, settings=s, when=OPEN, snapshots=snapshots,
    )
    assert ok, reason
    assert meta.get("openAlignedSideLaneWaiver") is True


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_open_aligned_side_rank_bonus_and_counter_trend_penalty(mock_session):
    mock_session.return_value = {"open": 77000.0, "last": 77300.0}
    s = Settings(
        open_aligned_side_rank_bonus=40.0,
        open_counter_trend_side_rank_penalty=45.0,
    )
    ce = _cand("SENSEX", Side.CALL, 77200.0, spot=77300.0)
    pe = _cand("SENSEX", Side.PUT, 77400.0, spot=77300.0)
    assert open_aligned_side_rank_bonus(ce, settings=s, when=OPEN) == 40.0
    assert open_aligned_side_rank_bonus(pe, settings=s, when=OPEN) == 0.0
    assert open_counter_trend_side_rank_penalty(pe, settings=s, when=POST_OPEN) == 45.0
    assert open_counter_trend_side_rank_penalty(ce, settings=s, when=POST_OPEN) == 0.0


@patch("app.engines.index_tick_helpers.resolve_index_session")
def test_open_index_lane_first_lift_waiver_for_exploding_local_base(mock_session):
    mock_session.return_value = {"open": 77000.0, "last": 77300.0}
    s = Settings(
        open_index_lane_enabled=True,
        open_index_lane_require_first_lift=True,
        open_index_lane_open_rip_first_lift_waiver_enabled=True,
        open_index_lane_min_elite_score=80.0,
        open_index_lane_max_local_base_pct=15.0,
        open_sensex_call_lane_enabled=True,
        open_session_expiry_lane_enabled=False,
    )
    cand = _cand(
        "SENSEX",
        Side.CALL,
        77200.0,
        spot=77300.0,
        alert={
            "tier": "EXPLODING",
            "ictBaseRelativeMovePct": 9.0,
            "localBaseMovePct": 9.0,
        },
    )
    with patch("app.engines.trade_ranking.rank_entry_candidate") as mock_rank:
        mock_rank.return_value = {
            "evidence": {"setup": "V", "velocity3s": 2.0},
        }
        with patch("app.engines.elite_score_engine.infer_setup_type", return_value="V"):
            with patch(
                "app.engines.elite_score_engine.compute_elite_score",
                return_value=(92.0, "ELITE", "HOT"),
            ):
                with patch("app.engines.elite_score_engine.infer_stage", return_value="HOT"):
                    ok, reason, meta = validate_open_index_lane(
                        cand, settings=s, when=OPEN,
                    )
    assert ok, reason
    assert meta.get("firstLiftOpenRipWaiver") is True


def test_fake_trap_open_book_waives_conflict_on_aligned_exploding():
    s = Settings(
        fake_explosion_trap_enabled=True,
        fake_explosion_trap_open_book_conflict_bypass_enabled=True,
        fake_explosion_trap_open_book_max_local_base_pct=22.0,
        fake_explosion_trap_block_on_conflict=True,
        fake_explosion_trap_min_conflict_flags=3,
    )
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=OPEN,
        marketPhase="LIVE_MARKET",
        spot=77300.0,
        atmStrike=77300.0,
        dataAvailable=True,
    )
    event = SimpleNamespace(tier="EXPLODING", velocity_3s=2.5, daily_move_pct=12.0)
    cand = SimpleNamespace(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77300.0,
        mode="explosion",
        tier="EXPLODING",
        explosion_event=event,
        alert={"tier": "EXPLODING", "localBaseMovePct": 10.0},
        snap=snap,
    )
    with patch("app.engines.index_tick_helpers.resolve_index_session") as mock_sess:
        mock_sess.return_value = {"open": 77000.0, "last": 77300.0}
        with patch(
            "app.engines.explosion_entry_guards._session_peak_move",
            return_value=12.0,
        ):
            with patch(
                "app.engines.explosion_entry_guards._worst_or_expiry_chop_day",
                return_value=False,
            ):
                with patch(
                    "app.engines.explosion_entry_guards._post_small_win",
                    return_value=(False, {}),
                ):
                    with patch(
                        "app.engines.explosion_entry_guards._post_session_win",
                        return_value=(True, {"postSessionWin": True}),
                    ):
                        block, reason, meta = detect_fake_explosion_trap(
                            cand, snap, state=SimpleNamespace(),
                        )
    assert not block or meta.get("openBookFakeTrapWaiver") is True
    if block:
        assert reason != "fake_explosion_trap_conflict"
