"""Swing profit mode — multi-day hold entry/exit rules."""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.swing_engine import SwingSetup
from app.models.schemas import PaperTrade

IST = ZoneInfo("Asia/Kolkata")


def check_swing_entry(
    setup: SwingSetup,
    existing_swing_ids: set[tuple[str, str]],
    calibration_blocked: bool,
) -> tuple[bool, str]:
    if calibration_blocked:
        return False, "calibration_block"
    if setup.confidence < 68:
        return False, f"confidence_{setup.confidence:.0f}"
    key = (setup.symbol, setup.side.value)
    if key in existing_swing_ids:
        return False, "swing_already_open_symbol_side"
    return True, "passed"


def compute_swing_lots(confidence: float) -> int:
    settings = get_settings()
    if confidence >= 82:
        lots = settings.swing_target_lots
    elif confidence >= 72:
        lots = (settings.swing_min_lots + settings.swing_target_lots) // 2
    else:
        lots = settings.swing_min_lots
    from app.engines.capital_allocator import clamp_lots
    return clamp_lots(lots)


def evaluate_swing_exit(
    trade: PaperTrade,
    current_premium: float,
    lot_multiplier: int = 25,
) -> tuple[Optional[str], float]:
    settings = get_settings()
    entry = trade.entryPremium
    if not entry or entry <= 0:
        return None, 0.0

    pnl_pts = current_premium - entry
    pnl_inr = pnl_pts * trade.lots * lot_multiplier
    pnl_pct = (pnl_pts / entry) * 100
    best_pct = max(
        trade.entryContext.get("bestPnlPct", 0) if trade.entryContext else 0,
        (trade.bestPnlPoints / entry) * 100 if entry else 0,
    )

    opened = trade.openedAt
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=IST)
    hold_days = (datetime.now(IST) - opened.astimezone(IST)).total_seconds() / 86400

    if pnl_inr <= -settings.swing_max_loss_inr:
        return "swing_max_loss_inr", pnl_inr

    if pnl_pct <= -settings.swing_stop_pct:
        return "swing_stop_pct", pnl_inr

    if pnl_pct >= settings.swing_target_pct:
        return "swing_target_pct", pnl_inr

    if best_pct >= settings.swing_trail_arm_pct and pnl_pct < best_pct * settings.swing_trail_keep:
        return "swing_trail_lock", pnl_inr

    if hold_days >= settings.swing_max_hold_days:
        return "swing_time_exit_profit" if pnl_inr > 0 else "swing_time_exit", pnl_inr

    if hold_days >= 2 and pnl_pct <= -5:
        return "swing_theta_bleed", pnl_inr

    return None, pnl_inr
