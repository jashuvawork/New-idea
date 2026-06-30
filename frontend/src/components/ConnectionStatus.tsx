import type { StreamMetrics } from '../types';

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
  marketClosed: boolean,
): StreamMetrics['connectionQuality'] {
  if (marketClosed && stalenessMs < 120_000) return 'good';
  if (stalenessMs > 5_000) return 'offline';
  if (stalenessMs > 2_000) return 'slow';
  return latencyQuality(latencyMs);
}

function qualityLabel(
  quality: StreamMetrics['connectionQuality'],
  streamMode?: StreamMetrics['streamMode'],
  marketClosed?: boolean,
) {
  if (marketClosed) return 'Market closed';
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

export function ConnectionStatus({
  metrics,
  marketClosed = false,
}: {
  metrics: StreamMetrics;
  marketClosed?: boolean;
}) {
  const ageSec = Math.floor(metrics.stalenessMs / 5000) * 5;
  const quality = deriveQuality(metrics.lastLatencyMs, metrics.stalenessMs, marketClosed);

  return (
    <div
      className={`flex items-center gap-2 text-[10px] px-2.5 py-1 rounded border ${qualityColor(quality)}`}
      title={`${metrics.streamMode === 'sse' ? 'SSE stream' : 'HTTP poll'} · Round-trip: ${metrics.lastLatencyMs}ms · Avg: ${metrics.avgLatencyMs}ms · Refresh every ${metrics.pollIntervalMs / 1000}s`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          quality === 'offline'
            ? 'bg-nexus-red'
            : quality === 'slow'
              ? 'bg-nexus-yellow'
              : marketClosed
                ? 'bg-gray-400'
                : 'bg-nexus-green'
        }`}
      />
      <span className="font-semibold">{qualityLabel(quality, metrics.streamMode, marketClosed)}</span>
      <span className="opacity-80">·</span>
      <span className="font-mono">{metrics.lastLatencyMs}ms</span>
      {metrics.lastUpdatedAt && (
        <>
          <span className="opacity-80">·</span>
          <span>{ageSec < 5 ? 'just now' : marketClosed ? `idle ${ageSec}s` : `${ageSec}s ago`}</span>
        </>
      )}
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
          {metrics.stalenessMs < 5000 ? 'live' : `${Math.round(metrics.stalenessMs / 1000)}s`}
        </span>
      </span>
    </div>
  );
}
