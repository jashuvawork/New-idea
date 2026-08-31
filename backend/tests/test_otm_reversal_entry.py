"""OTM reversal entry — allow a slightly-deeper OTM CALL/PUT only on a CONFIRMED index turn.

Aug31: the +105% NIFTY 24150 CE was 2-3 strikes OTM and rejected as
armed_base_requires_atm_itm_otm, then spot rallied through it. This lane fixes exactly that,
but only when the index is confirmed reversing toward the side (not a lottery guess).
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.early_radar_pad_capture import otm_reversal_entry_allowed


def _settings(**over):
    s = SimpleNamespace(
        otm_reversal_entry_enabled=True,
        otm_reversal_max_steps=2,
        nifty_strike_step=50,
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s


def _snap(symbol="NIFTY", spot=24040.0, atm=24050.0):
    return SimpleNamespace(symbol=symbol, spot=spot, atmStrike=atm)


# NIFTY 24150 CE with spot ~24040 => 2 steps OTM (50-step).
def _alert(side="CALL", strike=24150.0):
    return {"side": side, "strike": strike}


def test_disabled_by_default():
    with patch("app.engines.early_radar_pad_capture.get_settings",
               return_value=_settings(otm_reversal_entry_enabled=False)):
        assert otm_reversal_entry_allowed(_alert(), _snap()) is False


def test_allows_shallow_otm_when_side_regime_confirms():
    with (
        patch("app.engines.early_radar_pad_capture.get_settings", return_value=_settings()),
        patch("app.engines.side_regime.session_trade_side", lambda s: "CALL"),
    ):
        assert otm_reversal_entry_allowed(_alert("CALL"), _snap()) is True


def test_blocks_when_no_index_confirmation():
    with (
        patch("app.engines.early_radar_pad_capture.get_settings", return_value=_settings()),
        patch("app.engines.side_regime.session_trade_side", lambda s: "NEUTRAL"),
        patch("app.engines.index_tick_helpers.recent_index_drift", lambda *a, **k: {"drift": False}),
        patch("app.engines.index_tick_helpers.index_trend_breakout", lambda *a, **k: {"breakout": False}),
    ):
        assert otm_reversal_entry_allowed(_alert("CALL"), _snap()) is False


def test_allows_when_index_drift_confirms():
    with (
        patch("app.engines.early_radar_pad_capture.get_settings", return_value=_settings()),
        patch("app.engines.side_regime.session_trade_side", lambda s: "NEUTRAL"),
        patch("app.engines.index_tick_helpers.recent_index_drift",
              lambda sym, side, *a, **k: {"drift": side == "CALL"}),
        patch("app.engines.index_tick_helpers.index_trend_breakout", lambda *a, **k: {"breakout": False}),
    ):
        assert otm_reversal_entry_allowed(_alert("CALL"), _snap()) is True


def test_blocks_too_deep_otm_even_with_confirmation():
    # 24400 CE with spot ~24040 => ~7 steps OTM > max_steps(2).
    with (
        patch("app.engines.early_radar_pad_capture.get_settings", return_value=_settings()),
        patch("app.engines.side_regime.session_trade_side", lambda s: "CALL"),
    ):
        assert otm_reversal_entry_allowed(_alert("CALL", strike=24400.0), _snap()) is False


def test_atm_itm_passthrough_true():
    # ITM CALL (strike below spot) → not OTM → always allowed.
    with patch("app.engines.early_radar_pad_capture.get_settings", return_value=_settings()):
        assert otm_reversal_entry_allowed(_alert("CALL", strike=23900.0), _snap()) is True
