#!/usr/bin/env python3
"""Before/after validation for chartConf rescale (40–100) on closed trade history.

Uses stored chartConfidence as a proxy for pre-clamp raw when stored < 95, and
raw >= 95 when stored == 95 (old ceiling). Transformed thresholds preserve
pass/fail for every trade where stored < 95, and for all ceiling trades against
gates at or below 95.
"""

from __future__ import annotations

import json
import statistics
import sys
import urllib.request
from collections import Counter
from pathlib import Path

RAW_LO, RAW_HI = 40.0, 200.0
DMIN, DMAX = 40.0, 100.0

# Old clamp-era cutovers → rescaled display cutovers
OLD_TO_NEW = {
    "min_hold": (62.0, 48.2),
    "runner_no_breadth": (78.0, 54.2),
    "elevated_hold": (85.0, 56.9),
    "elevated_size": (90.0, 58.8),
    "high_conviction": (85.0, 56.9),
    "defer_tp": (95.0, 60.6),
}


def rescale(raw: float) -> float:
    t = (float(raw) - RAW_LO) / (RAW_HI - RAW_LO)
    return round(max(DMIN, min(DMAX, DMIN + t * (DMAX - DMIN))), 1)


def load_trades(url: str | None) -> list[dict]:
    if url:
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.load(resp)
    else:
        path = Path("/tmp/closed_trades.json")
        payload = json.loads(path.read_text())
    if isinstance(payload, dict) and "trades" in payload:
        return list(payload["trades"])
    if isinstance(payload, list):
        return payload
    raise SystemExit(f"unexpected payload type: {type(payload)}")


def chart_conf(trade: dict) -> float | None:
    ctx = trade.get("entryContext") or {}
    c = ctx.get("chartConfidence")
    if c is None:
        c = (ctx.get("exitPlan") or {}).get("chartConfidence")
    if c is None:
        return None
    return float(c)


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://65.0.136.146:8000/api/auto-trader/history/trades/closed"
    try:
        trades = load_trades(url)
    except Exception:
        trades = load_trades(None)

    rows = []
    for t in trades:
        stored = chart_conf(t)
        if stored is None:
            continue
        # Proxy raw: exact when below old ceiling; lower-bound when capped.
        raw_proxy = stored
        capped = stored >= 94.9
        display = rescale(raw_proxy)
        rows.append(
            {
                "id": t.get("id"),
                "symbol": t.get("symbol"),
                "day": (t.get("openedAt") or t.get("entryTs") or "")[:10],
                "pnl": float(t.get("pnlInr") or t.get("pnl") or 0),
                "stored": stored,
                "raw_proxy": raw_proxy,
                "display": display,
                "was_capped": capped,
            }
        )

    if not rows:
        print("no trades with chartConfidence")
        return 1

    stored_vals = [r["stored"] for r in rows]
    display_vals = [r["display"] for r in rows]

    def dist(vals: list[float]) -> dict:
        s = sorted(vals)
        def pct(p: float) -> float:
            return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]
        return {
            "n": len(vals),
            "min": round(min(vals), 1),
            "p10": round(pct(0.1), 1),
            "p25": round(pct(0.25), 1),
            "median": round(statistics.median(vals), 1),
            "p75": round(pct(0.75), 1),
            "p90": round(pct(0.9), 1),
            "max": round(max(vals), 1),
            "at_ceiling_95": sum(1 for v in vals if v >= 94.9),
            "at_ceiling_pct": round(100 * sum(1 for v in vals if v >= 94.9) / len(vals), 1),
            "buckets": dict(sorted(Counter(int(v) // 5 * 5 for v in vals).items())),
        }

    gate_report = {}
    for name, (old_thr, new_thr) in OLD_TO_NEW.items():
        old_pass = [r["stored"] >= old_thr for r in rows]
        new_pass = [r["display"] >= new_thr for r in rows]
        agree = sum(1 for a, b in zip(old_pass, new_pass) if a == b)
        # For capped rows, monotonic transform guarantees agree when using raw_proxy=stored;
        # note true raw>=95 still passes new_thr=rescale(95).
        gate_report[name] = {
            "old_threshold": old_thr,
            "new_threshold": new_thr,
            "old_pass_rate_pct": round(100 * sum(old_pass) / len(rows), 1),
            "new_pass_rate_pct": round(100 * sum(new_pass) / len(rows), 1),
            "agreement_pct": round(100 * agree / len(rows), 1),
            "disagree_n": len(rows) - agree,
        }

    # Sizing-relevant: high conviction + elevated size gates on chartConf alone
    sizing = {
        "high_conviction_chart_gate": gate_report["high_conviction"],
        "elevated_size_chart_gate": gate_report["elevated_size"],
        "defer_tp_gate": gate_report["defer_tp"],
        "elevated_hold_gate": gate_report["elevated_hold"],
        "min_hold_gate": gate_report["min_hold"],
    }

    report = {
        "title": "chartConf rescale validation (40–100)",
        "anchors": {"raw_lo": RAW_LO, "raw_hi": RAW_HI, "display_min": DMIN, "display_max": DMAX},
        "sample": {"closed_trades": len(trades), "with_chart_confidence": len(rows)},
        "before_stored_distribution": dist(stored_vals),
        "after_display_from_stored_proxy": dist(display_vals),
        "note": (
            "after_display uses rescale(stored). Trades pinned at 95 underestimate top-end "
            "spread (true raw often 150–200 → display 82–100). Gate agreement uses the same "
            "proxy; for stored==95, true raw>=95 still clears every transformed gate ≤60.6."
        ),
        "gates": gate_report,
        "sizing_behavior": sizing,
        "all_gates_perfect_agreement": all(g["agreement_pct"] == 100.0 for g in gate_report.values()),
    }

    out = Path("/opt/cursor/artifacts/chartconf_rescale_validation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    md = Path("/opt/cursor/artifacts/chartconf_rescale_validation.md")
    lines = [
        "# chartConf rescale validation",
        "",
        f"- Sample: {report['sample']['with_chart_confidence']} / {report['sample']['closed_trades']} closed trades with chartConf",
        f"- Anchors: raw [{RAW_LO}, {RAW_HI}] → display [{DMIN}, {DMAX}]",
        f"- All gates perfect agreement: **{report['all_gates_perfect_agreement']}**",
        "",
        "## Distribution",
        "",
        "| | before (stored) | after (rescale proxy) |",
        "|---|---|---|",
    ]
    b, a = report["before_stored_distribution"], report["after_display_from_stored_proxy"]
    for k in ("min", "p10", "median", "p90", "max", "at_ceiling_pct"):
        lines.append(f"| {k} | {b[k]} | {a[k]} |")
    lines += ["", "## Gate agreement (sizing / hold)", ""]
    for name, g in gate_report.items():
        lines.append(
            f"- **{name}**: {g['old_threshold']} → {g['new_threshold']} — "
            f"pass {g['old_pass_rate_pct']}%→{g['new_pass_rate_pct']}% — "
            f"agree {g['agreement_pct']}%"
        )
    lines += ["", report["note"], ""]
    md.write_text("\n".join(lines))

    print(json.dumps(report, indent=2))
    print(f"\nwrote {out} and {md}")
    return 0 if report["all_gates_perfect_agreement"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
