import { useCallback, useEffect, useRef, useState } from 'react';
import type { DeploymentReadiness, DeploymentStatus, MultiSnapshot, PerformanceMilestone, StreamMetrics, TradeHistoryResponse, TradeLogResponse, WeeklyDashboard } from '../types';
import { snapshotSignature } from './snapshotSignature';

// Production: same-origin /api (Vercel HTTPS → EC2). Do NOT use http:// IP — mixed-content blocks SSE.
const API_BASE = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_URL || '');
const STREAM_BASE = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_STREAM_BASE_URL || API_BASE);
const POLL_MS = Number(import.meta.env.VITE_POLL_MS || 500);
const UI_TICK_MS = Math.max(POLL_MS, 200);
const SSE_MIN_INTERVAL_MS = Math.max(Number(import.meta.env.VITE_SSE_THROTTLE_MS || 50), 25);
// Vercel rewrites kill proxied SSE after ~30s (hard proxy limit). Prefer HTTP poll unless
// a direct stream base URL bypasses Vercel (e.g. https://api.jashuvatrade.xyz).
const SSE_THROUGH_VERCEL = !import.meta.env.DEV && !import.meta.env.VITE_STREAM_BASE_URL;
const SSE_ENABLED = import.meta.env.VITE_SSE_ENABLED !== 'false' && !SSE_THROUGH_VERCEL;
const SSE_STALE_POLL_MS = Number(import.meta.env.VITE_SSE_STALE_POLL_MS || 1000);
/** Reconnect before Vercel/proxy ~30s SSE cutoff when using a direct stream URL. */
const SSE_RECONNECT_MS = Number(import.meta.env.VITE_SSE_RECONNECT_MS || 25_000);
const HEALTH_URL = `${API_BASE || ''}/health`;
/** With cached dashboard data, stay slow/reconnecting — not offline — through rebuild blips. */
const TRANSPORT_OFFLINE_MS = 90_000;
const DATA_OFFLINE_MS = 90_000;
const SNAPSHOT_URL = `${API_BASE}/api/market/snapshots/cached`;
// Same-origin only — do NOT fall back to api.jashuvatrade.xyz (stale DNS → old EC2 IP
// times out and makes the UI look "unreachable" while www→EIP proxy still works).
const SNAPSHOT_FALLBACK_URL = SNAPSHOT_URL;

/** Prefer WS tick age when present; fall back to snapshot timestamp age. */
function snapshotDataAgeMs(json: MultiSnapshot, nowMs = Date.now()): number {
  const snapTs = json.timestamp ? new Date(json.timestamp).getTime() : nowMs;
  const snapshotAgeMs = Math.max(0, nowMs - snapTs);
  const tickAgeMs = typeof json.wsTickAgeMs === 'number' && json.wsTickAgeMs >= 0
    ? json.wsTickAgeMs
    : null;
  return tickAgeMs ?? snapshotAgeMs;
}

function latencyQuality(ms: number): StreamMetrics['connectionQuality'] {
  if (ms <= 0) return 'offline';
  if (ms < 80) return 'excellent';
  if (ms < 250) return 'good';
  return 'slow';
}

/** SSE is server-push — use payload data freshness, not JSON parse time (~0ms). */
function sseConnectionQuality(
  dataAgeMs: number,
  dataReady: boolean,
  transportAgeMs?: number,
  hasCachedData?: boolean,
): StreamMetrics['connectionQuality'] {
  const transportLimit = hasCachedData ? TRANSPORT_OFFLINE_MS : 45_000;
  const dataLimit = dataReady ? DATA_OFFLINE_MS : 45_000;
  const slowAfterMs = dataReady ? 15_000 : 10_000;
  const transportOk = transportAgeMs == null || transportAgeMs < transportLimit;

  if (!transportOk && transportAgeMs != null) {
    return 'slow';
  }
  if (!dataReady && dataAgeMs > dataLimit) return 'offline';
  if (dataAgeMs > dataLimit) return 'offline';
  if (dataAgeMs > slowAfterMs) return 'slow';
  if (dataAgeMs > 3_000) return 'slow';
  if (dataAgeMs > 1_000) return 'good';
  return 'excellent';
}

function sseDisplayLatencyMs(dataAgeMs: number, pollIntervalMs: number): number {
  const age = dataAgeMs > 0 ? dataAgeMs : pollIntervalMs;
  return stableLatencyMs(Math.max(25, Math.min(pollIntervalMs, age)));
}

/** Round-trip display — dampens jitter from ±few ms network variance */
function stableLatencyMs(ms: number): number {
  return Math.round(ms / 25) * 25;
}

const EMPTY_METRICS: StreamMetrics = {
  lastLatencyMs: 0,
  avgLatencyMs: 0,
  lastUpdatedAt: null,
  stalenessMs: 0,
  pollIntervalMs: POLL_MS,
  connectionQuality: 'offline',
  streamMode: SSE_ENABLED ? 'sse' : 'poll',
};

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function applySnapshot(
  json: MultiSnapshot,
  started: number,
  latencyHistory: React.MutableRefObject<number[]>,
  lastSuccessAt: React.MutableRefObject<Date | null>,
  lastSignature: React.MutableRefObject<string>,
  hasDataRef: React.MutableRefObject<boolean>,
  streamMode: StreamMetrics['streamMode'],
  pollIntervalMs: number,
  setData: (d: MultiSnapshot) => void,
  setError: (e: string | null) => void,
  setMetrics: React.Dispatch<React.SetStateAction<StreamMetrics>>,
) {
  if (!json || typeof json !== 'object' || !json.snapshots) {
    throw new Error('Invalid API response');
  }
  const now = new Date();
  lastSuccessAt.current = now;
  const elapsed = Math.round(performance.now() - started);
  const dataAgeMs = snapshotDataAgeMs(json, now.getTime());

  if (streamMode !== 'sse') {
    latencyHistory.current = [...latencyHistory.current.slice(-9), elapsed];
  }

  const sig = snapshotSignature(json);
  const dataChanged = sig !== lastSignature.current;
  if (dataChanged) {
    lastSignature.current = sig;
    setData(json);
    hasDataRef.current = true;
  }

  const isSse = streamMode === 'sse';
  const roundTripMs = Math.round(performance.now() - started);
  // HTTP poll via Vercel→EC2 inflates round-trip; prefer data freshness when payload is current.
  const pollFresh = !isSse && Boolean(json.dataReady) && dataAgeMs < 3000;
  const latency = isSse
    ? sseDisplayLatencyMs(dataAgeMs, pollIntervalMs)
    : pollFresh
      ? sseDisplayLatencyMs(dataAgeMs, pollIntervalMs)
      : stableLatencyMs(roundTripMs);
  const avgStable = isSse || pollFresh
    ? latency
    : stableLatencyMs(
        Math.round(
          latencyHistory.current.reduce((a, b) => a + b, 0) / latencyHistory.current.length,
        ),
      );
  const quality = isSse
    ? sseConnectionQuality(dataAgeMs, Boolean(json.dataReady), undefined, hasDataRef.current)
    : pollFresh
      ? sseConnectionQuality(dataAgeMs, Boolean(json.dataReady), undefined, hasDataRef.current)
      : latencyQuality(roundTripMs);
  setMetrics((prev) => {
    const staleBucket = Math.floor(dataAgeMs / 1000);
    const prevBucket = Math.floor(prev.stalenessMs / 1000);
    if (
      !dataChanged
      && prev.lastLatencyMs === latency
      && prev.avgLatencyMs === avgStable
      && prev.connectionQuality === quality
      && prev.streamMode === streamMode
      && staleBucket === prevBucket
      && prev.pollIntervalMs === pollIntervalMs
    ) {
      return prev;
    }
    return {
      lastLatencyMs: latency,
      avgLatencyMs: avgStable,
      lastUpdatedAt: now,
      stalenessMs: dataAgeMs,
      pollIntervalMs,
      connectionQuality: quality,
      streamMode,
    };
  });
  setError(null);
}

function applySseFreshness(
  json: MultiSnapshot,
  pollIntervalMs: number,
  setMetrics: React.Dispatch<React.SetStateAction<StreamMetrics>>,
) {
  const now = new Date();
  const dataAgeMs = snapshotDataAgeMs(json, now.getTime());
  const latency = sseDisplayLatencyMs(dataAgeMs, pollIntervalMs);
  const quality = sseConnectionQuality(dataAgeMs, Boolean(json.dataReady), undefined, true);
  setMetrics((prev) => {
    const staleBucket = Math.floor(dataAgeMs / 1000);
    const prevBucket = Math.floor(prev.stalenessMs / 1000);
    if (
      prev.lastLatencyMs === latency
      && prev.connectionQuality === quality
      && staleBucket === prevBucket
      && prev.streamMode === 'sse'
    ) {
      return prev;
    }
    return {
      ...prev,
      lastLatencyMs: latency,
      avgLatencyMs: latency,
      lastUpdatedAt: now,
      stalenessMs: dataAgeMs,
      connectionQuality: quality,
      streamMode: 'sse',
    };
  });
}

export function useMarketStream() {
  const [data, setData] = useState<MultiSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState<StreamMetrics>(EMPTY_METRICS);
  const latencyHistory = useRef<number[]>([]);
  const lastSuccessAt = useRef<Date | null>(null);
  const lastSignature = useRef('');
  const sseFailed = useRef(false);
  const lastSseApplyAt = useRef(0);
  const pollAbortRef = useRef<AbortController | null>(null);
  const hasDataRef = useRef(false);
  const lastTransportAt = useRef<Date | null>(null);

  const touchTransport = useCallback(() => {
    const now = new Date();
    lastSuccessAt.current = now;
    lastTransportAt.current = now;
  }, []);

  const pingHealth = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(4000) });
      if (res.ok) {
        touchTransport();
        return true;
      }
    } catch {
      // ignore
    }
    return false;
  }, [touchTransport]);

  const fetchSnapshot = useCallback(async (
    streamMode: StreamMetrics['streamMode'] = 'poll',
    options: { background?: boolean } = {},
  ) => {
    const background = options.background ?? false;
    if (!background) {
      pollAbortRef.current?.abort();
    }
    const ac = new AbortController();
    if (!background) {
      pollAbortRef.current = ac;
    }
    const started = performance.now();
    const urls = streamMode === 'sse' && SNAPSHOT_FALLBACK_URL !== SNAPSHOT_URL
      ? [SNAPSHOT_URL, SNAPSHOT_FALLBACK_URL]
      : [SNAPSHOT_URL];
    const maxAttempts = hasDataRef.current ? 3 : 4;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (attempt > 0) {
        await new Promise((r) => setTimeout(r, 500 * attempt));
        if (!background && ac.signal.aborted) return;
      }
      for (const url of urls) {
        try {
          const res = await fetch(url, { signal: background ? undefined : ac.signal });
          if (!res.ok) continue;
          const json = (await res.json()) as MultiSnapshot;
          applySnapshot(
            json,
            started,
            latencyHistory,
            lastSuccessAt,
            lastSignature,
            hasDataRef,
            streamMode,
            POLL_MS,
            setData,
            setError,
            setMetrics,
          );
          touchTransport();
          setLoading(false);
          return;
        } catch (e) {
          if (!background && e instanceof DOMException && e.name === 'AbortError') return;
        }
      }
    }
    const elapsed = Math.round(performance.now() - started);
    const transportAge = lastTransportAt.current
      ? Date.now() - lastTransportAt.current.getTime()
      : lastSuccessAt.current
        ? Date.now() - lastSuccessAt.current.getTime()
        : 0;
    if (hasDataRef.current) {
      const healthOk = await pingHealth();
      const offlineLimit = healthOk ? TRANSPORT_OFFLINE_MS : 45_000;
      setMetrics((prev) => ({
        ...prev,
        lastLatencyMs: elapsed,
        connectionQuality: transportAge > offlineLimit ? 'offline' : 'slow',
        streamMode: streamMode === 'sse' ? 'sse' : 'poll',
        stalenessMs: prev.stalenessMs || transportAge,
      }));
      setError(healthOk ? null : 'Snapshot refresh delayed — showing cached data');
    } else {
      setMetrics((prev) => ({
        ...prev,
        lastLatencyMs: elapsed,
        connectionQuality: 'offline',
        streamMode: streamMode === 'sse' ? 'sse' : 'poll',
        stalenessMs: prev.stalenessMs,
      }));
      setError('Cannot reach server');
    }
    setLoading(false);
  }, [pingHealth, touchTransport]);

  // Tick staleness between updates; fall back to HTTP poll when SSE goes quiet
  useEffect(() => {
    const id = setInterval(() => {
      const transportRef = lastTransportAt.current ?? lastSuccessAt.current;
      if (!transportRef) return;
      const transportAge = Date.now() - transportRef.getTime();
      setMetrics((prev) => {
        if (prev.streamMode === 'sse') {
          const limit = hasDataRef.current ? TRANSPORT_OFFLINE_MS : 45_000;
          if (transportAge <= limit) {
            return prev;
          }
          if (prev.connectionQuality === 'slow') {
            return prev;
          }
          return { ...prev, connectionQuality: 'slow' };
        }
        const staleBucket = Math.floor(transportAge / 1000);
        const prevBucket = Math.floor(prev.stalenessMs / 1000);
        const quality = prev.connectionQuality;
        const latency = prev.lastLatencyMs;
        if (prevBucket === staleBucket && quality === prev.connectionQuality && latency === prev.lastLatencyMs) {
          return prev;
        }
        return { ...prev, stalenessMs: transportAge, connectionQuality: quality, lastLatencyMs: latency };
      });
      if (SSE_ENABLED && transportAge > SSE_STALE_POLL_MS) {
        void fetchSnapshot('sse', { background: true });
      }
      if (transportAge > 5_000 && hasDataRef.current) {
        void pingHealth();
      }
    }, UI_TICK_MS);
    return () => clearInterval(id);
  }, [fetchSnapshot, pingHealth]);

  useEffect(() => {
    if (!SSE_ENABLED) {
      fetchSnapshot('poll');
      const id = setInterval(() => fetchSnapshot('poll'), POLL_MS);
      return () => clearInterval(id);
    }

    let es: EventSource | null = null;
    let pollId: ReturnType<typeof setInterval> | null = null;
    let retryId: ReturnType<typeof setTimeout> | null = null;
    let reconnectId: ReturnType<typeof setInterval> | null = null;
    let disposed = false;
    let retryMs = 1500;

    const startPollSupplement = () => {
      if (pollId) return;
      void fetchSnapshot('sse', { background: true });
      pollId = setInterval(() => {
        void fetchSnapshot('sse', { background: true });
      }, POLL_MS);
    };

    const stopPollSupplement = () => {
      if (pollId) {
        clearInterval(pollId);
        pollId = null;
      }
    };

    const connectSse = () => {
      if (disposed) return;
      es?.close();
      es = null;
      const url = `${STREAM_BASE}/api/market/stream`;
      es = new EventSource(url);
      let opened = false;

      es.onopen = () => {
        opened = true;
        retryMs = 1500;
        sseFailed.current = false;
        setLoading(false);
        touchTransport();
        setMetrics((prev) => ({
          ...prev,
          streamMode: 'sse',
          connectionQuality: prev.connectionQuality === 'offline' ? 'slow' : 'good',
        }));
      };

      es.onmessage = (ev) => {
        const now = performance.now();
        touchTransport();
        let json: MultiSnapshot;
        try {
          json = JSON.parse(ev.data) as MultiSnapshot;
        } catch {
          return;
        }
        const tickAge = typeof json.wsTickAgeMs === 'number' ? json.wsTickAgeMs : 0;
        if (now - lastSseApplyAt.current < SSE_MIN_INTERVAL_MS && tickAge < 2000) {
          applySseFreshness(json, POLL_MS, setMetrics);
          return;
        }
        lastSseApplyAt.current = now;
        const started = performance.now();
        try {
          applySnapshot(
            json,
            started,
            latencyHistory,
            lastSuccessAt,
            lastSignature,
            hasDataRef,
            'sse',
            POLL_MS,
            setData,
            setError,
            setMetrics,
          );
          touchTransport();
          setLoading(false);
        } catch (e) {
          setError(e instanceof Error ? e.message : 'Invalid stream payload');
        }
      };

      es.onerror = () => {
        es?.close();
        es = null;
        if (!disposed) {
          startPollSupplement();
          retryId = setTimeout(() => {
            if (!disposed) connectSse();
          }, retryMs);
          retryMs = Math.min(retryMs * 2, 15_000);
        }
        if (!opened) {
          setMetrics((prev) => ({
            ...prev,
            streamMode: 'sse',
            connectionQuality: 'slow',
          }));
        }
      };
    };

    startPollSupplement();
    connectSse();
    reconnectId = setInterval(() => {
      if (!disposed) connectSse();
    }, SSE_RECONNECT_MS);

    return () => {
      disposed = true;
      es?.close();
      stopPollSupplement();
      if (retryId) clearTimeout(retryId);
      if (reconnectId) clearInterval(reconnectId);
    };
  }, [fetchSnapshot, touchTransport]);

  return { data, error, loading, metrics, refetch: fetchSnapshot };
}

export function useDeploymentStatus() {
  const [status, setStatus] = useState<DeploymentStatus | null>(null);

  const refresh = useCallback(() => {
    fetchJson<DeploymentStatus>(`${API_BASE}/api/deployment/status`).then((json) => {
      if (json) setStatus(json);
    });
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60_000);
    return () => clearInterval(id);
  }, [refresh]);

  return status;
}

export function useTradeHistory(days = 14) {
  const [history, setHistory] = useState<TradeHistoryResponse | null>(null);

  useEffect(() => {
    fetchJson<TradeHistoryResponse>(`${API_BASE}/api/auto-trader/history?days=${days}`).then((json) => {
      if (json) setHistory(json);
    });
  }, [days]);

  return history;
}

export function useTradeLog(limit = 30) {
  const [log, setLog] = useState<TradeLogResponse | null>(null);

  const refresh = useCallback(() => {
    fetchJson<TradeLogResponse>(`${API_BASE}/api/auto-trader/log?limit=${limit}`).then((json) => {
      if (json) setLog(json);
    });
  }, [limit]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, [refresh]);

  return log;
}

export function useDeploymentReadiness() {
  const [readiness, setReadiness] = useState<DeploymentReadiness | null>(null);

  const refresh = useCallback(() => {
    fetchJson<DeploymentReadiness>(`${API_BASE}/api/deployment/readiness`).then((json) => {
      if (json) setReadiness(json);
    });
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  }, [refresh]);

  return readiness;
}

export function usePerformanceMilestone() {
  const [milestone, setMilestone] = useState<PerformanceMilestone | null>(null);

  const refresh = useCallback(() => {
    fetchJson<PerformanceMilestone>(`${API_BASE}/api/auto-trader/milestone`).then((json) => {
      if (json && typeof json.tradeCount === 'number' && json.checks) setMilestone(json);
    });
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10_000);
    return () => clearInterval(id);
  }, [refresh]);

  return milestone;
}

export function useWeeklyDashboard(days = 7) {
  const [dashboard, setDashboard] = useState<WeeklyDashboard | null>(null);

  const refresh = useCallback(() => {
    fetchJson<WeeklyDashboard>(`${API_BASE}/api/auto-trader/weekly-dashboard?days=${days}`).then((json) => {
      if (json && json.summary) setDashboard(json);
    });
  }, [days]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  return dashboard;
}

export async function stopTrading() {
  await fetch(`${API_BASE}/api/execution/stop`, { method: 'POST' });
}

export async function resumeTrading() {
  await fetch(`${API_BASE}/api/execution/resume`, { method: 'POST' });
}

export async function resetSession() {
  await fetch(`${API_BASE}/api/auto-trader/reset`, { method: 'POST' });
}

export function getLoginUrl() {
  return `${API_BASE}/api/upstox/login`;
}
