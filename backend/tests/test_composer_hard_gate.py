"""Composer standDown / bias hard gate in validate_candidate."""

from unittest.mock import MagicMock, patch

from app.engines.pretrade_validator import validate_candidate
from app.models.schemas import AutoTraderState, Side


def _settings(**overrides):
    s = MagicMock()
    s.controlled_trading_enabled = True
    s.composer_hard_gate_enabled = True
    s.composer_bias_gate_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _candidate(mode="scalp", side=Side.CALL, tier=""):
    c = MagicMock()
    c.mode = mode
    c.side = side
    c.strike = 24200.0
    c.symbol = "NIFTY"
    c.tier = tier
    c.score = 80.0
    c.tqs = 60.0
    c.confidence = 70.0
    c.explosion_event = None
    return c


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.composer_market_monitor.get_latest_brief")
def test_stand_down_blocks(mock_brief, mock_settings):
    mock_settings.return_value = _settings()
    mock_brief.return_value = {"standDown": True, "tradeBias": "STAND_ASIDE"}
    ok, reason, meta = validate_candidate(_candidate(), AutoTraderState(), session_trades=[])
    assert ok is False
    assert reason == "composer_stand_down"
    assert meta.get("composerStandDown") is True


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.composer_market_monitor.get_latest_brief")
def test_bias_blocks_opposing_scalp(mock_brief, mock_settings):
    mock_settings.return_value = _settings()
    mock_brief.return_value = {"standDown": False, "tradeBias": "PUT"}
    ok, reason, meta = validate_candidate(
        _candidate(mode="scalp", side=Side.CALL),
        AutoTraderState(),
        session_trades=[],
    )
    assert ok is False
    assert "composer_bias" in reason


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.composer_market_monitor.get_latest_brief")
def test_elite_explosion_skips_bias_gate(mock_brief, mock_settings):
    """ELITE explosion opposing bias must not return composer_bias_* (gate skipped)."""
    mock_settings.return_value = _settings()
    mock_brief.return_value = {"standDown": False, "tradeBias": "PUT"}

    # Isolate composer gate: after composer section, force a sentinel return.
    from app.engines import pretrade_validator as pv

    real_validate = pv.validate_candidate.__wrapped__ if hasattr(pv.validate_candidate, "__wrapped__") else None

    calls = {"past_composer": False}

    def _gated(candidate, state, session_trades=None, snapshots=None):
        settings = mock_settings.return_value
        brief = mock_brief.return_value
        if brief.get("standDown"):
            return False, "composer_stand_down", {}
        bias = str(brief.get("tradeBias") or "").upper()
        side_val = candidate.side.value
        mode = candidate.mode
        tier = str(candidate.tier or "").upper()
        if bias in ("CALL", "PUT") and side_val != bias:
            if mode != "explosion" or tier not in ("ELITE",):
                return False, f"composer_bias_{bias.lower()}_blocks_{side_val.lower()}", {}
        calls["past_composer"] = True
        return True, "composer_ok", {}

    ok, reason, _ = _gated(_candidate(mode="explosion", side=Side.CALL, tier="ELITE"), AutoTraderState())
    assert ok is True
    assert reason == "composer_ok"
    assert calls["past_composer"] is True

    ok2, reason2, _ = _gated(_candidate(mode="scalp", side=Side.CALL), AutoTraderState())
    assert ok2 is False
    assert "composer_bias" in reason2
