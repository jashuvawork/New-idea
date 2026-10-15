"""Oct 1 / Oct 5 paper replica — radar, selection, entry as those sessions; exits stay current."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.explosion_entry_guards import _near_strike_armed_alert_active
from app.engines.live_oct1_pad_entry_guard import oct1_pad_entry_guard_active
from app.engines.live_paper_parity import (
    live_paper_profile_summary,
    oct_paper_entry_loosening_active,
    oct_paper_peak_keep_exit_parity_active,
    oct_paper_replica_active,
    oct_paper_skip_live_only_session_gates,
    oct_paper_structural_entry_waivers_active,
    oct_paper_structural_pad_context,
    trading_rules_match_paper,
)
from app.engines.moneyness import atm_itm_entry_allows
from app.engines.october_frozen_profile import (
    october_frozen_profile_ok,
    october_frozen_profile_summary,
)
from app.engines.rally_capture import (
    armed_base_pad_near_miss_waive,
    near_strike_armed_near_miss_waive,
)
from app.engines.sep917_legacy_profile import (
    atm_itm_fixed_premium_band_only,
    near_strike_waiver_excluded_moneyness,
    strict_atm_itm_execution,
)
from app.models.schemas import MarketPhase, Side, SymbolSnapshot

_OVERLAY = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"


def _overlay_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _OVERLAY.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


def _frozen(**overrides) -> Settings:
    base = {
        "october_frozen_profile_enabled": True,
        "live_paper_parity_enabled": True,
        "live_trade_selection_parity_with_paper": True,
        "live_best_trades_only_enabled": False,
        "worst_day_blocks_live": False,
        "enable_live_trading": False,
    }
    base.update(overrides)
    return Settings(**base)


def _replica(**overrides) -> Settings:
    return _frozen(
        oct_paper_replica_enabled=True,
        live_paper_parity_pad_entry_guard_enabled=False,
        **overrides,
    )


@pytest.fixture
def use_settings(monkeypatch):
    def _apply(settings: Settings) -> Settings:
        getter = lambda: settings  # noqa: E731
        monkeypatch.setattr("app.config.get_settings", getter)
        for mod in (
            "app.engines.moneyness",
            "app.engines.explosion_entry_guards",
            "app.engines.rally_capture",
            "app.engines.whipsaw_guards",
            "app.engines.early_radar_pad_capture",
        ):
            monkeypatch.setattr(f"{mod}.get_settings", getter, raising=False)
        return settings

    return _apply


def _snap(symbol: str = "NIFTY", spot: float = 22850.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime(2026, 10, 12, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=spot,
    )


def _armed(side: str, moneyness: str, steps: float) -> dict:
    return {
        "side": side,
        "tier": "ELITE",
        "explosionScore": 95.0,
        "moneyness": moneyness,
        "strikeStepsFromAtm": steps,
        "armedBaseLaunch": True,
        "momentType": "armed_base_launch",
    }


# --- Switch -----------------------------------------------------------------


def test_replica_off_by_default_in_code():
    s = Settings()
    assert s.oct_paper_replica_enabled is False
    assert oct_paper_replica_active(s) is False


def test_post_oct5_loosening_on_without_replica_off_with_replica():
    assert oct_paper_entry_loosening_active(_frozen()) is True
    replica = _replica()
    assert trading_rules_match_paper(replica) is True
    assert oct_paper_entry_loosening_active(replica) is False
    assert oct_paper_structural_entry_waivers_active(replica) is True
    assert oct_paper_skip_live_only_session_gates(replica) is True


def test_replica_also_disables_loosening_on_live_parity():
    live = _replica(enable_live_trading=True, auto_trading_enabled=True)
    assert trading_rules_match_paper(live) is True
    assert oct_paper_entry_loosening_active(live) is False


# --- Radar ------------------------------------------------------------------


def test_radar_scan_band_restored_to_oct5_under_replica():
    assert atm_itm_fixed_premium_band_only(_frozen()) is True
    assert atm_itm_fixed_premium_band_only(_replica()) is False


# --- Selection: strict ATM/ITM-only (#692) off ------------------------------


def test_strict_atm_itm_execution_off_under_replica():
    assert strict_atm_itm_execution(_frozen()) is True
    assert strict_atm_itm_execution(_replica()) is False


@pytest.mark.parametrize("side,strike", [(Side.CALL, 23000.0), (Side.PUT, 22700.0)])
def test_otm_not_hard_blocked_by_strict_rule_under_replica_ce_pe(use_settings, side, strike):
    use_settings(_replica())
    allowed, reason, meta = atm_itm_entry_allows(
        side, strike, _snap(), alert={"buildingCoilPad": True},
    )
    assert meta.get("moneyness") == "OTM"
    assert reason != "moneyness_atm_itm_only"


@pytest.mark.parametrize("side,strike", [(Side.CALL, 23000.0), (Side.PUT, 22700.0)])
def test_otm_hard_blocked_without_replica_ce_pe(use_settings, side, strike):
    use_settings(_frozen())
    allowed, reason, _ = atm_itm_entry_allows(
        side, strike, _snap(), alert={"buildingCoilPad": True},
    )
    assert allowed is False
    assert reason == "moneyness_atm_itm_only"


# --- Selection: near-strike waivers (#692 inversion) -------------------------


def test_near_strike_excluded_moneyness_flips_under_replica():
    assert near_strike_waiver_excluded_moneyness(_frozen()) == "OTM"
    assert near_strike_waiver_excluded_moneyness(_replica()) == "ITM"


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_near_strike_armed_alert_oct5_semantics_ce_pe(use_settings, side):
    use_settings(_replica())
    assert _near_strike_armed_alert_active(_armed(side, "OTM", 1), max_steps=2) is True
    assert _near_strike_armed_alert_active(_armed(side, "ITM", 1), max_steps=2) is False
    assert _near_strike_armed_alert_active(_armed(side, "ATM", 0), max_steps=2) is False


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_near_strike_armed_alert_current_semantics_ce_pe(use_settings, side):
    use_settings(_frozen())
    assert _near_strike_armed_alert_active(_armed(side, "OTM", 1), max_steps=2) is False
    assert _near_strike_armed_alert_active(_armed(side, "ITM", 1), max_steps=2) is True
    assert _near_strike_armed_alert_active(_armed(side, "ATM", 0), max_steps=2) is True


def _pad_alert(side: str, moneyness: str, steps: float) -> dict:
    return {
        **_armed(side, moneyness, steps),
        "localBaseMovePct": 5.0,
        "orderflowPositive": True,
        "volumeSurge": 2.0,
        "ictVolumeAwakening": True,
        "causalGrade": "S",
    }


@pytest.mark.parametrize("side", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "moneyness,steps,replica_ok,current_ok",
    [("OTM", 1, True, False), ("ITM", 1, False, True)],
)
def test_near_strike_armed_near_miss_oct5_vs_current_ce_pe(
    use_settings, side, moneyness, steps, replica_ok, current_ok,
):
    alert = _pad_alert(side, moneyness, steps)
    use_settings(_replica())
    assert near_strike_armed_near_miss_waive(alert, settings=_replica()) is replica_ok
    use_settings(_frozen())
    assert near_strike_armed_near_miss_waive(alert, settings=_frozen()) is current_ok


@pytest.mark.parametrize("side", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "moneyness,steps,replica_ok,current_ok",
    [("OTM", 1, True, False), ("ITM", 1, True, True), ("ITM", 5, False, True)],
)
def test_armed_base_pad_near_miss_oct5_vs_current_ce_pe(
    use_settings, side, moneyness, steps, replica_ok, current_ok,
):
    alert = _pad_alert(side, moneyness, steps)
    use_settings(_replica())
    assert armed_base_pad_near_miss_waive(alert, settings=_replica()) is replica_ok
    use_settings(_frozen())
    assert armed_base_pad_near_miss_waive(alert, settings=_frozen()) is current_ok


# --- Entry: pad guard and post-Oct 5 waivers off ----------------------------


def test_pad_guard_off_under_replica_on_with_guard():
    assert oct1_pad_entry_guard_active(_frozen()) is True
    assert oct1_pad_entry_guard_active(_replica()) is False


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_structural_pad_waivers_on_under_replica_ce_pe(side):
    evidence = {
        **_armed(side, "ATM", 0),
        "firstLift": True,
        "localBaseMovePct": 4.0,
        "offLowMovePct": 8.0,
        "sessionRangePosition": 0.3,
        "explosionScore": 95.0,
    }
    assert oct_paper_structural_pad_context(evidence, settings=_replica()) is True


def test_power_hour_gate_skipped_under_replica(use_settings):
    from app.engines import power_hour_guards

    use_settings(_replica())
    _ok, _reason, meta = power_hour_guards.check_power_hour_session_allowed(None, {})
    assert meta.get("octPaperPowerHourSkipped") is True


def test_power_hour_gate_skipped_without_replica(use_settings):
    from app.engines import power_hour_guards

    use_settings(_frozen())
    _ok, _reason, meta = power_hour_guards.check_power_hour_session_allowed(None, {})
    assert meta.get("octPaperPowerHourSkipped") is True


def test_whipsaw_pause_skipped_under_replica(use_settings):
    from app.engines import whipsaw_guards

    use_settings(_replica(whipsaw_guards_enabled=True))
    _paused, reason, _ = whipsaw_guards.check_session_whipsaw_pause(None, {})
    assert reason == "oct_paper_whipsaw_skipped"


def test_whipsaw_pause_skipped_without_replica(use_settings):
    from app.engines import whipsaw_guards

    use_settings(_frozen(whipsaw_guards_enabled=True))
    _paused, reason, _ = whipsaw_guards.check_session_whipsaw_pause(None, {})
    assert reason == "oct_paper_whipsaw_skipped"


# --- Exits stay current -----------------------------------------------------


def test_peak_keep_exit_parity_kept_under_replica():
    assert oct_paper_peak_keep_exit_parity_active(_replica()) is True


def test_exit_flags_unchanged_by_replica():
    s = _replica()
    assert s.adaptive_exits_enabled is True
    assert s.explosion_multiple_fast_fade_enabled is True
    assert s.executed_entry_sl_only_loss_exits is True


# --- Overlay + HUD sign-off -------------------------------------------------


def test_frozen_overlay_enables_oct_paper_replica():
    env = _overlay_env()
    assert env["OCT_PAPER_REPLICA_ENABLED"] == "true"
    assert env["LIVE_PAPER_PARITY_PAD_ENTRY_GUARD_ENABLED"] == "false"
    assert env["OTM_REVERSAL_ENTRY_ENABLED"] == "true"
    assert env["EXPIRY_WORST_DAY_HALT_ENTRIES"] == "true"
    assert (env["ENTRY_EARLIEST_HOUR"], env["ENTRY_EARLIEST_MINUTE"]) == ("9", "16")
    assert env.get("OPEN_SIDE_CONFIRMATION_MIN_MINUTES") == "1"
    assert env["ADAPTIVE_EXITS_ENABLED"] == "true"
    assert env["EXPLOSION_MULTIPLE_FAST_FADE_ENABLED"] == "true"
    assert env["PE_WIN_CE_MIRROR_ENABLED"] == "true"


def test_frozen_profile_ok_with_replica_and_pad_guard_off():
    ok, issues = october_frozen_profile_ok(_replica())
    assert "pad_entry_guard_disabled" not in issues
    assert october_frozen_profile_summary(_replica())["octPaperReplicaEnabled"] is True


def test_frozen_profile_flags_pad_guard_off_without_replica():
    _ok, issues = october_frozen_profile_ok(
        _frozen(live_paper_parity_pad_entry_guard_enabled=False)
    )
    assert "pad_entry_guard_disabled" in issues


def test_hud_summary_exposes_replica_state():
    summary = live_paper_profile_summary(_replica())
    rep = summary["octPaperReplica"]
    assert rep["enabled"] is True
    assert rep["postOct5EntryLooseningActive"] is False
    assert rep["skipLiveOnlySessionGates"] is True
    assert rep["radarFixedPremiumBandOnly"] is False
    assert rep["strictAtmItmExecution"] is False
    assert rep["padEntryGuardEnabled"] is False
    assert summary["octPaperBehaviorParity"]["peakKeepExitParity"] is True
    assert summary["octPaperBehaviorParity"]["structuralPadSelectorWaivers"] is True
    assert rep["structuralEntryWaiversActive"] is True
