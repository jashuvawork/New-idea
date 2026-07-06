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

  return [
    json.timestamp ?? '',
    json.waitingReason ?? '',
    json.dataReady ? '1' : '0',
    auto?.openPaperTrades?.length ?? 0,
    auto?.closedPaperTrades?.length ?? 0,
    auto?.dailyReport?.netPnlInr?.toFixed(0) ?? '',
    auto?.dailyReport?.profitFactor?.toFixed(2) ?? '',
    auto?.running ? '1' : '0',
    auto?.skipped?.length ?? 0,
    chop?.dayMode ?? '',
    chop?.sessionPaused ? '1' : '0',
    chop?.lastNTradesPaused ? '1' : '0',
    lastN?.wins ?? '',
    lastN?.losses ?? '',
    lastN?.netPnlInr?.toFixed(0) ?? '',
    snapParts,
  ].join('::');
}
