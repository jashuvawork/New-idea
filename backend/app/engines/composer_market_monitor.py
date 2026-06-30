"""Composer 2.5 market monitor — session understanding + trading advisory."""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.engines.chop_day_guards import chop_guard_summary
from app.engines.expiry_day_guards import expiry_guard_summary, is_expiry_session
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services.cursor_composer_client import ComposerClientError, get_composer_client
from app.services.upstox import get_market_phase

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

SYSTEM_PROMPT = """You are NexusQuant's intraday Indian index options trading copilot.
Your job is to UNDERSTAND the market context and advise the human trader — not to fire orders.

Rules:
- Be concise and actionable (max 12 lines in summary).
- Respect expiry-day playbooks: fewer trades, morning focus, dual CE/PE only when chop demands hedging.
- If session is declining or worst-day predicted, recommend STAND_ASIDE or very selective scalps.
- Hold high-confidence and psychology (FEAR/CAUTION) setups longer; avoid churn.
- Output valid JSON only, no markdown fences.

JSON schema:
{
  "marketRead": "1-2 sentence regime read",
  "tradeBias": "CALL|PUT|BOTH|STAND_ASIDE",
  "confidence": "HIGH|MEDIUM|LOW",
  "sessionPlan": "what to do this hour",
  "risks": ["risk1", "risk2"],
  "actions": ["action1", "action2"],
  "standDown": false
}
"""


@dataclass
class ComposerBrief:
    at: str
    source: str
    marketRead: str = ""
    tradeBias: str = "STAND_ASIDE"
    confidence: str = "LOW"
    sessionPlan: str = ""
    risks: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    standDown: bool = False
    raw: str = ""
    contextHash: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_brief_history: deque[ComposerBrief] = deque(maxlen=48)
_last_brief: Optional[ComposerBrief] = None
_last_run_mono: float = 0.0
_last_trade_ids: set[str] = set()


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def build_market_context(
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> dict[str, Any]:
    """Structured facts for Composer — regime, guards, recent trades."""
    state = state or get_state()
    chop = chop_guard_summary(state, snapshots)
    expiry = expiry_guard_summary(state, snapshots)

    symbols_ctx: dict[str, Any] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        chart = snap.spotChart
        symbols_ctx[sym] = {
            "spot": snap.spot,
            "regime": str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime),
            "breadth": snap.breadth.bias,
            "breadthScore": snap.breadth.score,
            "tqs": snap.tradeQualityScore,
            "optionExpiry": snap.optionExpiry,
            "psychology": (snap.psychology or {}).get("label"),
            "chartDirection": chart.direction if chart else None,
            "momentum5Pct": chart.momentum5Pct if chart else None,
            "pcr": snap.pcr,
        }

    recent_trades = []
    for t in (state.closedPaperTrades or [])[-8:]:
        ctx = t.entryContext or {}
        recent_trades.append({
            "symbol": t.symbol,
            "side": t.side.value if hasattr(t.side, "value") else str(t.side),
            "strike": t.strike,
            "pnlInr": t.pnlInr,
            "exitReason": t.exitReason,
            "score": ctx.get("selectionScore") or ctx.get("tqs"),
            "moneyness": ctx.get("moneyness"),
            "psychology": ctx.get("psychology"),
        })

    skipped = state.skipped or []
    return {
        "at": _now_iso(),
        "marketPhase": get_market_phase(),
        "dayMode": chop.get("dayMode"),
        "dayModeHint": chop.get("dayModeHint"),
        "chopSession": chop.get("chopSession"),
        "sessionPaused": chop.get("sessionPaused"),
        "tradeCap": {
            "closed": chop.get("closedTrades"),
            "cap": chop.get("dailyTradeCap"),
            "label": chop.get("dailyTradeCapLabel"),
        },
        "expiry": expiry,
        "whipsaw": chop.get("whipsawGuards"),
        "lastNTrades": chop.get("lastNTrades"),
        "symbols": symbols_ctx,
        "openTrades": len(state.openPaperTrades or []),
        "recentTrades": recent_trades,
        "skippedNow": skipped[:6],
        "dailyProfitGate": state.dailyProfitGate,
    }


def generate_rule_brief(context: dict[str, Any]) -> ComposerBrief:
    """Deterministic brief when Composer API unavailable."""
    expiry = context.get("expiry") or {}
    day_mode = str(context.get("dayMode") or "NORMAL")
    risks: list[str] = []
    actions: list[str] = []
    stand_down = False
    bias = "STAND_ASIDE"
    confidence = "LOW"

    if context.get("sessionPaused"):
        stand_down = True
        risks.append("loss_streak_pause_active")
        actions.append("No new entries until pause clears")

    if expiry.get("eveningBlock"):
        stand_down = True
        risks.append("expiry_evening_theta_gamma")
        actions.append("Avoid new entries after 14:00 on expiry")

    if expiry.get("worstDay"):
        risks.extend(expiry.get("worstDayReasons") or ["worst_expiry_day"])
        actions.append("Max 3 trades; morning only; ITM scalps if any")
        confidence = "MEDIUM"

    if expiry.get("decliningSession"):
        stand_down = True
        risks.append("session_declining_hard_to_make_money")
        actions.append("Stand aside or dual CE/PE hedge scalps only with score ≥72")

    if context.get("chopSession") and not expiry.get("dualScalpMode"):
        risks.append("chop_whipsaw_risk")
        actions.append("Wait for score ≥65 and breadth alignment")

    if expiry.get("dualScalpMode") and expiry.get("morningWindow"):
        bias = "BOTH"
        actions.append("Managed CE+PE scalps OK in expiry morning chop")
        confidence = "MEDIUM"

    sym_data = context.get("symbols") or {}
    bearish = sum(1 for s in sym_data.values() if s.get("breadth") == "BEARISH")
    bullish = sum(1 for s in sym_data.values() if s.get("breadth") == "BULLISH")
    if bearish > bullish and not stand_down:
        bias = "PUT"
        actions.append("PUT bias unless high-score momentum CALL override")
    elif bullish > bearish and not stand_down:
        bias = "CALL"

    recent = context.get("recentTrades") or []
    if len(recent) >= 3:
        losses = sum(1 for t in recent if (t.get("pnlInr") or 0) < 0)
        if losses >= 3:
            stand_down = True
            risks.append("recent_loss_cluster")
            actions.append("Pause — last trades bleeding; let guards cool down")

    read = (
        f"{day_mode}: "
        f"{len(sym_data)} symbols live, "
        f"expiry={'yes' if expiry.get('expirySession') else 'no'}, "
        f"session PnL ₹{expiry.get('sessionPnlInr', 0):,.0f}."
    )
    plan = "Morning selective scalps" if expiry.get("morningWindow") else "Reduce activity; respect time windows"

    return ComposerBrief(
        at=context.get("at", _now_iso()),
        source="rules",
        marketRead=read,
        tradeBias=bias,
        confidence=confidence,
        sessionPlan=plan,
        risks=risks[:5],
        actions=actions[:5],
        standDown=stand_down,
        raw=json.dumps({"source": "rules", "dayMode": day_mode}),
    )


def _parse_composer_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def brief_from_composer_text(text: str, *, context_hash: str = "") -> ComposerBrief:
    try:
        data = _parse_composer_json(text)
    except json.JSONDecodeError:
        return ComposerBrief(
            at=_now_iso(),
            source="composer-2.5",
            marketRead=text[:500],
            sessionPlan="See raw analysis",
            raw=text,
            contextHash=context_hash,
            error="json_parse_failed",
        )

    return ComposerBrief(
        at=_now_iso(),
        source="composer-2.5",
        marketRead=str(data.get("marketRead", "")),
        tradeBias=str(data.get("tradeBias", "STAND_ASIDE")).upper(),
        confidence=str(data.get("confidence", "LOW")).upper(),
        sessionPlan=str(data.get("sessionPlan", "")),
        risks=[str(x) for x in (data.get("risks") or [])][:6],
        actions=[str(x) for x in (data.get("actions") or [])][:6],
        standDown=bool(data.get("standDown")),
        raw=text,
        contextHash=context_hash,
    )


async def generate_composer_brief(context: dict[str, Any]) -> ComposerBrief:
    settings = get_settings()
    client = get_composer_client()
    if not settings.composer_monitor_enabled or not client.configured:
        return generate_rule_brief(context)

    user_prompt = (
        "Analyze this live Indian index options session and return JSON only.\n\n"
        f"CONTEXT:\n{json.dumps(context, indent=2, default=str)[:12000]}"
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        text = await client.chat_completion(
            messages,
            temperature=settings.composer_temperature,
            max_tokens=settings.composer_max_tokens,
        )
        brief = brief_from_composer_text(text, context_hash=str(hash(json.dumps(context, sort_keys=True, default=str))))
        return brief
    except ComposerClientError as exc:
        logger.warning("Composer brief failed, using rules: %s", exc)
        fallback = generate_rule_brief(context)
        fallback.error = str(exc)
        return fallback


async def run_monitor_cycle(
    snapshots: dict[str, SymbolSnapshot],
    *,
    force: bool = False,
) -> ComposerBrief:
    """Run one monitor cycle — rules always, Composer when configured."""
    global _last_brief, _last_run_mono

    import time

    settings = get_settings()
    if not settings.composer_monitor_enabled and not force:
        brief = generate_rule_brief(build_market_context(snapshots))
        _last_brief = brief
        return brief

    now_mono = time.monotonic()
    if (
        not force
        and _last_brief
        and (now_mono - _last_run_mono) < settings.composer_monitor_interval_seconds
    ):
        return _last_brief

    context = build_market_context(snapshots)
    if settings.composer_monitor_use_ai and get_composer_client().configured:
        brief = await generate_composer_brief(context)
    else:
        brief = generate_rule_brief(context)

    _last_run_mono = now_mono
    _last_brief = brief
    _brief_history.append(brief)
    return brief


def analyze_new_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag churn patterns on newly closed trades for monitor output."""
    alerts: list[dict[str, Any]] = []
    prev = None
    for t in trades:
        ctx = t.get("entryContext") or {}
        if prev:
            try:
                from datetime import datetime as dt

                gap = (
                    dt.fromisoformat(t["openedAt"])
                    - dt.fromisoformat(prev["closedAt"])
                ).total_seconds()
                if gap < 60:
                    alerts.append({
                        "type": "rapid_reentry",
                        "tradeId": t.get("id"),
                        "gapSeconds": gap,
                        "message": f"Re-entry {gap:.0f}s after {prev.get('side')} exit",
                    })
                if prev.get("side") != t.get("side"):
                    alerts.append({
                        "type": "ce_pe_flip",
                        "tradeId": t.get("id"),
                        "message": f"Flip {prev.get('side')} → {t.get('side')}",
                    })
            except Exception:
                pass
        score = ctx.get("selectionScore") or ctx.get("tqs")
        if score is not None and float(score) < 60:
            alerts.append({
                "type": "low_score",
                "tradeId": t.get("id"),
                "score": score,
                "message": f"Low entry score {score}",
            })
        prev = t
    return alerts


def get_latest_brief() -> Optional[dict[str, Any]]:
    return _last_brief.to_dict() if _last_brief else None


def get_brief_history(limit: int = 12) -> list[dict[str, Any]]:
    items = list(_brief_history)
    return [b.to_dict() for b in items[-limit:]]


def monitor_status() -> dict[str, Any]:
    settings = get_settings()
    client = get_composer_client()
    return {
        "enabled": settings.composer_monitor_enabled,
        "useAi": settings.composer_monitor_use_ai,
        "model": settings.cursor_composer_model,
        "runtime": settings.cursor_composer_runtime,
        "apiConfigured": client.configured,
        "intervalSeconds": settings.composer_monitor_interval_seconds,
        "latest": get_latest_brief(),
        "historyCount": len(_brief_history),
        "isExpirySession": None,
    }


def reset_monitor_state() -> None:
    global _last_brief, _last_run_mono, _last_trade_ids
    _brief_history.clear()
    _last_brief = None
    _last_run_mono = 0.0
    _last_trade_ids.clear()
