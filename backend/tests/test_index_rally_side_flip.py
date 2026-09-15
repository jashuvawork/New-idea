"""Index trend side-flip bypass — unlock opposite side on index move + RSI/MACD."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.directional_lock import (
    check_directional_side_lock,
    record_trade_side,
    reset_directional_lock,
)
from app.engines.index_rally_side_flip import index_rally_side_flip_bypass
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides) -> Settings:
    base = dict(
        index_rally_side_flip_enabled=True,
        index_rally_side_flip_min_pts=130.0,
        index_rally_side_flip_min_rsi=50.0,
        index_rally_side_flip_max_rsi=50.0,
        index_rally_side_flip_require_macd_bullish=True,
        index_rally_side_flip_require_macd_bearish=True,
        index_rally_side_flip_min_mom5_pct=0.05,
        directional_side_lock_enabled=True,
        directional_switch_min_confirmations=5,
        breadth_hard_side_block_enabled=False,
    )
    base.update(overrides)
    return Settings(**base)


def _snap(
    *,
    spot: float = 76510.0,
    breadth: str = "BEARISH",
    chart_dir: str = "BEARISH",
    rsi: float = 58.0,
    macd_bias: str = "BULLISH",
    mom5: float = 0.12,
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=76500.0,
        breadth=Breadth(bias=breadth),
        spotChart=SpotChart(
            direction=chart_dir,
            spot=spot,
            rsi=rsi,
            macdBias=macd_bias,
            macdHistogram=2.5 if macd_bias == "BULLISH" else -2.5,
            momentum5Pct=mom5,
            momentum15Pct=0.08 if mom5 >= 0 else -0.08,
        ),
    )


@patch("app.engines.index_rally_side_flip.get_settings")
def test_rally_bypass_fires_on_sensex_130pt_rip(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap()
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76513.0),
    ):
        ok, reason, meta = index_rally_side_flip_bypass("SENSEX", Side.CALL, snap)
    assert ok is True
    assert reason == "index_rally_side_flip"
    assert meta["rallyPoints"] == pytest.approx(133.0, abs=0.5)


@patch("app.engines.index_rally_side_flip.get_settings")
def test_slide_bypass_fires_on_sensex_130pt_drop(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(
        spot=76270.0,
        breadth="BULLISH",
        chart_dir="BULLISH",
        rsi=42.0,
        macd_bias="BEARISH",
        mom5=-0.12,
    )
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76400.0, 76200.0, 76270.0),
    ):
        ok, reason, meta = index_rally_side_flip_bypass("SENSEX", Side.PUT, snap)
    assert ok is True
    assert reason == "index_slide_side_flip"
    assert meta["slidePoints"] == pytest.approx(130.0, abs=0.5)


@patch("app.engines.index_rally_side_flip.get_settings")
def test_rally_bypass_rejects_small_rally(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap()
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76500.0, 76450.0, 76510.0),
    ):
        ok, reason, _ = index_rally_side_flip_bypass("SENSEX", Side.CALL, snap)
    assert ok is False
    assert "rally_" in reason


@patch("app.engines.index_rally_side_flip.get_settings")
def test_rally_bypass_neutral_macd_passes_with_positive_mom5(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(macd_bias="NEUTRAL", mom5=0.44)
    snap.spotChart.macdHistogram = 0.0
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76135.0, 76512.0),
    ):
        ok, reason, meta = index_rally_side_flip_bypass("SENSEX", Side.CALL, snap)
    assert ok is True
    assert reason == "index_rally_side_flip"
    assert meta["macdBias"] == "NEUTRAL"


@patch("app.engines.index_rally_side_flip.get_settings")
def test_slide_bypass_neutral_macd_passes_with_negative_mom5(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(
        spot=76270.0,
        breadth="BULLISH",
        chart_dir="BULLISH",
        rsi=42.0,
        macd_bias="NEUTRAL",
        mom5=-0.12,
    )
    snap.spotChart.macdHistogram = 0.0
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76400.0, 76200.0, 76270.0),
    ):
        ok, reason, meta = index_rally_side_flip_bypass("SENSEX", Side.PUT, snap)
    assert ok is True
    assert reason == "index_slide_side_flip"
    assert meta["macdBias"] == "NEUTRAL"


@patch("app.engines.index_rally_side_flip.get_settings")
def test_rally_bypass_requires_bullish_macd(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(macd_bias="BEARISH", rsi=55.0)
    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76520.0),
    ):
        ok, reason, _ = index_rally_side_flip_bypass("SENSEX", Side.CALL, snap)
    assert ok is False
    assert reason.startswith("macd_")


@patch("app.engines.directional_lock.get_settings")
@patch("app.engines.index_rally_side_flip.get_settings")
@patch("app.engines.aligned_side_guard.get_settings")
def test_directional_lock_yields_to_rally_bypass(
    mock_guard_settings, mock_rally_settings, mock_lock_settings,
):
    settings = _settings()
    mock_guard_settings.return_value = settings
    mock_rally_settings.return_value = settings
    mock_lock_settings.return_value = settings

    reset_directional_lock()
    snap = _snap(breadth="BEARISH", chart_dir="BEARISH")
    record_trade_side("SENSEX", Side.PUT, snap)

    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76520.0),
    ):
        blocked, reason = check_directional_side_lock("SENSEX", Side.CALL, snap)

    assert blocked is False
    assert reason == "ok"


@patch("app.engines.directional_lock.get_settings")
@patch("app.engines.index_rally_side_flip.get_settings")
@patch("app.engines.aligned_side_guard.get_settings")
def test_directional_lock_yields_to_slide_bypass(
    mock_guard_settings, mock_rally_settings, mock_lock_settings,
):
    settings = _settings()
    mock_guard_settings.return_value = settings
    mock_rally_settings.return_value = settings
    mock_lock_settings.return_value = settings

    reset_directional_lock()
    snap = _snap(
        spot=76270.0,
        breadth="BULLISH",
        chart_dir="BULLISH",
        rsi=42.0,
        macd_bias="BEARISH",
        mom5=-0.12,
    )
    record_trade_side("SENSEX", Side.CALL, snap)

    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76400.0, 76200.0, 76270.0),
    ):
        blocked, reason = check_directional_side_lock("SENSEX", Side.PUT, snap)

    assert blocked is False
    assert reason == "ok"


@patch("app.engines.directional_lock.get_settings")
@patch("app.engines.index_rally_side_flip.get_settings")
@patch("app.engines.aligned_side_guard.get_settings")
def test_directional_lock_still_blocks_put_to_call_without_rally(
    mock_guard_settings, mock_rally_settings, mock_lock_settings,
):
    settings = _settings()
    mock_guard_settings.return_value = settings
    mock_rally_settings.return_value = settings
    mock_lock_settings.return_value = settings

    reset_directional_lock()
    snap = _snap(breadth="BEARISH", chart_dir="BEARISH", mom5=0.02, rsi=45.0)
    record_trade_side("SENSEX", Side.PUT, snap)

    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76500.0, 76480.0, 76500.0),
    ):
        blocked, reason = check_directional_side_lock("SENSEX", Side.CALL, snap)

    assert blocked is True
    assert "directional_switch_blocked_PUT_to_CALL" in reason


@patch("app.engines.aligned_side_guard.get_settings")
@patch("app.engines.index_rally_side_flip.get_settings")
def test_breadth_hard_block_yields_to_rally_bypass(mock_rally_settings, mock_guard_settings):
    from app.engines.aligned_side_guard import breadth_hard_blocks_side

    settings = _settings()
    mock_rally_settings.return_value = settings
    mock_guard_settings.return_value = settings
    snap = _snap(breadth="BEARISH")

    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(77600.0, 76380.0, 76520.0),
    ):
        blocked, reason = breadth_hard_blocks_side(
            Side.CALL, "BEARISH", snap=snap,
        )

    assert blocked is False
    assert reason == "ok"


@patch("app.engines.aligned_side_guard.get_settings")
@patch("app.engines.index_rally_side_flip.get_settings")
def test_breadth_hard_block_yields_to_slide_bypass(mock_rally_settings, mock_guard_settings):
    from app.engines.aligned_side_guard import breadth_hard_blocks_side

    settings = _settings()
    mock_rally_settings.return_value = settings
    mock_guard_settings.return_value = settings
    snap = _snap(
        spot=76270.0,
        breadth="BULLISH",
        chart_dir="BULLISH",
        rsi=42.0,
        macd_bias="BEARISH",
        mom5=-0.12,
    )

    with patch(
        "app.engines.index_rally_side_flip._session_extremes_and_spot",
        return_value=(76400.0, 76200.0, 76270.0),
    ):
        blocked, reason = breadth_hard_blocks_side(
            Side.PUT, "BULLISH", snap=snap,
        )

    assert blocked is False
    assert reason == "ok"
