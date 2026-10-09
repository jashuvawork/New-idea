"""Frozen October overlay pins Oct 1 / Oct 5 session env (deploy sign-off)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy" / "env.october-frozen.overlay"

REQUIRED_KEYS = {
    "OCTOBER_FROZEN_PROFILE_ENABLED": "true",
    "SYMMETRIC_BEST_TRADE_CAPTURE_ENABLED": "true",
    "INDEX_RALLY_SIDE_FLIP_ENABLED": "true",
    "LIVE_PAPER_PARITY_ENABLED": "true",
    "LIVE_BEST_TRADES_ONLY_ENABLED": "false",
    "WORST_DAY_BLOCKS_LIVE": "false",
    "POWER_HOUR_END_MINUTE": "35",
    "DAILY_PROFIT_STAGE_BLOCK_ENTRIES_MIN_STAGE": "3",
    "SAME_STRIKE_POST_WIN_V_RIP_REENTRY_WAIVE_ENABLED": "true",
    "PE_WIN_CE_MIRROR_BLOCK_PUT_CHASE_ENABLED": "true",
}


def _parse_overlay() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in OVERLAY.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def test_frozen_overlay_contains_oct_ce_pe_session_keys():
    assert OVERLAY.is_file(), "deploy/env.october-frozen.overlay missing"
    env = _parse_overlay()
    missing = [k for k in REQUIRED_KEYS if k not in env]
    assert not missing, f"missing keys in frozen overlay: {missing}"
    bad = [k for k, want in REQUIRED_KEYS.items() if env.get(k) != want]
    assert not bad, f"wrong values in frozen overlay: {[(k, env.get(k), REQUIRED_KEYS[k]) for k in bad]}"
