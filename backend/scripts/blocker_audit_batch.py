#!/usr/bin/env python3
"""Blocker audit batch — live trades, funnel, EOD replay (structural + parity), classification."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_DIR = Path("/tmp/blocker_audit_archives")
API_BASE = "https://api.jashuvatrade.xyz"
WEB_BASE = "https://www.jashuvatrade.xyz"
OUT_JSON = Path("/opt/cursor/artifacts/blocker-audit-latest.json")
OUT_MD = Path("/opt/cursor/artifacts/blocker-classification.md")

# Heuristic labels for gate families (Phase 2 rubric).
REENTRY_REASON_MARKERS: tuple[str, ...] = (
    "reentry",
    "failed_launch_reentry",
    "peak_fade_same_side",
    "session_same_strike_loss",
    "session_same_side_loss",
    "exhausted_ftv",
    "win_reentry_velocity",
    "late_reentry_near_session_peak",
    "post_win_late_reentry_waive",
    "same_strike_post_win",
    "continuation_leg",
)

ENTRY_REASON_PREFIXES: tuple[str, ...] = (
    "elite_",
    "fake_explosion_trap",
    "top_moment",
    "ftv_elite",
    "pretrade_",
    "explosion_score",
    "score_",
    "chart_",
    "premium_out",
    "tier_not",
    "immature_",
    "coil_",
    "post_peak",
    "session_trough",
    "extended_session",
    "live_explosion",
    "timing_",
    "hard_block_",
    "counter_breadth",
)

GATE_LABELS: dict[str, str] = {
    "reentry_ml_win_prob_low": "RELAX_QUALITY",
    "quality_moment_passport_waive_reentry_ml": "RELAX_QUALITY",
    "quality_moment_passport_waive_peak": "RELAX_QUALITY",
    "elite_timing_not_good_or_ok": "RELAX_QUALITY",
    "late_reentry_near_session_peak": "RELAX_QUALITY",
    "fake_explosion_trap_post_win_fresh_near_base": "KEEP_NARROW",
    "fake_explosion_trap_post_win_extended_chase": "KEEP_NARROW",
    "fake_explosion_trap_post_win_afternoon": "KEEP",
    "fake_explosion_trap_midday_no_structure": "KEEP",
    "fake_explosion_trap_chop_elite_armed_base": "KEEP",
    "fake_explosion_trap_premium_flat_extension": "KEEP",
    "failed_launch_reentry_cooldown": "KEEP",
    "session_same_strike_loss_reentry_blocked": "KEEP",
    "session_same_side_loss_reentry_cooldown": "KEEP",
    "peak_fade_same_side_reentry_cooldown": "KEEP",
    "exhausted_ftv_requires_new_base_reacceleration": "KEEP",
    "hard_block_call_vs_bearish_breadth": "KEEP_NARROW",
    "explosion_call_vs_bearish_chart": "KEEP_NARROW",
    "pretrade_counter_breadth": "KEEP_NARROW",
    "daily_loss_stop_expiry_top_only": "KEEP",
    "composer_stand_down": "KEEP",
}


def _get_json(url: str, timeout: float = 120.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _has_premium_tape(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return "premium_tape.jsonl" in zf.namelist()
    except Exception:
        return False


def _download_archive(date: str) -> bool:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"radar-{date}.zip"
    if dest.exists() and dest.stat().st_size > 10_000 and _has_premium_tape(dest):
        return True
    for base in (API_BASE, WEB_BASE):
        try:
            urllib.request.urlretrieve(f"{base}/api/ai/radar-archives/{date}", dest)
            if dest.stat().st_size > 1000 and _has_premium_tape(dest):
                return True
        except Exception:
            continue
    return False


def _audit_settings(*, parity: bool = False) -> Settings:
    s = Settings()
    s.radar_archive_dir = str(ARCHIVE_DIR)
    s.trade_store_dir = str(ARCHIVE_DIR / "trades")
    s.eod_replay_live_session_gates_enabled = True
    s.eod_replay_structural_gates_enabled = True
    s.eod_replay_reentry_ml_gate_enabled = True
    s.eod_replay_reentry_velocity_gate_enabled = True
    s.eod_replay_exhausted_ftv_gate_enabled = True
    s.eod_replay_pretrade_enabled = parity
    return s


def _is_reentry_reason(reason: str) -> bool:
    r = str(reason or "").lower()
    return any(m in r for m in REENTRY_REASON_MARKERS)


def _is_entry_reason(reason: str) -> bool:
    r = str(reason or "").lower()
    if _is_reentry_reason(r):
        return False
    return any(r.startswith(p) for p in ENTRY_REASON_PREFIXES)


def _quality_moment_radar_row(row: Mapping[str, Any]) -> bool:
    tier = str(row.get("bestTier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False
    outcome = row.get("radarOutcome") or {}
    mfe = float(outcome.get("maxFavorableExcursionPct") or outcome.get("mfePct") or 0)
    if mfe >= 30:
        return True
    for ev in row.get("timeline") or []:
        if str(ev.get("tier") or "").upper() in ("ELITE", "EXPLODING"):
            return True
    return tier in ("ELITE", "EXPLODING")


def _summarize_funnel(funnel: dict[str, Any]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    entry_reasons: Counter[str] = Counter()
    reentry_reasons: Counter[str] = Counter()
    by_stage: Counter[str] = Counter()
    quality_blocked_entry: list[dict[str, Any]] = []

    for row in funnel.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        entered = bool(row.get("entered"))
        blockers = [str(b) for b in (row.get("blockers") or [])]
        for b in blockers:
            reasons[b] += 1
            if _is_reentry_reason(b):
                reentry_reasons[b] += 1
            else:
                entry_reasons[b] += 1
        for ev in row.get("timeline") or []:
            if ev.get("event") == "GATED" and ev.get("reason"):
                reason = str(ev["reason"])
                reasons[reason] += 1
                stage = str(ev.get("stage") or "unknown")
                by_stage[stage] += 1
                if _is_reentry_reason(reason):
                    reentry_reasons[reason] += 1
                else:
                    entry_reasons[reason] += 1
        if (
            not entered
            and blockers
            and _quality_moment_radar_row(row)
        ):
            entry_only = [b for b in blockers if not _is_reentry_reason(b)]
            reentry_only = [b for b in blockers if _is_reentry_reason(b)]
            quality_blocked_entry.append(
                {
                    "key": row.get("key"),
                    "bestTier": row.get("bestTier"),
                    "blockers": blockers,
                    "entryBlockers": entry_only,
                    "reentryBlockers": reentry_only,
                    "primaryEntryBlock": entry_only[0] if entry_only else None,
                    "radarOutcome": row.get("radarOutcome"),
                }
            )

    quality_blocked_entry.sort(
        key=lambda r: -float(
            (r.get("radarOutcome") or {}).get("maxFavorableExcursionPct")
            or (r.get("radarOutcome") or {}).get("mfePct")
            or 0
        )
    )

    return {
        "detected": funnel.get("detected"),
        "blocked": funnel.get("blocked"),
        "entered": funnel.get("entered"),
        "topBlockReasons": reasons.most_common(25),
        "topEntryBlockReasons": entry_reasons.most_common(20),
        "topReentryBlockReasons": reentry_reasons.most_common(20),
        "blocksByStage": by_stage.most_common(12),
        "qualityBlockedNotEntered": quality_blocked_entry[:15],
        "qualityBlockedNotEnteredCount": len(quality_blocked_entry),
    }


def _live_trades_summary(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in trades:
        ctx = t.get("entryContext") or {}
        out.append(
            {
                "id": t.get("id"),
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "strike": t.get("strike"),
                "openedAt": t.get("openedAt"),
                "closedAt": t.get("closedAt"),
                "sessionDate": t.get("sessionDate"),
                "pnlInr": t.get("pnlInr"),
                "exitReason": t.get("exitReason"),
                "ictFirstLift": ctx.get("ictFirstLift") or ctx.get("firstLiftCapture"),
                "momentType": ctx.get("momentType"),
                "mlWinProb": (ctx.get("liveEntryScoreMeta") or {}).get("mlWinProb"),
                "radarKey": ctx.get("radarKey"),
            }
        )
    return out


def _window_after_win(close_iso: str, *, minutes: int = 150) -> tuple[str, str] | None:
    try:
        closed = datetime.fromisoformat(str(close_iso).replace("Z", "+00:00"))
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=IST)
        closed = closed.astimezone(IST)
        start = (closed + timedelta(minutes=2)).strftime("%H:%M:%S")
        end = (closed + timedelta(minutes=minutes)).strftime("%H:%M:%S")
        return start, end
    except Exception:
        return None


def _classify_aggregate(all_reasons: Counter[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for reason, count in all_reasons.most_common(60):
        label = GATE_LABELS.get(reason)
        if not label:
            if reason.startswith("fake_explosion_trap"):
                label = "KEEP_NARROW"
            elif "loss" in reason or "cooldown" in reason or "stop" in reason:
                label = "KEEP"
            elif reason.startswith("elite_score_below") or reason.startswith("elite_explosive"):
                label = "RELAX_QUALITY"
            elif reason.startswith("elite_timing") or reason.startswith("elite_v_rip"):
                label = "RELAX_QUALITY"
            elif "rank_floor" in reason or "score_" in reason:
                label = "KEEP_NARROW"
            else:
                label = "REVIEW"
        rows.append({"reason": reason, "count": count, "label": label})
    return rows


def _write_classification_md(
    classification: list[dict[str, Any]],
    rollup: dict[str, Any],
    *,
    entry_classification: list[dict[str, Any]] | None = None,
    reentry_classification: list[dict[str, Any]] | None = None,
    sample_quality_entry: list[dict[str, Any]] | None = None,
) -> None:
    lines = [
        "# Blocker classification (batch audit)",
        "",
        f"Run rollup: {json.dumps(rollup, indent=2)}",
        "",
        "## All gates (replay + live funnel)",
        "",
        "| Label | Reason | Count |",
        "|-------|--------|-------|",
    ]
    for row in classification:
        lines.append(
            f"| {row['label']} | `{row['reason']}` | {row['count']} |"
        )
    if entry_classification:
        lines.extend(
            [
                "",
                "## Live funnel — first entry / selector (not re-entry stack)",
                "",
                "| Label | Reason | Count |",
                "|-------|--------|-------|",
            ]
        )
        for row in entry_classification[:35]:
            lines.append(
                f"| {row['label']} | `{row['reason']}` | {row['count']} |"
            )
    if reentry_classification:
        lines.extend(
            [
                "",
                "## Live funnel — re-entry stack",
                "",
                "| Label | Reason | Count |",
                "|-------|--------|-------|",
            ]
        )
        for row in reentry_classification[:25]:
            lines.append(
                f"| {row['label']} | `{row['reason']}` | {row['count']} |"
            )
    if sample_quality_entry:
        lines.extend(
            [
                "",
                "## Quality radar rows blocked (sample — entry blockers first)",
                "",
                "| Key | Tier | Primary entry block | All blockers |",
                "|-----|------|---------------------|--------------|",
            ]
        )
        for row in sample_quality_entry[:12]:
            blockers = ", ".join(f"`{b}`" for b in (row.get("blockers") or [])[:4])
            lines.append(
                f"| {row.get('key')} | {row.get('bestTier')} | "
                f"`{row.get('primaryEntryBlock')}` | {blockers} |"
            )
    lines.extend(
        [
            "",
            "## Recommended actions (from rubric)",
            "",
            "- **RELAX_QUALITY**: waive when `quality_moment_passport_active` (FTV/V + structure) — **entry** (elite score/timing/V-shallow, peak chase) and **re-entry** (ML after wins).",
            "- **KEEP_NARROW**: scope post-win fake-trap to same-strike or passport — not session-wide blind block.",
            "- **KEEP**: loss cooldowns, failed launch, hard FOMO flat-extension, daily loss stop.",
            "",
        ]
    )
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    import os

    max_dates = int(os.environ.get("BLOCKER_AUDIT_MAX_DATES", "8") or "8")
    skip_replay = os.environ.get("BLOCKER_AUDIT_SKIP_REPLAY", "").lower() in (
        "1",
        "true",
        "yes",
    )
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    archives: list[str] = []
    try:
        arch_resp = _get_json(f"{API_BASE}/api/ai/radar-archives?limit=30")
        for row in arch_resp.get("archives") or []:
            d = row.get("date") or row.get("sessionDate")
            if d:
                archives.append(str(d))
    except Exception as exc:
        print(f"radar-archives list failed: {exc}", flush=True)

    live_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        closed_resp = _get_json(f"{API_BASE}/api/auto-trader/history/trades/closed?limit=500")
        for t in closed_resp.get("trades") or []:
            sd = t.get("sessionDate")
            if not sd and t.get("closedAt"):
                try:
                    sd = datetime.fromisoformat(
                        str(t["closedAt"]).replace("Z", "+00:00")
                    ).astimezone(IST).strftime("%Y-%m-%d")
                except Exception:
                    sd = None
            if sd:
                live_by_date[str(sd)].append(t)
    except Exception as exc:
        print(f"closed trades fetch failed: {exc}", flush=True)

    dates = sorted(set(archives) | set(live_by_date.keys()))[-max_dates:]
    print(f"Audit dates ({len(dates)}, max={max_dates}): {dates}", flush=True)

    from app.engines.eod_local_base_replay import replay_local_base_day

    all_reasons: Counter[str] = Counter()
    funnel_entry: Counter[str] = Counter()
    funnel_reentry: Counter[str] = Counter()
    quality_entry_samples: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    download_failed: list[str] = []

    for date in dates:
        print(f"\n[{date}] ...", flush=True)
        has_tape = _download_archive(date)
        if not has_tape and date not in live_by_date:
            download_failed.append(date)
            continue

        row: dict[str, Any] = {"date": date, "hasPremiumTape": has_tape}

        live = _live_trades_summary(live_by_date.get(date, []))
        row["liveTrades"] = live

        try:
            funnel = _get_json(f"{API_BASE}/api/ai/radar-funnel/{date}", timeout=90)
            row["funnel"] = _summarize_funnel(funnel)
            for r, c in row["funnel"].get("topBlockReasons") or []:
                all_reasons[r] += int(c)
            for r, c in row["funnel"].get("topEntryBlockReasons") or []:
                funnel_entry[r] += int(c)
            for r, c in row["funnel"].get("topReentryBlockReasons") or []:
                funnel_reentry[r] += int(c)
            for sample in row["funnel"].get("qualityBlockedNotEntered") or []:
                quality_entry_samples.append({"date": date, **sample})
        except Exception as exc:
            row["funnelError"] = str(exc)

        try:
            eod = _get_json(f"{API_BASE}/api/ai/eod-trade-report/{date}", timeout=120)
            row["eodScorecard"] = (eod.get("scorecard") or {}).get("overall")
            row["eodTradeCount"] = eod.get("tradeCount")
        except Exception as exc:
            row["eodError"] = str(exc)

        if has_tape and not skip_replay:
            settings_a = _audit_settings(parity=False)
            rep_a = replay_local_base_day(date, settings=settings_a)
            gates_a = dict(rep_a.get("gateStats") or {})
            row["replayStructural"] = {
                "status": rep_a.get("status"),
                "tradeCount": rep_a.get("tradeCount"),
                "netPnlInr": rep_a.get("netPnlInr"),
                "topGates": sorted(gates_a.items(), key=lambda kv: -kv[1])[:15],
            }
            for g, c in gates_a.items():
                all_reasons[g] += int(c)

            settings_b = _audit_settings(parity=True)
            rep_b = replay_local_base_day(date, settings=settings_b)
            gates_b = dict(rep_b.get("gateStats") or {})
            row["replayParityPretrade"] = {
                "status": rep_b.get("status"),
                "tradeCount": rep_b.get("tradeCount"),
                "netPnlInr": rep_b.get("netPnlInr"),
                "topGates": sorted(gates_b.items(), key=lambda kv: -kv[1])[:15],
            }

        wins = [t for t in live if float(t.get("pnlInr") or 0) > 0]
        row["postWinWindows"] = []
        if has_tape and wins:
            from app.engines.eod_local_base_replay import generate_window_replay

            for w in wins[:3]:
                win = w.get("closedAt")
                if not win:
                    continue
                span = _window_after_win(str(win))
                if not span:
                    continue
                start, end = span
                side = str(w.get("side") or "").upper() or None
                try:
                    wr = generate_window_replay(
                        date, start=start, end=end, side=side if side in ("CALL", "PUT") else None,
                    )
                    row["postWinWindows"].append(
                        {
                            "afterTrade": w.get("radarKey") or w.get("id"),
                            "window": f"{start}-{end}",
                            "tradeCount": wr.get("tradeCount"),
                            "topGates": sorted(
                                (wr.get("gateStats") or {}).items(),
                                key=lambda kv: -kv[1],
                            )[:8],
                        }
                    )
                except Exception as exc:
                    row["postWinWindows"].append(
                        {"afterTrade": w.get("id"), "error": str(exc)}
                    )

        day_rows.append(row)

    classification = _classify_aggregate(all_reasons)
    entry_classification = _classify_aggregate(funnel_entry)
    reentry_classification = _classify_aggregate(funnel_reentry)
    quality_entry_samples.sort(
        key=lambda r: -float(
            (r.get("radarOutcome") or {}).get("maxFavorableExcursionPct")
            or (r.get("radarOutcome") or {}).get("mfePct")
            or 0
        )
    )
    rollup = {
        "dates": len(day_rows),
        "withTape": sum(1 for d in day_rows if d.get("hasPremiumTape")),
        "liveTradeDays": len(live_by_date),
        "uniqueBlockReasons": len(all_reasons),
        "funnelEntryBlockReasons": len(funnel_entry),
        "funnelReentryBlockReasons": len(funnel_reentry),
        "qualityRadarBlockedNotEntered": len(quality_entry_samples),
    }
    out = {
        "runAt": datetime.now(IST).isoformat(),
        "apiBase": API_BASE,
        "archiveDir": str(ARCHIVE_DIR),
        "downloadFailed": download_failed,
        "rollup": rollup,
        "classification": classification,
        "funnelEntryClassification": entry_classification,
        "funnelReentryClassification": reentry_classification,
        "qualityBlockedAtEntry": quality_entry_samples[:40],
        "days": day_rows,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    _write_classification_md(
        classification,
        rollup,
        entry_classification=entry_classification,
        reentry_classification=reentry_classification,
        sample_quality_entry=quality_entry_samples,
    )
    print(f"\nWrote {OUT_JSON}", flush=True)
    print(f"Wrote {OUT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
