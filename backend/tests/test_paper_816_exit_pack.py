"""Paper book keeps the #816 mega exit pack even if env still has the old fade."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_profit import evaluate_explosion_exit
from app.engines.paper_816_exit_pack import (
    paper_816_exit_pack_active,
    settings_for_paper_exit,
)
from app.engines.tp_rung_ladder import tp_rung_exit_reason
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")
_TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "env.production.template"


def _template_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _TEMPLATE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


def _hostile_paper(**extra) -> Settings:
    """Pre-#816 fade: 2pt between-rung clip, ladder off, between-fade never skipped."""
    return Settings(
        enable_live_trading=False,
        paper_trading=True,
        unified_profit_ladder_enabled=False,
        tp_rung_ladder_mega_fade_min_giveback_points=2.0,
        tp_rung_ladder_mega_disable_between_fade_min_best_points=9999.0,
        tp_rung_ladder_mega_ladder_first_min_best_points=9999.0,
        **extra,
    )


def _mega_73200() -> PaperTrade:
    entry = 198.17
    return PaperTrade(
        id="73200-paper",
        symbol="SENSEX",
        side=Side.PUT,
        strike=73200.0,
        entryPremium=entry,
        currentPremium=entry + 50.0,
        lots=22,
        openedAt=datetime.now(IST) - timedelta(minutes=7),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=76.23,
        maxLtp=entry + 76.23,
        maxLtpAt=datetime.now(IST) - timedelta(seconds=120),
        entryContext={
            "maxProfitCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 500.0,
            "stageSize": 75.0,
            "tpRungLadder": True,
            "tpRungsPts": [28.0, 36.0, 75.0, 150.0, 225.0, 300.0, 375.0, 450.0, 500.0],
            "exitPlan": {"projectedMaxTp": 500.0, "stageSize": 75.0},
        },
    )


def test_production_template_arms_paper_816_exit_pack():
    env = _template_env()
    assert env.get("PAPER_816_EXIT_PACK_ENABLED") == "true"
    assert env.get("PAPER_676_ENTRY_CHOKE_ENABLED") == "true"


def test_paper_choke_activates_816_pack_and_restores_thresholds():
    raw = _hostile_paper(paper_676_entry_choke_enabled=True)
    assert paper_816_exit_pack_active(raw) is True
    packed = settings_for_paper_exit(raw)
    assert packed.unified_profit_ladder_enabled is True
    assert packed.tp_rung_ladder_mega_fade_min_giveback_points == 12.0
    assert packed.tp_rung_ladder_mega_disable_between_fade_min_best_points == 55.0
    assert packed.tp_rung_ladder_mega_ladder_first_min_best_points == 55.0
    assert packed.tp_rung_ladder_mega_hot_defer_velocity_3s == 4.0


def test_live_keeps_a_weaker_fade_when_the_paper_pack_is_set():
    live = Settings(
        enable_live_trading=True,
        paper_trading=False,
        paper_676_entry_choke_enabled=True,
        paper_816_exit_pack_enabled=True,
        unified_profit_ladder_enabled=False,
        tp_rung_ladder_mega_fade_min_giveback_points=2.0,
        tp_rung_ladder_mega_disable_between_fade_min_best_points=9999.0,
        tp_rung_ladder_mega_ladder_first_min_best_points=9999.0,
    )
    assert paper_816_exit_pack_active(live) is False
    assert settings_for_paper_exit(live).tp_rung_ladder_mega_fade_min_giveback_points == 2.0


def test_paper_pack_skips_between_rung_fade_on_oct22_mega(monkeypatch):
    settings = _hostile_paper(paper_676_entry_choke_enabled=True)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.engines.explosion_profit.get_settings", lambda: settings)
    monkeypatch.setattr("app.engines.tp_rung_ladder.get_settings", lambda: settings)
    trade = _mega_73200()
    reason = tp_rung_exit_reason(
        trade,
        best=76.23,
        pnl_pts=50.0,
        hold_seconds=400.0,
        live_velocity_3s=-1.5,
        settings=settings,
    )
    assert reason != "explosion_tp_rung_between_fade"


def test_paper_pack_prefers_ladder_over_early_rung_fade(monkeypatch):
    settings = _hostile_paper(paper_676_entry_choke_enabled=True)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.engines.explosion_profit.get_settings", lambda: settings)
    monkeypatch.setattr("app.engines.tp_rung_ladder.get_settings", lambda: settings)
    monkeypatch.setattr("app.engines.moment_stage_trail.get_settings", lambda: settings)
    trade = _mega_73200()
    trade.currentPremium = trade.entryPremium + 54.0
    import app.engines.explosion_profit as ep

    with patch.object(ep, "_hold_seconds", return_value=400):
        reason, pnl_inr = evaluate_explosion_exit(
            trade, trade.currentPremium, "ELITE", 20, live_velocity_3s=-2.0,
        )
    assert trade.entryContext.get("paper816ExitPack") is True
    assert reason != "explosion_tp_rung_between_fade"
    assert pnl_inr > 0
    assert reason in (
        "explosion_profit_ladder_peak_keep",
        "explosion_tp_rung_floor",
        "explosion_tp_rung_floor_hole",
        "explosion_stage_runner_hole_take",
    )
