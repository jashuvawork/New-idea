import type { MultiSnapshot } from '../types';

/** Compact fingerprint — skip React updates when live data unchanged. */
export function snapshotSignature(json: MultiSnapshot): string {
  const auto = json.autoTrader;
  const snaps = json.snapshots ?? {};
  const snapParts = Object.keys(snaps)
    .sort()
    .map((sym) => {
      const s = snaps[sym];
      if (!s) return `${sym}:x`;
      const chart = s.spotChart;
      return [
        sym,
        s.spot?.toFixed(1) ?? '',
        s.tradeQualityScore?.toFixed(0) ?? '',
        s.breadth?.bias ?? '',
        s.regime ?? '',
        chart?.direction ?? '',
        chart?.momentum5Pct?.toFixed(2) ?? '',
      ].join(':');
    })
    .join('|');

  const chop = auto?.chopGuards;
  const lastN = chop?.lastNTrades;
  const openFp = (auto?.openPaperTrades ?? [])
    .map((t) => `${t.id}:${t.pnlInr?.toFixed(0) ?? 0}:${t.pnlPoints?.toFixed(1) ?? 0}`)
    .join(',');
  const lastEntryId = auto?.lastEntry?.tradeId ?? auto?.lastEntry?.at ?? '';
  const lastExitId = auto?.lastExit?.tradeId ?? auto?.lastExit?.at ?? '';

  // Omit timestamp — WS overlay heartbeats rewrite it every tick and remount the page.
  return [
    json.dataReady ? '1' : '0',
    // Only fingerprint waitingReason when it blocks data (avoids banner flash on null↔msg).
    json.dataReady ? '' : (json.waitingReason ?? ''),
    auto?.openPaperTrades?.length ?? 0,
    auto?.closedPaperTrades?.length ?? 0,
    auto?.dailyReport?.netPnlInr?.toFixed(0) ?? '',
    auto?.dailyReport?.profitFactor?.toFixed(2) ?? '',
    auto?.dailyReport?.wins ?? '',
    auto?.dailyReport?.losses ?? '',
    auto?.running ? '1' : '0',
    auto?.skipped?.length ?? 0,
    lastEntryId,
    lastExitId,
    openFp,
    chop?.dayMode ?? '',
    chop?.sessionPaused ? '1' : '0',
    chop?.lastNTradesPaused ? '1' : '0',
    lastN?.wins ?? '',
    lastN?.losses ?? '',
    lastN?.netPnlInr?.toFixed(0) ?? '',
    snapParts,
  ].join('::');
}
