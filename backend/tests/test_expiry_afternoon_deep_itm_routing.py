"""Sep03 — SENSEX expiry afternoon: deep ITM SENSEX PE over cross-index NIFTY explosion."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.bad_day_routing import (
    check_expiry_afternoon_cross_index_explosion,
    cross_index_elite_priority_bonus,
    expiry_afternoon_deep_itm_rank_adjustment,
    expiring_symbol_has_deep_itm_heatmap,
    is_expiry_deep_itm_candidate,
)
from app.engines.expiry_day_guards import check_expiry_candidate
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    HeatmapStrike,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _snap(
    symbol: str,
    *,
    expiry: str | None = None,
    spot: float = 77000.0,
    atm: float = 77000.0,
    heatmap: list[HeatmapStrike] | None = None,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=expiry or _today(),
        spot=spot,
        atmStrike=atm,
        regime=Regime.CHOP,
        tradeQualityScore=45.0,
        breadth=Breadth(bias="BEARISH", score=60, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.15, trendStrength=35),
        heatmap=heatmap or [],
    )


class _Cand:
    def __init__(
        self,
        symbol,
        side,
        strike,
        score,
        *,
        mode="explosion",
        tier="EXPLODING",
        snap=None,
        event=None,
    ):
        self.symbol = symbol
        self.side = side
        self.strike = strike
        self.score = score
        self.mode = mode
        self.tier = tier
        self.snap = snap
        self.explosion_event = event


def _settings(**overrides):
    s = MagicMock()
    s.expiry_day_guards_enabled = True
    s.expiry_afternoon_deep_itm_routing_enabled = True
    s.expiry_afternoon_deep_itm_min_steps = 2
    s.expiry_afternoon_deep_itm_rank_bonus = 50.0
    s.expiry_afternoon_cross_index_explosion_penalty = 45.0
    s.expiry_afternoon_cross_index_explosion_block_enabled = True
    s.expiry_afternoon_cross_index_explosion_bypass_min_score = 95.0
    s.expiry_afternoon_cross_index_explosion_bypass_min_move_pct = 120.0
    s.expiry_afternoon_explosion_confirm_enabled = True
    s.expiry_afternoon_elite_min_explosion_score = 85.0
    s.expiry_afternoon_elite_min_velocity_3s = 2.5
    s.expiry_afternoon_exploding_min_explosion_score = 90.0
    s.expiry_afternoon_exploding_min_velocity_3s = 3.0
    s.expiry_pm_itm_quick_enabled = True
    s.expiry_pm_itm_premium_max_inr = 280.0
    s.expiry_day_min_option_premium_inr = 15.0
    s.cross_index_elite_priority_enabled = True
    s.cross_index_elite_min_session_move_pct = 40.0
    s.cross_index_elite_priority_bonus = 22.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _sensex_deep_itm_heatmap() -> list[HeatmapStrike]:
    """77200+ PE deep ITM when spot ~77000 (PUT ITM = strike above spot)."""
    return [
        HeatmapStrike(strike=77000.0, putLtp=180.0),
        HeatmapStrike(strike=77200.0, putLtp=220.0),
        HeatmapStrike(strike=77400.0, putLtp=120.0),
    ]


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_expiring_symbol_deep_itm_heatmap_detected(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry=(datetime.now(IST).replace(day=1).strftime("%Y-%m-%d"))),
    }
    snaps["NIFTY"].optionExpiry = "2026-09-09"
    assert expiring_symbol_has_deep_itm_heatmap(snaps) is True


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_deep_itm_sensex_candidate_gets_rank_bonus(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry="2026-09-09", spot=24500.0, atm=24500.0),
    }
    sensex_cand = _Cand(
        "SENSEX", Side.PUT, 77200.0, 62.0, mode="quick_sideways", snap=snaps["SENSEX"],
    )
    assert is_expiry_deep_itm_candidate(sensex_cand, snaps) is True
    bonus = expiry_afternoon_deep_itm_rank_adjustment(
        sensex_cand, AutoTraderState(), snaps,
    )
    assert bonus == 50.0


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_sep03_nifty_explosion_penalized_when_sensex_deep_itm_available(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry="2026-09-09", spot=24500.0, atm=24500.0),
    }
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        premium=95.0,
        velocity_3s=2.62,
        velocity_9s=3.0,
        velocity_15s=4.0,
        volume_surge=2.0,
        explosion_score=80.5,
        tier="EXPLODING",
        reason="fake-rip",
        daily_move_pct=35.0,
        peak_move_pct=40.0,
    )
    nifty_cand = _Cand(
        "NIFTY", Side.PUT, 23850.0, 270.0, mode="explosion", tier="EXPLODING",
        snap=snaps["NIFTY"], event=event,
    )
    penalty = expiry_afternoon_deep_itm_rank_adjustment(
        nifty_cand, AutoTraderState(), snaps,
    )
    assert penalty == -45.0


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_cross_index_elite_bonus_suppressed_on_expiry_afternoon(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry="2026-09-09", spot=24500.0, atm=24500.0),
    }
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        premium=95.0,
        velocity_3s=4.0,
        velocity_9s=5.0,
        velocity_15s=6.0,
        volume_surge=2.5,
        explosion_score=92.0,
        tier="ELITE",
        reason="rip",
        daily_move_pct=80.0,
        peak_move_pct=85.0,
    )
    nifty_cand = _Cand(
        "NIFTY", Side.PUT, 23850.0, 270.0, mode="explosion", tier="ELITE",
        snap=snaps["NIFTY"], event=event,
    )
    assert cross_index_elite_priority_bonus(nifty_cand, snaps) == 0.0


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_sep03_nifty_explosion_blocked_by_pretrade(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry="2026-09-09", spot=24500.0, atm=24500.0),
    }
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        premium=95.0,
        velocity_3s=2.62,
        velocity_9s=3.0,
        velocity_15s=4.0,
        volume_surge=2.0,
        explosion_score=80.5,
        tier="EXPLODING",
        reason="fake-rip",
        daily_move_pct=35.0,
        peak_move_pct=40.0,
    )
    nifty_cand = _Cand(
        "NIFTY", Side.PUT, 23850.0, 270.0, mode="explosion", tier="EXPLODING",
        snap=snaps["NIFTY"], event=event,
    )
    ok, reason, meta = check_expiry_afternoon_cross_index_explosion(
        nifty_cand, AutoTraderState(), snaps,
    )
    assert ok is False
    assert reason == "expiry_afternoon_prefer_expiring_deep_itm"
    assert meta.get("expiryAfternoonDeepItmRouting") is True


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_check_expiry_candidate_blocks_sep03_nifty(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry="2026-09-09", spot=24500.0, atm=24500.0),
    }
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        premium=95.0,
        velocity_3s=2.62,
        velocity_9s=3.0,
        velocity_15s=4.0,
        volume_surge=2.0,
        explosion_score=80.5,
        tier="EXPLODING",
        reason="fake-rip",
        daily_move_pct=35.0,
        peak_move_pct=40.0,
    )
    nifty_cand = _Cand(
        "NIFTY", Side.PUT, 23850.0, 270.0, mode="explosion", tier="EXPLODING",
        snap=snaps["NIFTY"], event=event,
    )
    with patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True):
        ok, reason, _meta = check_expiry_candidate(nifty_cand, AutoTraderState(), snaps)
    assert ok is False
    assert reason in (
        "expiry_afternoon_prefer_expiring_deep_itm",
        "expiry_afternoon_exploding_score_below_90",
        "expiry_afternoon_exploding_v3_below_3",
    )


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.bad_day_routing.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.is_expiry_session", return_value=True)
@patch("app.engines.bad_day_routing.in_expiry_afternoon_window", return_value=True)
def test_sensex_deep_itm_wins_ranking_vs_nifty_explosion(_aft, _sess_bad, _sess_exp, mock_bad, mock_exp):
    """Sep03 geometry: SENSEX quick ITM should outrank NIFTY explosion after routing."""
    cfg = _settings()
    mock_bad.return_value = cfg
    mock_exp.return_value = cfg
    snaps = {
        "SENSEX": _snap("SENSEX", heatmap=_sensex_deep_itm_heatmap()),
        "NIFTY": _snap("NIFTY", expiry="2026-09-09", spot=24500.0, atm=24500.0),
    }
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        premium=95.0,
        velocity_3s=2.62,
        velocity_9s=3.0,
        velocity_15s=4.0,
        volume_surge=2.0,
        explosion_score=80.5,
        tier="EXPLODING",
        reason="fake-rip",
        daily_move_pct=35.0,
        peak_move_pct=40.0,
    )
    sensex_cand = _Cand(
        "SENSEX", Side.PUT, 77200.0, 62.0, mode="quick_sideways", snap=snaps["SENSEX"],
    )
    nifty_cand = _Cand(
        "NIFTY", Side.PUT, 23850.0, 95.0, mode="explosion", tier="EXPLODING",
        snap=snaps["NIFTY"], event=event,
    )
    sensex_final = sensex_cand.score + expiry_afternoon_deep_itm_rank_adjustment(
        sensex_cand, AutoTraderState(), snaps,
    )
    nifty_final = nifty_cand.score + expiry_afternoon_deep_itm_rank_adjustment(
        nifty_cand, AutoTraderState(), snaps,
    ) + cross_index_elite_priority_bonus(nifty_cand, snaps)
    assert sensex_final == 112.0
    assert nifty_final == 50.0
    assert sensex_final > nifty_final
