import { useCallback, useEffect, useState } from 'react';
import { Panel } from './Panel';

interface EodScenario {
  id?: string;
  label: string;
  probability?: string;
  action?: string;
}

interface EodWatch {
  symbol: string;
  side: string;
  strikes?: string;
  reason?: string;
}

interface EodPlaybook {
  waiting?: boolean;
  generatedAt?: string;
  targetDate?: string;
  sessionDate?: string;
  summary?: string;
  bias?: string;
  confidence?: string;
  scenarios?: EodScenario[];
  watchlist?: EodWatch[];
  riskFlags?: string[];
  playbook?: string[];
  sessionPnlInr?: number;
  aiSummary?: {
    headline?: string;
    openPlan?: string;
    afternoonPlan?: string;
    priorityStrikes?: string[];
    avoid?: string[];
  };
  aiError?: string;
  source?: string;
}

interface EodStatus {
  enabled?: boolean;
  inEodWindow?: boolean;
  targetDate?: string;
  lastGeneratedAt?: string;
  lastBias?: string;
  hasPlaybook?: boolean;
}

const BIAS_TONE: Record<string, string> = {
  CALL: 'text-nexus-green',
  PUT: 'text-nexus-red',
  BOTH: 'text-nexus-yellow',
  STAND_ASIDE: 'text-gray-400',
};

export function EodTomorrowPlaybookPanel({ pollMs = 120_000 }: { pollMs?: number }) {
  const [playbook, setPlaybook] = useState<EodPlaybook | null>(null);
  const [status, setStatus] = useState<EodStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [pbRes, stRes] = await Promise.all([
        fetch('/api/playbook/tomorrow'),
        fetch('/api/playbook/tomorrow/status'),
      ]);
      if (pbRes.status === 404) {
        setPlaybook({ waiting: true, summary: 'EOD playbook API not deployed' });
      } else if (pbRes.ok) {
        setPlaybook(await pbRes.json());
      }
      if (stRes.ok) setStatus(await stRes.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'load failed');
    }
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const res = await fetch('/api/playbook/tomorrow/refresh', { method: 'POST' });
      if (!res.ok) throw new Error(`${res.status}`);
      setPlaybook(await res.json());
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

  const bias = playbook?.bias ?? status?.lastBias ?? '—';
  const waiting = playbook?.waiting && !playbook?.playbook?.length;

  return (
    <Panel
      title="Tomorrow EOD Playbook"
      badge={waiting ? 'PENDING' : bias}
      badgeColor={
        bias === 'PUT'
          ? 'bg-nexus-red/90'
          : bias === 'CALL'
            ? 'bg-nexus-green/90'
            : waiting
              ? 'bg-nexus-yellow/90 text-black'
              : 'bg-purple-600/90'
      }
    >
      <p className="text-[10px] text-nexus-muted mb-2 leading-relaxed">
        Next-session plan generated after 15:20 IST — scenarios, watchlist, risk flags for{' '}
        {playbook?.targetDate ?? status?.targetDate ?? 'next open'}.
      </p>

      {playbook?.summary ? (
        <div className="text-[10px] text-white mb-2 p-2 rounded bg-black/30">{playbook.summary}</div>
      ) : waiting ? (
        <div className="text-[10px] text-nexus-yellow mb-2 p-2 rounded border border-nexus-yellow/40 bg-nexus-yellow/5">
          {playbook?.summary ?? 'Waiting for EOD generation after market close…'}
        </div>
      ) : null}

      <div className={`text-[11px] font-mono mb-2 ${BIAS_TONE[bias] ?? 'text-white'}`}>
        Bias: {bias} · confidence {playbook?.confidence ?? '—'}
        {playbook?.sessionPnlInr != null ? ` · today PnL ₹${playbook.sessionPnlInr.toFixed(0)}` : ''}
      </div>

      {playbook?.aiSummary?.headline ? (
        <div className="mb-2 p-2 rounded bg-purple-900/20 border border-purple-500/30 text-[10px]">
          <div className="text-purple-300 font-semibold mb-1">AI tomorrow plan</div>
          <div className="text-white">{playbook.aiSummary.headline}</div>
          {playbook.aiSummary.openPlan ? (
            <div className="text-gray-300 mt-1">Open: {playbook.aiSummary.openPlan}</div>
          ) : null}
          {playbook.aiSummary.afternoonPlan ? (
            <div className="text-gray-300 mt-0.5">PM: {playbook.aiSummary.afternoonPlan}</div>
          ) : null}
        </div>
      ) : null}

      {playbook?.scenarios && playbook.scenarios.length > 0 ? (
        <div className="mb-2 text-[9px]">
          <div className="text-nexus-accent uppercase mb-1">Scenarios</div>
          {playbook.scenarios.map((s, i) => (
            <div key={s.id ?? i} className="p-1.5 mb-1 rounded border border-nexus-border/40 bg-black/20">
              <div className="text-white font-semibold">
                {s.label}
                {s.probability ? (
                  <span className="text-nexus-muted ml-1">({s.probability})</span>
                ) : null}
              </div>
              {s.action ? <div className="text-gray-400 mt-0.5">{s.action}</div> : null}
            </div>
          ))}
        </div>
      ) : null}

      {playbook?.watchlist && playbook.watchlist.length > 0 ? (
        <div className="mb-2 text-[9px]">
          <div className="text-nexus-accent uppercase mb-1">Watchlist</div>
          {playbook.watchlist.map((w, i) => (
            <div key={i} className="font-mono text-white mb-0.5">
              <span className={w.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                {w.symbol} {w.side}
              </span>
              <span className="text-nexus-muted"> · {w.strikes} — {w.reason}</span>
            </div>
          ))}
        </div>
      ) : null}

      {playbook?.riskFlags && playbook.riskFlags.length > 0 ? (
        <div className="mb-2 text-[9px]">
          <div className="text-nexus-red uppercase mb-1">Risk flags</div>
          {playbook.riskFlags.map((r, i) => (
            <div key={i} className="text-nexus-red font-mono">
              {r}
            </div>
          ))}
        </div>
      ) : null}

      {playbook?.playbook && playbook.playbook.length > 0 ? (
        <div className="max-h-24 overflow-y-auto mb-2 text-[9px] text-gray-300 space-y-0.5">
          {playbook.playbook.map((step, i) => (
            <div key={i}>• {step}</div>
          ))}
        </div>
      ) : null}

      {error || playbook?.aiError ? (
        <div className="text-[10px] text-nexus-red mb-2">{error ?? playbook?.aiError}</div>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={load}
          className="flex-1 text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white"
        >
          Reload
        </button>
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="flex-1 text-[10px] py-1.5 rounded border border-purple-500/50 text-purple-300 hover:bg-purple-900/20 disabled:opacity-50"
        >
          {refreshing ? 'Building…' : 'Generate now'}
        </button>
      </div>
    </Panel>
  );
}
