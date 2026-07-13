import { useCallback, useEffect, useState } from 'react';
import { Panel } from './Panel';

export interface SnapshotLagAnalysis {
  at?: string;
  lagScore?: number;
  summary?: string;
  windows?: Record<string, boolean>;
  misleadingLabels?: { field: string; issue: string; useInstead: string }[];
  explosionGaps?: {
    symbol: string;
    side: string;
    strike: number;
    tier: string;
    score: number;
    allDayExplosion?: boolean;
    blockers?: string[];
    wouldNeed?: string;
  }[];
  allDayExplosionAlerts?: { symbol: string; side: string; strike: number; score: number }[];
  bestCandidate?: { symbol: string; side: string; mode: string; score: number } | null;
}

async function fetchLag(): Promise<SnapshotLagAnalysis> {
  const res = await fetch('/api/ai/snapshot-analysis');
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<SnapshotLagAnalysis>;
}

export function SnapshotLagPanel({ pollMs = 20_000 }: { pollMs?: number }) {
  const [lag, setLag] = useState<SnapshotLagAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiSummary, setAiSummary] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchLag();
      setLag(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'lag fetch failed');
    }
  }, []);

  const runAi = async () => {
    setAiLoading(true);
    try {
      const res = await fetch('/api/ai/snapshot-analysis', { method: 'POST' });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setLag(data.rules ?? data);
      setAiSummary(data.aiSummary ?? null);
      setError(data.aiError ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI analysis failed');
    } finally {
      setAiLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [refresh, pollMs]);

  const score = lag?.lagScore ?? 0;
  const scoreTone =
    score >= 60 ? 'text-nexus-red' : score >= 30 ? 'text-nexus-yellow' : 'text-nexus-green';

  return (
    <Panel
      title="Snapshot Lag"
      badge={score >= 60 ? 'GAP' : score >= 30 ? 'WATCH' : 'OK'}
      badgeColor={score >= 60 ? 'bg-nexus-red/90' : score >= 30 ? 'bg-nexus-yellow/90 text-black' : 'bg-nexus-green/90'}
    >
      <p className="text-[10px] text-nexus-muted mb-2 leading-relaxed">
        Compares explosion radar vs entry gates — where monitoring sees rips the bot cannot take.
      </p>

      {lag?.summary ? (
        <div className="text-[10px] text-white mb-2 p-2 rounded bg-black/30">{lag.summary}</div>
      ) : null}

      <div className={`text-[11px] font-mono mb-2 ${scoreTone}`}>
        Lag score: {score}/100
      </div>

      {lag?.windows ? (
        <div className="flex flex-wrap gap-1 mb-2 text-[9px]">
          {Object.entries(lag.windows).map(([k, v]) => (
            <span
              key={k}
              className={`px-1 py-0.5 rounded border ${v ? 'border-nexus-green/40 text-nexus-green' : 'border-gray-700 text-gray-600'}`}
            >
              {k}
            </span>
          ))}
        </div>
      ) : null}

      {lag?.misleadingLabels && lag.misleadingLabels.length > 0 ? (
        <div className="mb-2 p-2 rounded border border-nexus-yellow/40 bg-nexus-yellow/5 text-[9px]">
          <div className="text-nexus-yellow font-semibold mb-1">Misleading UI</div>
          {lag.misleadingLabels.map((m, i) => (
            <div key={i} className="text-gray-300 mb-1">
              <span className="font-mono text-nexus-yellow">{m.field}</span>: {m.issue}
            </div>
          ))}
        </div>
      ) : null}

      {lag?.allDayExplosionAlerts && lag.allDayExplosionAlerts.length > 0 ? (
        <div className="mb-2 text-[9px]">
          <div className="text-nexus-accent uppercase mb-1">All-day explosions</div>
          {lag.allDayExplosionAlerts.map((a, i) => (
            <div key={i} className="font-mono text-white">
              {a.symbol} {a.side} {a.strike} · {a.score}
            </div>
          ))}
        </div>
      ) : null}

      {lag?.explosionGaps && lag.explosionGaps.length > 0 ? (
        <div className="max-h-32 overflow-y-auto space-y-1 mb-2 text-[9px]">
          {lag.explosionGaps.slice(0, 6).map((g, i) => (
            <div key={i} className="p-1 rounded border border-nexus-border/50">
              <span className={g.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                {g.symbol} {g.side} {g.strike}
              </span>
              <span className="text-nexus-muted ml-1">{g.tier} {g.score}</span>
              {g.blockers?.length ? (
                <div className="text-nexus-red font-mono">{g.blockers.join(' · ')}</div>
              ) : (
                <div className="text-nexus-green">tradeable</div>
              )}
            </div>
          ))}
        </div>
      ) : null}

      {aiSummary && typeof aiSummary.headline === 'string' ? (
        <div className="mb-2 p-2 rounded bg-purple-900/20 border border-purple-500/30 text-[10px]">
          <div className="text-purple-300 font-semibold mb-1">AI audit</div>
          <div className="text-white">{String(aiSummary.headline)}</div>
        </div>
      ) : null}

      {error ? <div className="text-[10px] text-nexus-red mb-2">{error}</div> : null}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={refresh}
          className="flex-1 text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white"
        >
          Refresh rules
        </button>
        <button
          type="button"
          onClick={runAi}
          disabled={aiLoading}
          className="flex-1 text-[10px] py-1.5 rounded border border-purple-500/50 text-purple-300 hover:bg-purple-900/20 disabled:opacity-50"
        >
          {aiLoading ? 'AI…' : 'AI audit'}
        </button>
      </div>
    </Panel>
  );
}
