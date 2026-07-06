import { useCallback, useEffect, useState } from 'react';
import { Panel } from './Panel';
import type { ComposerBrief, ComposerMonitorStatus } from '../types';

const BIAS_COLOR: Record<string, string> = {
  CALL: 'text-nexus-green',
  PUT: 'text-nexus-red',
  BOTH: 'text-nexus-yellow',
  STAND_ASIDE: 'text-gray-400',
};

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<T>;
}

export function ComposerMonitorPanel({ pollMs = 30_000 }: { pollMs?: number }) {
  const [status, setStatus] = useState<ComposerMonitorStatus | null>(null);
  const [brief, setBrief] = useState<ComposerBrief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, br] = await Promise.all([
        fetchJson<ComposerMonitorStatus>('/api/ai/composer/status'),
        fetchJson<ComposerBrief>('/api/ai/composer/brief').catch(() => null),
      ]);
      setStatus(st);
      setBrief(br);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'fetch failed');
    }
  }, []);

  const forceRefresh = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/ai/composer/refresh', { method: 'POST' });
      if (!res.ok) throw new Error(`${res.status}`);
      const br = (await res.json()) as ComposerBrief;
      setBrief(br);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'refresh failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [refresh, pollMs]);

  const apiOk = status?.apiConfigured && status?.apiPing?.ok;
  const source = brief?.source ?? '—';
  const bias = brief?.tradeBias ?? 'STAND_ASIDE';

  return (
    <Panel
      title="Composer Monitor"
      badge={apiOk ? 'Composer 2.5' : 'Rules'}
      badgeColor={apiOk ? 'bg-purple-600/90 text-white' : 'bg-gray-600/80 text-white'}
    >
      <p className="text-[10px] text-nexus-muted leading-relaxed mb-2">
        Advisory only — does not block orders. Reads regime, expiry, churn, and suggests CALL / PUT /
        BOTH / stand aside. Refreshes every {status?.intervalSeconds ?? 180}s during live market.
      </p>

      {status?.tradingBlockers && status.tradingBlockers.length > 0 ? (
        <div className="mb-2 p-2 rounded border border-nexus-red/40 bg-nexus-red/10 text-[10px]">
          <div className="text-nexus-red font-semibold uppercase mb-1">Trading blocked by engine</div>
          {status.tradingBlockers.map((b, i) => (
            <div key={`blocker-${i}`} className="text-white font-mono">
              {b.reason}
              {b.message ? ` — ${b.message}` : ''}
            </div>
          ))}
          <div className="text-nexus-muted mt-1 text-[9px]">
            Composer mirrors this — it does not cause the pause.
          </div>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1 mb-2 text-[9px]">
        <span
          className={`px-1.5 py-0.5 rounded border ${
            status?.enabled ? 'border-nexus-green/40 text-nexus-green' : 'border-gray-600 text-gray-500'
          }`}
        >
          Monitor {status?.enabled ? 'ON' : 'OFF'}
        </span>
        <span
          className={`px-1.5 py-0.5 rounded border ${
            apiOk ? 'border-purple-400/50 text-purple-300' : 'border-nexus-yellow/40 text-nexus-yellow'
          }`}
        >
          API {apiOk ? 'connected' : status?.apiConfigured ? 'ping fail' : 'no key'}
        </span>
        {brief?.standDown ? (
          <span className="px-1.5 py-0.5 rounded border border-nexus-yellow/50 text-nexus-yellow font-semibold">
            ADVISORY: STAND ASIDE
          </span>
        ) : null}
      </div>

      {error ? <div className="text-[10px] text-nexus-red mb-2">{error}</div> : null}

      {brief ? (
        <div className="space-y-2 text-[10px]">
          <div className="p-2 rounded bg-black/30">
            <div className="text-nexus-muted uppercase mb-0.5">Market read</div>
            <div className="text-white leading-relaxed">{brief.marketRead || '—'}</div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 rounded bg-black/30">
              <div className="text-nexus-muted uppercase mb-0.5">Bias</div>
              <div className={`font-bold font-mono ${BIAS_COLOR[bias] ?? 'text-white'}`}>{bias}</div>
              <div className="text-nexus-muted">{brief.confidence} confidence</div>
            </div>
            <div className="p-2 rounded bg-black/30">
              <div className="text-nexus-muted uppercase mb-0.5">Source</div>
              <div className="font-mono text-white">{source}</div>
              <div className="text-nexus-muted text-[9px]">{brief.at?.slice(11, 19)} IST</div>
            </div>
          </div>
          {brief.sessionPlan ? (
            <div className="p-2 rounded bg-black/30">
              <div className="text-nexus-muted uppercase mb-0.5">Session plan</div>
              <div className="text-nexus-accent">{brief.sessionPlan}</div>
            </div>
          ) : null}
          {brief.actions && brief.actions.length > 0 ? (
            <ul className="list-disc list-inside text-gray-300 space-y-0.5">
              {brief.actions.map((a, i) => (
                <li key={`act-${i}`}>{a}</li>
              ))}
            </ul>
          ) : null}
          {brief.risks && brief.risks.length > 0 ? (
            <div className="text-nexus-yellow font-mono text-[9px]">
              Risks: {brief.risks.join(' · ')}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="text-[10px] text-nexus-muted">Waiting for first brief…</div>
      )}

      <button
        type="button"
        onClick={forceRefresh}
        disabled={loading}
        className="mt-3 w-full text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white hover:border-nexus-accent disabled:opacity-50"
      >
        {loading ? 'Refreshing…' : 'Refresh now (Composer 2.5)'}
      </button>
    </Panel>
  );
}
