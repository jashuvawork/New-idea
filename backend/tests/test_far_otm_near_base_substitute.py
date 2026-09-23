"""Far OTM strike chase when nearer leg is at structural base (Sep23 75100 vs 74800)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_entry_guards import far_otm_near_base_substitute_blocked
from app.models.schemas import MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(alerts: list[dict]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=74500.0,
        atmStrike=74800.0,
        dataAvailable=True,
        explosionAlerts=alerts,
    )


def test_blocks_far_otm_when_near_strike_has_armed_base():
    s = Settings(explosion_far_otm_near_base_substitute_enabled=True)
    near = {
        "side": "CALL",
        "strike": 74800.0,
        "tier": "ELITE",
        "score": 200.0,
        "strikeStepsFromAtm": 1,
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 10.0,
    }
    snap = _snap([near])
    blocked, reason = far_otm_near_base_substitute_blocked(
        Side.CALL,
        75100.0,
        snap,
        settings=s,
        alert={
            "side": "CALL",
            "strike": 75100.0,
            "tier": "ELITE",
            "score": 210.0,
            "strikeStepsFromAtm": 4,
        },
    )
    assert blocked is True
    assert reason == "explosion_far_otm_near_base_substitute"


def test_allows_near_otm_at_base():
    s = Settings(explosion_far_otm_near_base_substitute_enabled=True)
    snap = _snap([])
    blocked, _ = far_otm_near_base_substitute_blocked(
        Side.CALL,
        74800.0,
        snap,
        settings=s,
        alert={"strikeStepsFromAtm": 1},
    )
    assert blocked is False
