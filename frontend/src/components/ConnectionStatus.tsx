import type { StreamMetrics } from '../types';
import { connectionStatusLabel, type MarketSessionInfo } from '../lib/marketSession';

function latencyQuality(ms: number): StreamMetrics['connectionQuality'] {
  if (ms <= 0) return 'offline';
  if (ms < 80) return 'excellent';
  if (ms < 250) return 'good';
  return 'slow';
}

function qualityColor(quality: StreamMetrics['connectionQuality']) {
  switch (quality) {
    case 'excellent':
      return 'text-nexus-green bg-nexus-green/15 border-nexus-green/30';
    case 'good':
      return 'text-nexus-accent bg-nexus-accent/10 border-nexus-accent/30';
    case 'slow':
      return 'text-nexus-yellow bg-nexus-yellow/10 border-nexus-yellow/30';
    default:
      return 'text-nexus-red bg-nexus-red/10 border-nexus-red/30';
  }
}

function deriveQuality(
  latencyMs: number,
  stalenessMs: number,
  session: MarketSessionInfo,
  dataReady?: boolean,
  streamMode?: StreamMetrics['streamMode'],
): StreamMetrics['connectionQuality'] {
  if (session.marketClosed && stalenessMs < 120_000) return 'good';
  if (session.dataPauseReason) {
    if (/cooling down|rate limit|429/i.test(session.dataPauseReason)) return 'slow';
    return 'slow';
  }
  if (dataReady && stalenessMs < 4_000) {
    if (streamMode === 'sse') {
      if (stalenessMs > 10_000) return 'offline';
      if (stalenessMs > 3_000) return 'slow';
      return stalenessMs > 1_000 ? 'good' : 'excellent';
    }
    return latencyQuality(latencyMs);
  }
  if (streamMode === 'sse') {
    if (!dataReady && stalenessMs > 20_000) return 'offline';
    if (stalenessMs > 10_000) return 'offline';
    if (stalenessMs > 3_000) return 'slow';
    if (stalenessMs > 1_000) return 'good';
    return 'excellent';
  }
  if (dataReady && stalenessMs < 30_000) return latencyQuality(latencyMs);
  if (stalenessMs > 20_000) return 'offline';
  if (stalenessMs > 5_000) return 'slow';
  if (stalenessMs > 3_000) return 'slow';
  return latencyQuality(latencyMs);
}

export function ConnectionStatus({
  metrics,
  session,
  dataReady,
}: {
  metrics: StreamMetrics;
  session: MarketSessionInfo;
  dataReady?: boolean;
}) {
  const ageSec = Math.floor(metrics.stalenessMs / 1000);
  const quality = deriveQuality(
    metrics.lastLatencyMs,
    metrics.stalenessMs,
    session,
    dataReady,
    metrics.streamMode,
  );
  const label = connectionStatusLabel(session, quality, metrics.streamMode, dataReady);
  const paused = Boolean(session.dataPauseReason);
  const latencyLabel = metrics.streamMode === 'sse' && metrics.lastLatencyMs > 0
    ? `${metrics.lastLatencyMs}ms fresh`
    : `${metrics.lastLatencyMs}ms`;

  const ageLabel = !metrics.lastUpdatedAt
    ? '—'
    : ageSec < 5
      ? 'live'
      : session.marketClosed
        ? `idle ${ageSec}s`
        : `${ageSec}s`;

  return (
    <div
      className={`conn-status flex items-center gap-2 text-[10px] px-2.5 py-1 rounded border whitespace-nowrap ${qualityColor(quality)}`}
      title={[
        metrics.streamMode === 'sse' ? 'SSE stream' : 'HTTP poll',
        metrics.streamMode === 'sse'
          ? `Data age: ${metrics.stalenessMs}ms`
          : `Round-trip: ${metrics.lastLatencyMs}ms`,
        `Avg: ${metrics.avgLatencyMs}ms`,
        `Refresh every ${metrics.pollIntervalMs / 1000}s`,
        session.dataPauseReason,
      ].filter(Boolean).join(' · ')}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          quality === 'offline'
            ? 'bg-nexus-red'
            : quality === 'slow' || paused
              ? 'bg-nexus-yellow'
              : session.marketClosed
                ? 'bg-gray-400'
                : 'bg-nexus-green'
        }`}
      />
      <span className="font-semibold truncate max-w-[7rem]">{label}</span>
      <span className="opacity-80">·</span>
      <span className="font-mono tabular-nums w-[4.5rem]">{latencyLabel}</span>
      <span className="opacity-80">·</span>
      <span className="font-mono tabular-nums w-[3.25rem]">{ageLabel}</span>
    </div>
  );
}

export function LatencyFooter({ metrics }: { metrics: StreamMetrics }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-nexus-muted">
      <span>
        Latency: <span className="font-mono text-gray-300">{metrics.lastLatencyMs}ms</span>
        {' '}(avg <span className="font-mono text-gray-300">{metrics.avgLatencyMs}ms</span>)
      </span>
      <span>
        Mode:{' '}
        <span className="font-mono text-gray-300">
          {metrics.streamMode === 'sse' ? 'SSE live' : 'HTTP poll'}
        </span>
      </span>
      <span>
        Refresh: every <span className="font-mono text-gray-300">{metrics.pollIntervalMs / 1000}s</span>
      </span>
      <span>
        Data age:{' '}
        <span className="font-mono text-gray-300">
          {metrics.stalenessMs < 1000 ? 'live' : `${Math.round(metrics.stalenessMs / 1000)}s`}
        </span>
      </span>
    </div>
  );
}
