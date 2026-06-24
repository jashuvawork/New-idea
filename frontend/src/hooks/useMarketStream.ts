import { useCallback, useEffect, useState } from 'react';
import type { DeploymentStatus, MultiSnapshot } from '../types';

const API_BASE = import.meta.env.VITE_API_URL || '';
const POLL_MS = Number(import.meta.env.VITE_POLL_MS || 3000);

export function useMarketStream() {
  const [data, setData] = useState<MultiSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSnapshot = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/market/snapshots`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshot();
    const id = setInterval(fetchSnapshot, POLL_MS);
    return () => clearInterval(id);
  }, [fetchSnapshot]);

  return { data, error, loading, refetch: fetchSnapshot };
}

export function useDeploymentStatus() {
  const [status, setStatus] = useState<DeploymentStatus | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/deployment/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => {});
  }, []);

  return status;
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
