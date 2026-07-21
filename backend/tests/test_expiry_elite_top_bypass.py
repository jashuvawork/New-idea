"""Expiry-worst declining: unblock early-window ELITE tops only."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.expiry_day_guards import (
    alert_is_expiry_elite_top,
    check_expiry_candidate,
    check_expiry_entry_allowed,
    is_expiry_elite_top_candidate,
    snapshots_have_expiry_elite_top,
)
from app.engines.pretrade_validator import validate_candidate
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.expiry_day_guards_enabled = True
    s.expiry_worst_day_halt_entries = True
    s.expiry_worst_day_elite_top_bypass_enabled = True
    s.expiry_worst_day_elite_top_min_score = 70.0
    s.expiry_worst_day_elite_top_min_move_pct = 28.0
    s.expiry_worst_day_elite_top_max_move_pct = 55.0
    s.expiry_worst_day_elite_top_tiers_csv = "ELITE"
    s.expiry_worst_day_elite_top_composer_bypass = True
    s.expiry_worst_day_min_rank_score = 72.0
    s.expiry_morning_only = True
    s.expiry_pm_itm_quick_enabled = False
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 250.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_cheap_rip_min_premium_inr = 8.0
    s.explosion_cheap_rip_min_peak_pct = 25.0
    s.controlled_trading_enabled = True
    s.composer_hard_gate_enabled = True
    s.composer_bias_gate_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, expiry: str = "2026-07-21", direction: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry,
        spot=24170.0,
        atmStrike=24200.0,
        regime=Regime.CHOP,
        tradeQualityScore=48,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=-0.12,
            momentum15Pct=-0.2,
            trendStrength=45,
            orPosition="BELOW",
            dataAvailable=True,
        ),
        explosionAlerts=[
            {
                "side": "PUT",
                "strike": 24200.0,
                "tier": "ELITE",
                "explosionScore": 100.0,
                "premium": 58.0,
                "dailyMovePct": 35.0,
                "peakMovePct": 42.0,
                "tradeable": True,
            }
        ],
    )


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_alert_elite_top_accepts_early_window(mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    snap = _snap()
    assert alert_is_expiry_elite_top(snap.explosionAlerts[0], snap) is True


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_alert_elite_top_rejects_extended_chase(mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    snap = _snap()
    alert = {**snap.explosionAlerts[0], "dailyMovePct": 131.0, "peakMovePct": 202.0}
    assert alert_is_expiry_elite_top(alert, snap) is False


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_declining_halt_lifts_when_elite_top_on_radar(mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    snap = _snap()
    snaps = {"NIFTY": snap}
    state = AutoTraderState()
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-21"):
        with patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=True):
            with patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False):
                with patch(
                    "app.engines.expiry_day_guards.predict_worst_expiry_day",
                    return_value=(True, 65.0, ["chop_regime", "declining_session"]),
                ):
                    with patch("app.engines.expiry_day_guards._session_declining", return_value=True):
                        with patch(
                            "app.engines.expiry_day_guards.expiry_trades_cap_reached",
                            return_value=(False, "ok"),
                        ):
                            ok, reason, meta = check_expiry_entry_allowed(state, snaps)
    assert ok is True
    assert reason == "ok"
    assert meta.get("expiryWorstDayEliteTopBypass") is True
    assert meta.get("expiryWorstDayEliteTopOnly") is True


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_declining_halt_stays_when_only_chase_alerts(mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    snap = _snap()
    snap.explosionAlerts = [
        {
            "side": "PUT",
            "strike": 24200.0,
            "tier": "ELITE",
            "explosionScore": 100.0,
            "premium": 58.0,
            "dailyMovePct": 131.0,
            "peakMovePct": 202.0,
            "tradeable": True,
        }
    ]
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-21"):
        with patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=True):
            with patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False):
                with patch(
                    "app.engines.expiry_day_guards.predict_worst_expiry_day",
                    return_value=(True, 65.0, ["chop_regime"]),
                ):
                    with patch("app.engines.expiry_day_guards._session_declining", return_value=True):
                        with patch(
                            "app.engines.expiry_day_guards.expiry_trades_cap_reached",
                            return_value=(False, "ok"),
                        ):
                            ok, reason, _ = check_expiry_entry_allowed(
                                AutoTraderState(), {"NIFTY": snap},
                            )
    assert ok is False
    assert reason == "expiry_worst_day_declining_halt"
    assert snapshots_have_expiry_elite_top({"NIFTY": snap}) is False


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_candidate_blocks_scalp_allows_elite_top(mock_p, mock_s):
    cfg = _settings()
    mock_s.return_value = cfg
    mock_p.return_value = cfg
    snap = _snap()
    event = SimpleNamespace(
        daily_move_pct=35.0, peak_move_pct=42.0, explosion_score=100.0, tier="ELITE",
    )
    elite = SimpleNamespace(
        symbol="NIFTY", side=Side.PUT, strike=24200.0, score=120.0, mode="explosion",
        snap=snap, tier="ELITE", confidence=100.0, premium=58.0, explosion_event=event,
        alert=snap.explosionAlerts[0],
    )
    scalp = SimpleNamespace(
        symbol="NIFTY", side=Side.PUT, strike=24200.0, score=80.0, mode="scalp",
        snap=snap, tier="", confidence=50.0, premium=58.0, explosion_event=None, alert={},
    )
    with patch("app.engines.expiry_day_guards._today_str", return_value="2026-07-21"):
        with patch(
            "app.engines.expiry_day_guards.predict_worst_expiry_day",
            return_value=(True, 65.0, ["chop_regime"]),
        ):
            with patch("app.engines.expiry_day_guards._session_declining", return_value=True):
                with patch(
                    "app.engines.expiry_day_guards.check_expiry_explosion_open_block",
                    return_value=(False, "ok"),
                ):
                    with patch(
                        "app.engines.aligned_explosion_bypass.expiry_aligned_explosion_trade_allowed",
                        return_value=(True, "ok"),
                    ):
                        ok_e, reason_e, meta_e = check_expiry_candidate(
                            elite, AutoTraderState(), {"NIFTY": snap},
                        )
                        ok_s, reason_s, _ = check_expiry_candidate(
                            scalp, AutoTraderState(), {"NIFTY": snap},
                        )
    assert ok_e is True
    assert meta_e.get("expiryEliteTop") is True
    assert ok_s is False
    assert reason_s == "expiry_worst_day_elite_top_only"
    assert is_expiry_elite_top_candidate(elite) is True


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.composer_market_monitor.get_latest_brief")
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
def test_validate_candidate_composer_bypass_real_path(mock_p, mock_exp, mock_brief, mock_s):
    """Real validate_candidate: standDown must not block elite top; still blocks scalp."""
    cfg = _settings()
    cfg.dual_mode_enabled = False
    mock_s.return_value = cfg
    mock_exp.return_value = cfg
    mock_p.return_value = cfg
    mock_brief.return_value = {"standDown": True, "tradeBias": "STAND_ASIDE"}
    snap = _snap()
    event = SimpleNamespace(
        daily_move_pct=35.0, peak_move_pct=42.0, explosion_score=100.0, tier="ELITE",
        side=Side.PUT,
    )
    elite = SimpleNamespace(
        symbol="NIFTY", side=Side.PUT, strike=24200.0, score=120.0, mode="explosion",
        snap=snap, tier="ELITE", confidence=100.0, premium=58.0, explosion_event=event,
        alert=snap.explosionAlerts[0], tqs=48.0, pretrade_meta=None,
    )
    scalp = SimpleNamespace(
        symbol="NIFTY", side=Side.PUT, strike=24200.0, score=80.0, mode="scalp",
        snap=snap, tier="", confidence=50.0, premium=58.0, explosion_event=None,
        alert={}, tqs=48.0, pretrade_meta=None,
    )
    with patch("app.engines.chop_day_guards.is_chop_session", return_value=True):
        with patch(
            "app.engines.extreme_explosion_moment.is_extreme_explosion_all_in_bypass",
            return_value=False,
        ):
            with patch(
                "app.engines.extreme_explosion_moment.is_high_mover_elite_bypass",
                return_value=False,
            ):
                with patch(
                    "app.engines.pretrade_validator.check_min_entry_interval",
                    return_value=(False, "interval_sentinel"),
                ):
                    ok, reason, meta = validate_candidate(
                        elite, AutoTraderState(), session_trades=[],
                        snapshots={"NIFTY": snap},
                    )
                    ok_s, reason_s, _ = validate_candidate(
                        scalp, AutoTraderState(), session_trades=[],
                        snapshots={"NIFTY": snap},
                    )
    assert meta.get("composerStandDownBypass") == "elite_top"
    assert reason == "interval_sentinel"  # passed composer, hit next gate
    assert ok_s is False
    assert reason_s == "composer_stand_down"
