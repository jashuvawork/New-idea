import type { MultiSnapshot } from '../types';

export type MarketSessionPhase =
  | 'CLOSED'
  | 'PREMARKET'
  | 'LIVE_MARKET'
  | 'POST_MARKET'
  | 'UNKNOWN';

export type MarketSessionInfo = {
  phase: MarketSessionPhase;
  marketClosed: boolean;
  dataPauseReason: string | null;
};

function resolveSessionPhase(phases: string[]): MarketSessionPhase {
  if (phases.length === 0) return 'UNKNOWN';
  if (phases.every((p) => p === 'CLOSED')) return 'CLOSED';
  if (phases.some((p) => p === 'LIVE_MARKET')) return 'LIVE_MARKET';
  if (phases.some((p) => p === 'PREMARKET')) return 'PREMARKET';
  if (phases.some((p) => p === 'POST_MARKET')) return 'POST_MARKET';
  return 'UNKNOWN';
}

export function deriveMarketSession(data: MultiSnapshot | null | undefined): MarketSessionInfo {
  const snapshots = data?.snapshots ? Object.values(data.snapshots) : [];
  const phases = snapshots.map((s) => s.marketPhase ?? 'UNKNOWN');
  const phase = resolveSessionPhase(phases);
  const marketClosed = phase === 'CLOSED';

  const dataPauseReason =
    data?.waitingReason && !marketClosed
      ? data.waitingReason
      : data && !data.dataReady && !marketClosed
        ? (data.waitingReason ?? 'Refreshing market data…')
        : null;

  return { phase, marketClosed, dataPauseReason };
}

export function connectionStatusLabel(
  session: MarketSessionInfo,
  quality: 'excellent' | 'good' | 'slow' | 'offline',
  streamMode?: 'sse' | 'poll',
): string {
  if (session.marketClosed) return 'Market closed';
  if (session.dataPauseReason) {
    if (/cooling down|rate limit|429/i.test(session.dataPauseReason)) {
      return 'Rate limited';
    }
    return 'Data paused';
  }
  if (session.phase === 'PREMARKET') return 'Premarket';
  if (session.phase === 'POST_MARKET') return 'Post-market';
  if (streamMode === 'sse' && quality !== 'offline' && quality !== 'slow') {
    return 'Live';
  }
  switch (quality) {
    case 'excellent':
      return 'Fast';
    case 'good':
      return 'OK';
    case 'slow':
      return 'Stale';
    default:
      return 'Offline';
  }
}
