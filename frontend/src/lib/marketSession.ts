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

  const reason = data?.waitingReason?.trim() ?? '';
  let dataPauseReason: string | null = null;
  if (!marketClosed && data) {
    if (!data.dataReady) {
      dataPauseReason = reason || 'Refreshing market data…';
    } else if (/cooling down|rate limit|429|not authenticated/i.test(reason)) {
      dataPauseReason = reason;
    } else if (/showing last good data/i.test(reason)) {
      dataPauseReason = reason;
    }
    // refresh in progress + dataReady => still live, not paused
  }

  return { phase, marketClosed, dataPauseReason };
}

export function connectionStatusLabel(
  session: MarketSessionInfo,
  quality: 'excellent' | 'good' | 'slow' | 'offline',
  streamMode?: 'sse' | 'poll',
  dataReady?: boolean,
): string {
  if (session.marketClosed) return 'Market closed';
  if (quality === 'offline') return 'Offline';
  if (quality === 'slow' && session.dataPauseReason) return 'Reconnecting';
  if (session.dataPauseReason) {
    if (/showing last good data/i.test(session.dataPauseReason)) {
      return 'Live (cached)';
    }
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
  if (dataReady && quality === 'good') {
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
