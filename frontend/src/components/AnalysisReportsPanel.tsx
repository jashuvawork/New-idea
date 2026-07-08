import { useCallback, useEffect, useState } from 'react';
import { Panel } from './Panel';

interface AnalysisReport {
  at?: string;
  ts?: string;
  lagScore?: number;
  summary?: string;
  source?: string;
  aiSummary?: { headline?: string; missedOpportunities?: string[]; priorityFixes?: string[] };
  aiError?: string;
  blockedRadarAlerts?: { symbol: string; side: string; strike: number; blockers?: string[] }[];
  highMovers?: { symbol: string; side: string; strike: number; dailyMovePct?: number; tier?: string }[];
}

interface MonitorStatus {
  enabled?: boolean;
  intervalSeconds?: number;
  lastRunAt?: string;
  lastLagScore?: number;
  lastError?: string;
  cycleCount?: number;
}

async function fetchStatus(): Promise<MonitorStatus> {
  const res = await fetch('/api/ai/analysis-monitor/status');
  if (res.status === 404) {
    return { enabled: false, cycleCount: 0 };
  }
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json() as Promise<MonitorStatus>;
}

async function fetchReports(): Promise<AnalysisReport[]> {
  const res = await fetch('/api/ai/analysis-reports?limit=8&days=3');
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`reports ${res.status}`);
  const data = await res.json();
  return (data.reports ?? []) as AnalysisReport[];
}

export function AnalysisReportsPanel({ pollMs = 60_000 }: { pollMs?: number }) {
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [reports, setReports] = useState<AnalysisReport[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [apiMissing, setApiMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [st, reps] = await Promise.all([fetchStatus(), fetchReports()]);
      setStatus(st);
      setReports(reps);
      setApiMissing(st.enabled === false && (st.cycleCount ?? 0) === 0 && reps.length === 0);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'load failed');
    }
  }, []);

  const forceRefresh = async () => {
    setRefreshing(true);
    try {
      const res = await fetch('/api/ai/analysis-monitor/refresh', { method: 'POST' });
      if (res.status === 404) {
        setApiMissing(true);
        setError('Analysis monitor not deployed — merge latest backend');
        return;
      }
      if (!res.ok) throw new Error(`refresh ${res.status}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);

  const latest = reports[0];
  const lag = latest?.lagScore ?? status?.lastLagScore ?? 0;
  const scoreTone =
    lag >= 60 ? 'text-nexus-red' : lag >= 30 ? 'text-nexus-yellow' : 'text-nexus-green';
  const badge = apiMissing ? 'SETUP' : status?.enabled ? 'LIVE' : 'OFF';

  return (
    <Panel
      title="AI Analysis Reports"
      badge={badge}
      badgeColor={apiMissing ? 'bg-nexus-yellow/90 text-black' : status?.enabled ? 'bg-purple-600/90' : 'bg-gray-700'}
    >
      <p className="text-[10px] text-nexus-muted mb-2 leading-relaxed">
        Interval audit of radar vs gates — stored every {status?.intervalSeconds ?? 120}s so missed rips are explainable later.
      </p>

      {apiMissing ? (
        <div className="text-[10px] text-nexus-yellow mb-2 p-2 rounded border border-nexus-yellow/40 bg-nexus-yellow/5">
          No stored reports yet. Deploy latest backend, then click Run now for the first cycle.
        </div>
      ) : null}

      <div className={`text-[11px] font-mono mb-2 ${scoreTone}`}>
        Lag score: {lag}/100 · cycles: {status?.cycleCount ?? 0}
      </div>

      {latest?.summary ? (
        <div className="text-[10px] text-white mb-2 p-2 rounded bg-black/30">{latest.summary}</div>
      ) : !apiMissing ? (
        <div className="text-[10px] text-nexus-muted mb-2 p-2 rounded bg-black/20">
          Waiting for first analysis cycle…
        </div>
      ) : null}

      {latest?.aiSummary?.headline ? (
        <div className="mb-2 p-2 rounded bg-purple-900/20 border border-purple-500/30 text-[10px]">
          <div className="text-purple-300 font-semibold mb-1">Latest AI audit</div>
          <div className="text-white">{latest.aiSummary.headline}</div>
        </div>
      ) : null}

      {latest?.highMovers && latest.highMovers.length > 0 ? (
        <div className="mb-2 text-[9px]">
          <div className="text-nexus-accent uppercase mb-1">High movers</div>
          {latest.highMovers.slice(0, 4).map((m, i) => (
            <div key={i} className="font-mono text-white">
              {m.symbol} {m.side} {m.strike} · {m.dailyMovePct?.toFixed?.(0) ?? m.dailyMovePct}% {m.tier}
            </div>
          ))}
        </div>
      ) : null}

      {latest?.blockedRadarAlerts && latest.blockedRadarAlerts.length > 0 ? (
        <div className="max-h-24 overflow-y-auto mb-2 text-[9px] space-y-1">
          {latest.blockedRadarAlerts.slice(0, 4).map((b, i) => (
            <div key={i} className="p-1 rounded border border-nexus-red/30 text-nexus-red font-mono">
              {b.symbol} {b.side} {b.strike}: {(b.blockers ?? []).join(' · ')}
            </div>
          ))}
        </div>
      ) : null}

      {reports.length > 1 ? (
        <div className="max-h-20 overflow-y-auto mb-2 text-[9px] text-gray-500">
          {reports.slice(1, 6).map((r, i) => (
            <div key={i} className="font-mono truncate">
              {(r.at ?? r.ts ?? '').slice(11, 19)} lag={r.lagScore} {r.source}
            </div>
          ))}
        </div>
      ) : null}

      {error || latest?.aiError || status?.lastError ? (
        <div className="text-[10px] text-nexus-red mb-2">
          {error ?? latest?.aiError ?? status?.lastError}
        </div>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={load}
          className="flex-1 text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white"
        >
          Reload history
        </button>
        <button
          type="button"
          onClick={forceRefresh}
          disabled={refreshing}
          className="flex-1 text-[10px] py-1.5 rounded border border-purple-500/50 text-purple-300 hover:bg-purple-900/20 disabled:opacity-50"
        >
          {refreshing ? 'Running…' : 'Run now'}
        </button>
      </div>
    </Panel>
  );
}
