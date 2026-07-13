"""Volume awakening + extreme-move bad-day bypass for flat-then-vertical PE rips."""

from unittest.mock import MagicMock, patch

from app.engines.bad_day_routing import _extreme_explosion_bypass, check_bad_day_candidate
from app.engines.explosion_detector import (
    ExplosionEvent,
    _volume_awakening,
    scan_chain_explosions,
)
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot


def _settings() -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.min_option_premium_inr = 20.0
    s.explosion_max_premium_inr = 800.0
    s.max_option_premium_inr = 175.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.all_day_explosion_min_score = 38.0
    s.open_premium_min_move_pct = 25.0
    s.explosion_deep_otm_min_premium_inr = 3.0
    s.open_premium_explosion_enabled = True
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_volume_awaken_min = 25000
    s.explosion_volume_awaken_min_velocity_3s = 1.0
    return s


def test_volume_awakening_detects_flat_then_rip():
    s = _settings()
    assert _volume_awakening(48200, 2.5, 5.0, s) is True
    assert _volume_awakening(1000, 2.5, 5.0, s) is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_awakens_76900_pe_on_volume_spike(mock_get_settings, _open):
    mock_get_settings.return_value = _settings()
    chain = [
        {
            "strike_price": 76900,
            "put_options": {"ltp": 46.66, "volume": 500},
            "call_options": {"ltp": 5.0, "volume": 100},
        },
    ]
    scan_chain_explosions("SENSEX", chain, spot=77600.0, atm=77600.0)
    chain[0]["put_options"] = {"ltp": 120.0, "volume": 48000}
    events = scan_chain_explosions("SENSEX", chain, spot=77600.0, atm=77600.0)
    puts = [e for e in events if e.strike == 76900 and e.side == Side.PUT]
    assert puts, "76900 PE should awaken on volume spike"
    assert puts[0].tier in ("BUILDING", "EXPLODING", "ELITE")


def test_extreme_explosion_bypasses_bad_day_rank():
    from dataclasses import dataclass

    @dataclass
    class C:
        mode: str
        score: float
        explosion_event: ExplosionEvent

    ev = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76900.0,
        premium=400.0,
        velocity_3s=10.0,
        velocity_9s=20.0,
        velocity_15s=5.0,
        volume_surge=3.0,
        explosion_score=72.0,
        tier="EXPLODING",
        reason="test",
        daily_move_pct=4520.0,
    )
    c = C(mode="explosion", score=72.0, explosion_event=ev)
    assert _extreme_explosion_bypass(c) is True
