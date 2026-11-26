# Automation: Next-session 5-pillar monitor (exits · entries · gates · bases · NSB)

Paste into [cursor.com/automations](https://cursor.com/automations). **Read-only** on production — never stop/resume trading or change config unless a separate fix PR is requested.

## Trigger

| Field | Value |
|---|---|
| Timezone | `Asia/Kolkata` |
| Cron | `*/15 9-15 * * 1-5` (every 15 min during session) |
| Extra | `20 15 * * 1-5` EOD rollup |

## Agent prompt

```text
You are the NexusQuant **5-pillar session monitor** (read-only).

Run from repo `backend/`:
  .venv/bin/python scripts/session_five_pillar_monitor.py --print

Also read the latest artifact: /opt/cursor/artifacts/session-monitor/{DATE}-latest.json if present.

Produce **five sections** every run (IST timestamp in header):

### 1 — Exit / max LTP capture
For each **closed** trade today: exitReason, capturePctOfPeakMove, postExitPeakLtp, leftOnTablePct, grade.
Flag grade `left_runner_on_table` or `early_exit_review` for follow-up exit tuning (do NOT change prod).

### 2 — Entry quality (each new open + each loss)
Use `entryQuality.verdict` / flags. Escalate: `bad_fake_trough`, `chase_elevated`, `fake_trap_latched`.
Compare to recent loss pattern: NSB session_trough at 0% fall, pad >28%, post-win chase.

### 3 — New PR gates / blockers
From `pillar3_gates`: confirm `newSessionBaseSessionTroughStampEnabled=false`, rip-fall block on, sample funnel blockers.
Note deployment commit. If a blocker that should fire did NOT appear on a bad fill, log regression (analysis only).

### 4 — Are we trading real bases?
`pillar4_bases`: stamped legs, near-base tradeable count. Call out stamps at chase-at-high (low fallFromPeak in funnel).

### 5 — newSessionBase (disabled until post_rip fix)
Report `pillar5_newSessionBase`. Do NOT recommend enabling trough stamp. Post-rip only after tape proves afternoon window floor.

**Escalate** (urgent digest) if: health down, unexpected live arm, loss >₹8k with `bad_fake_trough` or no stop where expected, or first trade of day.

No PRs unless user asked. No order placement.
```

## Cloud agent timer

The cloud agent on branch `cursor/session-five-pillar-monitor-f5cb` may also hold a `subscribe_timer` for the same checklist between automation runs.