"""Paper #794 / #816 deploy contract — template pins, no 09:16 overlay."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "deploy/env.production.template"


def _template_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in TEMPLATE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_production_template_paper_794_816_entry_and_exits():
    env = _template_env()
    assert env.get("PAPER_TRADING") == "true"
    assert env.get("ENABLE_LIVE_TRADING") == "false"
    assert env.get("ENTRY_EARLIEST_HOUR") == "9"
    assert env.get("ENTRY_EARLIEST_MINUTE") == "20"
    assert env.get("EXPLOSION_ENTRY_EARLIEST_MINUTE") == "20"
    assert env.get("UNIFIED_PROFIT_LADDER_ENABLED") == "true"
    assert env.get("UNIFIED_PROFIT_LADDER_BREAKEVEN_ENABLED") == "false"
    assert env.get("TP_RUNG_LADDER_EXIT_ENABLED") == "true"
    assert env.get("TP_RUNG_LADDER_MEGA_LADDER_FIRST_MIN_BEST_POINTS") == "55"
    assert env.get("CALL_ATM_ITM_BASE_CAPTURE_ENABLED") == "true"


def test_redeploy_and_verify_scripts_exist():
    assert (ROOT / "deploy/redeploy-paper-794-816-session.sh").is_file()
    assert (ROOT / "deploy/verify-paper-794-816-session.sh").is_file()
