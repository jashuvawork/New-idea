import { useCallback, useEffect, useState } from 'react';
import { Panel } from './Panel';

interface GateRow {
  gate: string;
  passed: boolean;
  detail?: string;
  fix?: string;
}

interface MissedRow {
  symbol: string;
  side: string;
  strike: number;
  tier: string;
  score: number;
  dailyMovePct?: number;
  premium?: number;
  primaryBlocker?: string;
  blockers?: string[];
  gates?: GateRow[];
  sortScore?: number;
  rankFloor?: number;
  fix?: string;
  wouldPass?: boolean;
  allDayExplosion?: boolean;
  volumeAwaken?: boolean;
}

interface MissedTradeReport {
  at?: string;
  summary?: string;
  entryPolicy?: string;
  badDayMinRank?: number;
  worstDayBreakoutMinRank?: number;
  bestTradesMinRank?: number;
  missedCount?: number;
  passCount?: number;
  missed?: MissedRow[];
  wouldPass?: MissedRow[];
  bestCandidate?: { symbol: string; side: string; mode: string; score: number; strike: number } | null;
  sessionBlocks?: { reason?: string; message?: string }[];
  dataIssues?: { symbol: string; error?: string }[];
}

const GATE_LABELS: Record<string, string> = {
  radar: 'Radar',
  tradeable_tier: 'Tradeable tier',
  premium_band: 'Premium band',
  explosion_score: 'Explosion score',
  symbol_tqs: 'Symbol TQS',
  chart_alignment: 'Chart align',
  capture_window: 'Capture window',
  pretrade: 'Pretrade',
  worst_day: 'Worst day',
  bad_day: 'Bad day',
  rank_floor: 'Rank floor',
  execution_chart: 'Exec chart',
};

async function fetchReport(): Promise<MissedTradeReport> {
  const res = await fetch('/api/ai/missed-trades');
  if (res.status === 404) {
    return { summary: 'Missed-trade API not deployed — redeploy EC2 backend', missed: [] };
  }
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<MissedTradeReport>;
}

export function MissedTradeExplainerPanel({ pollMs = 15_000 }: { pollMs?: number }) {
  const [data, setData] = useState<MissedTradeReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetchReport());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'load failed');
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);

  const missed = data?.missed ?? [];
  const badge =
    (data?.missedCount ?? 0) > 0 ? `${data?.missedCount} MISSED` : (data?.passCount ?? 0) > 0 ? 'OK' : '—';

  return (
    <Panel
      title="Missed Trade Explainer"
      badge={badge}
      badgeColor={(data?.missedCount ?? 0) > 0 ? 'bg-nexus-red/90' : 'bg-nexus-green/90'}
    >
      <p className="text-[10px] text-nexus-muted mb-2 leading-relaxed">
        Gate-by-gate audit — why each radar alert did or did not become a trade.
      </p>

      {data?.summary ? (
        <div className="text-[10px] text-white mb-2 p-2 rounded bg-black/30">{data.summary}</div>
      ) : null}

      <div className="flex flex-wrap gap-2 mb-2 text-[9px] font-mono text-nexus-muted">
        {data?.entryPolicy ? <span>policy {data.entryPolicy}</span> : null}
        {data?.badDayMinRank != null ? <span>bad-day floor {data.badDayMinRank}</span> : null}
        {data?.worstDayBreakoutMinRank != null ? <span>breakout {data.worstDayBreakoutMinRank}</span> : null}
        {data?.bestTradesMinRank != null ? <span>best {data.bestTradesMinRank}</span> : null}
      </div>

      {data?.sessionBlocks?.length ? (
        <div className="mb-2 p-1.5 rounded border border-nexus-red/40 text-[9px] text-nexus-red">
          Session: {data.sessionBlocks[0].reason} — {data.sessionBlocks[0].message}
        </div>
      ) : null}

      {data?.dataIssues?.length ? (
        <div className="mb-2 p-1.5 rounded border border-nexus-yellow/40 text-[9px] text-nexus-yellow">
          Data: {data.dataIssues.map((d) => `${d.symbol} ${d.error}`).join(' · ')}
        </div>
      ) : null}

      <div className="max-h-56 overflow-y-auto space-y-1">
        {missed.length === 0 ? (
          <p className="text-[10px] text-nexus-muted py-2">No blocked radar alerts — or waiting for data</p>
        ) : (
          missed.slice(0, 10).map((row) => {
            const key = `${row.symbol}-${row.side}-${row.strike}`;
            const open = expanded === key;
            return (
              <div key={key} className="p-1.5 rounded border border-nexus-border/50 text-[10px]">
                <button
                  type="button"
                  className="w-full text-left"
                  onClick={() => setExpanded(open ? null : key)}
                >
                  <div className="flex justify-between gap-2">
                    <span className={row.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                      {row.symbol} {row.side} {row.strike}
                    </span>
                    <span className="text-nexus-muted shrink-0">
                      {row.tier} {row.score?.toFixed(0)}
                      {row.dailyMovePct != null && row.dailyMovePct > 0
                        ? ` +${row.dailyMovePct.toFixed(0)}%`
                        : ''}
                    </span>
                  </div>
                  <div className="text-[9px] text-nexus-red font-mono mt-0.5">
                    {row.primaryBlocker}
                    {row.rankFloor != null && row.sortScore != null
                      ? ` · sort ${row.sortScore.toFixed(0)} < floor ${row.rankFloor.toFixed(0)}`
                      : ''}
                  </div>
                  {row.fix ? <div className="text-[8px] text-nexus-yellow mt-0.5">{row.fix}</div> : null}
                </button>
                {open && row.gates ? (
                  <div className="mt-1 pt-1 border-t border-nexus-border/30 space-y-0.5">
                    {row.gates.map((g) => (
                      <div
                        key={g.gate}
                        className={`text-[8px] font-mono flex justify-between gap-2 ${g.passed ? 'text-nexus-green' : 'text-nexus-red'}`}
                      >
                        <span>{GATE_LABELS[g.gate] ?? g.gate}</span>
                        <span className="text-right truncate text-gray-400">{g.detail}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>

      {data?.wouldPass && data.wouldPass.length > 0 ? (
        <div className="mt-2 text-[9px]">
          <div className="text-nexus-green uppercase mb-1">Would pass gates ({data.passCount})</div>
          {data.wouldPass.slice(0, 3).map((row, i) => (
            <div key={i} className="font-mono text-gray-300">
              {row.symbol} {row.side} {row.strike} sort={row.sortScore?.toFixed(0)}
            </div>
          ))}
        </div>
      ) : null}

      {error ? <div className="text-[10px] text-nexus-red mt-2">{error}</div> : null}

      <button
        type="button"
        onClick={load}
        className="w-full mt-2 text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white"
      >
        Refresh gate audit
      </button>
    </Panel>
  );
}
