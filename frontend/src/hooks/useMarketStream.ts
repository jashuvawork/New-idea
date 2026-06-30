import { useCallback, useEffect, useRef, useState } from 'react';
import type { DeploymentReadiness, DeploymentStatus, MultiSnapshot, PerformanceMilestone, StreamMetrics, TradeHistoryResponse, TradeLogResponse } from '../types';
import { snapshotSignature } from './snapshotSignature';

// Production: always use same-origin /api (Vercel rewrites → EC2 backend)
// Dev: vite proxy handles /api → localhost:8000
const API_BASE = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_URL || '');
const POLL_MS = Number(import.meta.env.VITE_POLL_MS || 500);
const UI_TICK_MS = Math.max(POLL_MS, 250);
const SSE_MIN_INTERVAL_MS = Math.max(Number(import.meta.env.VITE_SSE_THROTTLE_MS || 100), 50);
const SSE_ENABLED = import.meta.env.VITE_SSE_ENABLED !== 'false';

function latencyQuality(ms: number): StreamMetrics['connectionQuality'] {
  if (ms <= 0) return 'offline';
  if (ms < 80) return 'excellent';
  if (ms < 250) return 'good';
  return 'slow';
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
  const snapTs = json.timestamp ? new Date(json.timestamp).getTime() : now.getTime();
  const dataAgeMs = Math.max(0, now.getTime() - snapTs);

  latencyHistory.current = [...latencyHistory.current.slice(-9), elapsed];
  const avg = Math.round(
    latencyHistory.current.reduce((a, b) => a + b, 0) / latencyHistory.current.length,
  );

  const sig = snapshotSignature(json);
  const dataChanged = sig !== lastSignature.current;
  if (dataChanged) {
    lastSignature.current = sig;
    setData(json);
  }

  const latency = stableLatencyMs(elapsed);
  const avgStable = stableLatencyMs(avg);
  setMetrics((prev) => {
    const quality = latencyQuality(elapsed);
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
      lastUpdatedAt: dataChanged ? now : prev.lastUpdatedAt,
      stalenessMs: dataAgeMs,
      pollIntervalMs,
      connectionQuality: quality,
      streamMode,
    };
  });
  setError(null);
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

  const fetchSnapshot = useCallback(async () => {
    const started = performance.now();
    try {
      const res = await fetch(`${API_BASE}/api/market/snapshots`);
      const elapsed = Math.round(performance.now() - started);
      if (!res.ok) throw new Error(`API ${res.status}`);

      const json = (await res.json()) as MultiSnapshot;
      applySnapshot(
        json,
        started,
        latencyHistory,
        lastSuccessAt,
        lastSignature,
        'poll',
        POLL_MS,
        setData,
        setError,
        setMetrics,
      );
      void elapsed;
    } catch (e) {
      const elapsed = Math.round(performance.now() - started);
      setMetrics((prev) => ({
        ...prev,
        lastLatencyMs: elapsed,
        connectionQuality: 'offline',
        streamMode: 'poll',
        stalenessMs: lastSuccessAt.current
          ? Date.now() - lastSuccessAt.current.getTime()
          : prev.stalenessMs,
      }));
      setError(e instanceof Error ? e.message : 'Connection failed');
    } finally {
      setLoading(false);
    }
  }, []);

  // Tick staleness between updates; fall back to HTTP poll when SSE goes quiet
  useEffect(() => {
    const id = setInterval(() => {
      if (!lastSuccessAt.current) return;
      const stale = Date.now() - lastSuccessAt.current.getTime();
      const staleBucket = Math.floor(stale / 1000);
      setMetrics((prev) => {
        const prevBucket = Math.floor(prev.stalenessMs / 1000);
        const quality =
          prev.streamMode === 'sse' && stale > 8000
            ? (stale > 15_000 ? 'offline' : 'slow')
            : prev.connectionQuality;
        if (prevBucket === staleBucket && quality === prev.connectionQuality) {
          return prev;
        }
        return { ...prev, stalenessMs: stale, connectionQuality: quality };
      });
      if (SSE_ENABLED && !sseFailed.current && stale > 4000) {
        void fetchSnapshot();
      }
    }, UI_TICK_MS);
    return () => clearInterval(id);
  }, [fetchSnapshot]);

  useEffect(() => {
    if (!SSE_ENABLED || sseFailed.current) {
      fetchSnapshot();
      const id = setInterval(fetchSnapshot, POLL_MS);
      return () => clearInterval(id);
    }

    const url = `${API_BASE}/api/market/stream`;
    const es = new EventSource(url);
    let opened = false;
    let pollId: ReturnType<typeof setInterval> | null = null;

    es.onopen = () => {
      opened = true;
      setLoading(false);
      setMetrics((prev) => (
        prev.streamMode === 'sse' && prev.connectionQuality === 'good'
          ? prev
          : { ...prev, streamMode: 'sse', connectionQuality: 'good' }
      ));
    };

    es.onmessage = (ev) => {
      const now = performance.now();
      if (now - lastSseApplyAt.current < SSE_MIN_INTERVAL_MS) {
        return;
      }
      lastSseApplyAt.current = now;
      const started = performance.now();
      try {
        const json = JSON.parse(ev.data) as MultiSnapshot;
        applySnapshot(
          json,
          started,
          latencyHistory,
          lastSuccessAt,
          lastSignature,
          'sse',
          POLL_MS,
          setData,
          setError,
          setMetrics,
        );
        setLoading(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Invalid stream payload');
      }
    };

    es.onerror = () => {
      es.close();
      if (!opened) {
        sseFailed.current = true;
        setMetrics((prev) => ({ ...prev, streamMode: 'poll' }));
        fetchSnapshot();
        pollId = setInterval(fetchSnapshot, POLL_MS);
        return;
      }
      sseFailed.current = true;
      setMetrics((prev) => ({
        ...prev,
        streamMode: 'poll',
        connectionQuality: prev.stalenessMs > 15_000 ? 'offline' : 'slow',
      }));
      fetchSnapshot();
      pollId = setInterval(fetchSnapshot, POLL_MS);
    };

    return () => {
      es.close();
      if (pollId) clearInterval(pollId);
    };
  }, [fetchSnapshot]);

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
