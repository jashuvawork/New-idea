"""High-conviction base rip → max lots + hold longer (Jul22 SENSEX 77200 PE)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_confidence import (
    is_elevated_size_entry,
    is_high_conviction_entry,
    trade_is_high_conviction,
)
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.high_conviction_sizing_enabled = True
    s.high_conviction_min_score = 90.0
    # Rescaled display cutovers (was 85 / 90 on old 20–95 clamp).
    s.high_conviction_min_chart_confidence = 56.9
    s.missed_explosion_promote_min_move_pct = 28.0
    s.missed_explosion_promote_max_move_pct = 55.0
    s.elevated_size_enabled = True
    s.elevated_size_min_score = 65.0
    s.elevated_size_min_chart_confidence = 58.8
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(direction="BEARISH", breadth="BEARISH"):
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.TREND_EXPANSION,
        spot=77200.0,
        atmStrike=77200.0,
        tradeQualityScore=60,
        breadth=Breadth(bias=breadth, score=40, aligned=True),
        spotChart=SpotChart(
            direction=direction, momentum5Pct=-0.25, momentum15Pct=-0.4,
            trendStrength=72, orPosition="BELOW", emaBias=direction,
            candleBias=direction, macdBias=direction, rsi=38, spot=77200.0,
        ),
    )


@patch("app.engines.explosion_confidence.get_settings")
def test_accepts_jul22_sensex_pe(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=32.0, chart_confidence=95.0,
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_low_score(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=80.0,
        move_pct=32.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_low_chart_conf(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=32.0, chart_confidence=50.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_extended_chase(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=90.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_wrong_side(mock_s):
    mock_s.return_value = _settings()
    # CALL on a bearish chart+breadth → not high conviction
    assert is_high_conviction_entry(
        side=Side.CALL, snap=_snap(direction="BEARISH", breadth="BEARISH"),
        tier="ELITE", score=100.0, move_pct=32.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_rejects_non_elite(mock_s):
    mock_s.return_value = _settings()
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=100.0,
        move_pct=32.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_elevated_accepts_strong_exploding_base(mock_s):
    """SENSEX 76800 PE: EXPLODING 73.7, conf 95, 48% base → elevated (not high-conv)."""
    mock_s.return_value = _settings()
    assert is_elevated_size_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=73.7,
        move_pct=48.0, chart_confidence=95.0,
    ) is True
    # but NOT full high-conviction (EXPLODING/73 < ELITE/90)
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=73.7,
        move_pct=48.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_elevated_rejects_extended_move(mock_s):
    mock_s.return_value = _settings()
    # 58-64% move (extended) → not elevated
    assert is_elevated_size_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=73.0,
        move_pct=58.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_elevated_rejects_low_score(mock_s):
    mock_s.return_value = _settings()
    # score 45 (weak) → not elevated
    assert is_elevated_size_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=45.0,
        move_pct=31.0, chart_confidence=95.0,
    ) is False


@patch("app.engines.explosion_confidence.get_settings")
def test_elevated_rejects_wrong_side(mock_s):
    mock_s.return_value = _settings()
    assert is_elevated_size_entry(
        side=Side.CALL, snap=_snap(direction="BEARISH", breadth="BEARISH"),
        tier="EXPLODING", score=73.0, move_pct=48.0, chart_confidence=95.0,
    ) is False


def _size_gate(gate_fn, *, side, snap, tier, score, chart_confidence, move_candidates):
    """Mirror of auto_trader._size_gate: qualify if ANY candidate move is in window."""
    return any(
        gate_fn(
            side=side, snap=snap, tier=tier, score=score,
            move_pct=mv, chart_confidence=chart_confidence,
        )
        for mv in move_candidates
    )


@patch("app.engines.explosion_confidence.get_settings")
def test_base_relative_move_upsizes_fast_rip(mock_s):
    """Fast base rip (SENSEX 76300 PE profile): raw peak move blew past 55% off the
    day low, but the flat→vertical break off the consolidation base is only ~40%.
    Off-the-low move alone disqualifies; base-relative move keeps it high-conviction."""
    mock_s.return_value = _settings()
    off_low_move = 92.0  # ran hard off the day low before ELITE confirmed
    base_relative_move = 40.0  # distance from the flat consolidation base

    # Off-the-low move alone → NOT high conviction (looks like an extended chase)
    assert is_high_conviction_entry(
        side=Side.PUT, snap=_snap(), tier="ELITE", score=100.0,
        move_pct=off_low_move, chart_confidence=95.0,
    ) is False

    # With base-relative move added as a candidate → qualifies for max lots
    assert _size_gate(
        is_high_conviction_entry, side=Side.PUT, snap=_snap(), tier="ELITE",
        score=100.0, chart_confidence=95.0,
        move_candidates=[off_low_move, base_relative_move],
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_base_relative_move_upsizes_exploding_rip(mock_s):
    """Same for the elevated (1.5x) tier: strong EXPLODING rip past 55% off the low
    still earns elevated size when the base-relative break is in the 28-55% window."""
    mock_s.return_value = _settings()
    assert is_elevated_size_entry(
        side=Side.PUT, snap=_snap(), tier="EXPLODING", score=73.0,
        move_pct=88.0, chart_confidence=95.0,
    ) is False
    assert _size_gate(
        is_elevated_size_entry, side=Side.PUT, snap=_snap(), tier="EXPLODING",
        score=73.0, chart_confidence=95.0,
        move_candidates=[88.0, 42.0],
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_base_relative_still_rejects_true_late_chase(mock_s):
    """A genuine late chase (both off-low AND base-relative move are extended) stays
    blocked — base-relative is additive, it never rescues a real chase."""
    mock_s.return_value = _settings()
    assert _size_gate(
        is_high_conviction_entry, side=Side.PUT, snap=_snap(), tier="ELITE",
        score=100.0, chart_confidence=95.0,
        move_candidates=[92.0, 70.0],
    ) is False


def test_trade_is_high_conviction_flag():
    t = MagicMock()
    t.entryContext = {"highConviction": True}
    assert trade_is_high_conviction(t) is True
    t.entryContext = {"highConviction": False}
    assert trade_is_high_conviction(t) is False
    t.entryContext = None
    assert trade_is_high_conviction(t) is False
