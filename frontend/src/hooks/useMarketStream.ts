import { useCallback, useEffect, useRef, useState } from 'react';
import type { DeploymentReadiness, DeploymentStatus, MultiSnapshot, PerformanceMilestone, StreamMetrics, TradeHistoryResponse, TradeLogResponse } from '../types';

// Production: always use same-origin /api (Vercel rewrites → EC2 backend)
// Dev: vite proxy handles /api → localhost:8000
const API_BASE = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_URL || '');
const POLL_MS = Number(import.meta.env.VITE_POLL_MS || 3000);

function latencyQuality(ms: number): StreamMetrics['connectionQuality'] {
  if (ms <= 0) return 'offline';
  if (ms < 400) return 'excellent';
  if (ms < 1200) return 'good';
  return 'slow';
}

const EMPTY_METRICS: StreamMetrics = {
  lastLatencyMs: 0,
  avgLatencyMs: 0,
  lastUpdatedAt: null,
  stalenessMs: 0,
  pollIntervalMs: POLL_MS,
  connectionQuality: 'offline',
};

export function useMarketStream() {
  const [data, setData] = useState<MultiSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState<StreamMetrics>(EMPTY_METRICS);
  const latencyHistory = useRef<number[]>([]);
  const lastSuccessAt = useRef<Date | null>(null);

  const fetchSnapshot = useCallback(async () => {
    const started = performance.now();
    try {
      const res = await fetch(`${API_BASE}/api/market/snapshots`);
      const elapsed = Math.round(performance.now() - started);
      if (!res.ok) throw new Error(`API ${res.status}`);

      const json = (await res.json()) as MultiSnapshot;
      if (!json || typeof json !== 'object' || !json.snapshots) {
        throw new Error('Invalid API response');
      }
      const now = new Date();
      lastSuccessAt.current = now;

      latencyHistory.current = [...latencyHistory.current.slice(-9), elapsed];
      const avg = Math.round(
        latencyHistory.current.reduce((a, b) => a + b, 0) / latencyHistory.current.length,
      );

      setMetrics({
        lastLatencyMs: elapsed,
        avgLatencyMs: avg,
        lastUpdatedAt: now,
        stalenessMs: 0,
        pollIntervalMs: POLL_MS,
        connectionQuality: latencyQuality(elapsed),
      });
      setData(json);
      setError(null);
    } catch (e) {
      const elapsed = Math.round(performance.now() - started);
      setMetrics((prev) => ({
        ...prev,
        lastLatencyMs: elapsed,
        connectionQuality: 'offline',
        stalenessMs: lastSuccessAt.current
          ? Date.now() - lastSuccessAt.current.getTime()
          : prev.stalenessMs,
      }));
      setError(e instanceof Error ? e.message : 'Connection failed');
    } finally {
      setLoading(false);
    }
  }, []);

  // Tick staleness between polls so UI shows aging data
  useEffect(() => {
    const id = setInterval(() => {
      if (!lastSuccessAt.current) return;
      setMetrics((prev) => ({
        ...prev,
        stalenessMs: Date.now() - lastSuccessAt.current!.getTime(),
      }));
    }, 500);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    fetchSnapshot();
    const id = setInterval(fetchSnapshot, POLL_MS);
    return () => clearInterval(id);
  }, [fetchSnapshot]);

  return { data, error, loading, metrics, refetch: fetchSnapshot };
}

export function useDeploymentStatus() {
  const [status, setStatus] = useState<DeploymentStatus | null>(null);

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/api/deployment/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => {});
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
    fetch(`${API_BASE}/api/auto-trader/history?days=${days}`)
      .then((r) => r.json())
      .then(setHistory)
      .catch(() => {});
  }, [days]);

  return history;
}

export function useTradeLog(limit = 30) {
  const [log, setLog] = useState<TradeLogResponse | null>(null);

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/api/auto-trader/log?limit=${limit}`)
      .then((r) => r.json())
      .then(setLog)
      .catch(() => {});
  }, [limit]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  return log;
}

export function useDeploymentReadiness() {
  const [readiness, setReadiness] = useState<DeploymentReadiness | null>(null);

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/api/deployment/readiness`)
      .then((r) => r.json())
      .then(setReadiness)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  return readiness;
}

export function usePerformanceMilestone() {
  const [milestone, setMilestone] = useState<PerformanceMilestone | null>(null);

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/api/auto-trader/milestone`)
      .then((r) => r.json())
      .then(setMilestone)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
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
