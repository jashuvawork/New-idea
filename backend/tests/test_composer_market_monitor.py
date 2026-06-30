"""Tests for Composer 2.5 market monitor."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.engines.composer_market_monitor import (
    brief_from_composer_text,
    generate_rule_brief,
    run_monitor_cycle,
)
from app.models.schemas import Breadth, MarketPhase, Regime, SymbolSnapshot
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24000.0,
        optionExpiry="2026-06-30",
        regime=Regime.RANGE_BOUND,
        breadth=Breadth(bias="BEARISH", score=40, aligned=False),
        tradeQualityScore=35.0,
    )


def test_generate_rule_brief_worst_expiry():
    context = {
        "at": "2026-06-30T10:00:00+05:30",
        "dayMode": "EXPIRY WORST",
        "chopSession": True,
        "sessionPaused": False,
        "expiry": {
            "expirySession": True,
            "worstDay": True,
            "worstDayReasons": ["chop_regime", "bearish_sideways"],
            "eveningBlock": False,
            "morningWindow": True,
            "dualScalpMode": True,
            "decliningSession": True,
            "sessionPnlInr": -15000,
        },
        "symbols": {"NIFTY": {"breadth": "BEARISH"}},
        "recentTrades": [],
    }
    brief = generate_rule_brief(context)
    assert brief.standDown is True
    assert brief.tradeBias in ("BOTH", "STAND_ASIDE", "PUT")
    assert len(brief.risks) >= 1


def test_brief_from_composer_json():
    raw = json.dumps({
        "marketRead": "Bearish chop on expiry",
        "tradeBias": "BOTH",
        "confidence": "MEDIUM",
        "sessionPlan": "Morning dual scalp only",
        "risks": ["theta"],
        "actions": ["Wait for score 72+"],
        "standDown": False,
    })
    brief = brief_from_composer_text(raw)
    assert brief.tradeBias == "BOTH"
    assert brief.source == "composer-2.5"
    assert brief.sessionPlan == "Morning dual scalp only"


def test_run_monitor_cycle_rules_only():
    from app.engines.composer_market_monitor import reset_monitor_state

    reset_monitor_state()
    snaps = {"NIFTY": _snap()}
    with patch("app.engines.composer_market_monitor.get_settings") as mock_settings:
        s = MagicMock()
        s.composer_monitor_enabled = True
        s.composer_monitor_use_ai = False
        s.composer_monitor_interval_seconds = 180
        mock_settings.return_value = s
        brief = asyncio.run(run_monitor_cycle(snaps, force=True))
    assert brief.source == "rules"
    assert brief.marketRead


def test_run_monitor_cycle_with_composer_mock():
    from app.engines.composer_market_monitor import reset_monitor_state

    reset_monitor_state()
    snaps = {"NIFTY": _snap()}
    mock_client = MagicMock()
    mock_client.configured = True
    mock_client.chat_completion = AsyncMock(return_value=json.dumps({
        "marketRead": "Sideways expiry",
        "tradeBias": "STAND_ASIDE",
        "confidence": "HIGH",
        "sessionPlan": "No trades until breadth clears",
        "risks": ["whipsaw"],
        "actions": ["Monitor only"],
        "standDown": True,
    }))

    with patch("app.engines.composer_market_monitor.get_settings") as mock_settings:
        s = MagicMock()
        s.composer_monitor_enabled = True
        s.composer_monitor_use_ai = True
        s.composer_monitor_interval_seconds = 180
        s.composer_temperature = 0.2
        s.composer_max_tokens = 1200
        mock_settings.return_value = s
        with patch("app.engines.composer_market_monitor.get_composer_client", return_value=mock_client):
            brief = asyncio.run(run_monitor_cycle(snaps, force=True))
    assert brief.source == "composer-2.5"
    assert brief.standDown is True
