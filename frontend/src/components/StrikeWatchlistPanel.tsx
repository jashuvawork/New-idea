import { useCallback, useEffect, useMemo, useState } from 'react';
import { Panel } from './Panel';
import type { ExplosionAlert, RunnerWatchItem, SymbolSnapshot } from '../types';

type Side = 'CALL' | 'PUT';

export interface StrikeWatchRow {
  symbol: string;
  side: Side;
  strike: number;
  premium: number;
  score: number;
  tier: string;
  movePct: number;
  velocity3s?: number;
  source: string;
  priority: number;
  expiry?: string | null;
  atmStrike?: number | null;
}

const TIER_RANK: Record<string, number> = {
  ELITE: 4,
  EXPLODING: 3,
  BUILDING: 2,
  WATCH: 1,
  ATM: 0,
};

function priorityOf(score: number, tier: string, move: number): number {
  return score + (TIER_RANK[tier] ?? 0) * 8 + Math.min(40, Math.abs(move) * 0.15);
}

function fromAlerts(snap: SymbolSnapshot, side: Side, limit: number): StrikeWatchRow[] {
  const alerts = (snap.explosionAlerts || []) as ExplosionAlert[];
  const rows = alerts
    .filter((a) => String(a.side).toUpperCase() === side)
    .map((a) => {
      const tier = String(a.tier || 'WATCH').toUpperCase();
      const score = Number(a.explosionScore || 0);
      const move = Math.max(Number(a.dailyMovePct || 0), Number(a.peakMovePct || 0));
      return {
        symbol: snap.symbol,
        side,
        strike: Number(a.strike),
        premium: Number(a.premium || 0),
        score,
        tier,
        movePct: move,
        velocity3s: Number(a.velocity3s || 0),
        source: 'explosion_radar',
        priority: priorityOf(score, tier, move),
        expiry: snap.optionExpiry,
        atmStrike: snap.atmStrike,
      } satisfies StrikeWatchRow;
    })
    .filter((r) => r.strike > 0)
    .sort((a, b) => b.priority - a.priority);

  const out: StrikeWatchRow[] = [];
  const seen = new Set<number>();
  for (const r of rows) {
    if (seen.has(r.strike)) continue;
    seen.add(r.strike);
    out.push(r);
    if (out.length >= limit) break;
  }
  return out;
}

function fromRunners(snap: SymbolSnapshot, side: Side, limit: number, exclude: Set<number>): StrikeWatchRow[] {
  const runners = (snap.explosiveRunnerWatchlist || []) as RunnerWatchItem[];
  const rows = runners
    .filter((r) => String(r.side).toUpperCase() === side && !exclude.has(Number(r.strike)))
    .map((r) => {
      const score = Number(r.score || 0);
      const tier = r.elite ? 'ELITE' : score >= 45 ? 'EXPLODING' : 'BUILDING';
      const move = Number(r.premiumVelocityPct || 0);
      return {
        symbol: snap.symbol,
        side,
        strike: Number(r.strike),
        premium: Number(r.premium || 0),
        score,
        tier,
        movePct: move,
        velocity3s: move,
        source: 'runner_watchlist',
        priority: priorityOf(score, tier, move),
        expiry: snap.optionExpiry,
        atmStrike: snap.atmStrike,
      } satisfies StrikeWatchRow;
    })
    .sort((a, b) => b.priority - a.priority)
    .slice(0, limit);
  return rows;
}

function sideWatch(snap: SymbolSnapshot, side: Side, perSide: number): StrikeWatchRow[] {
  const primary = fromAlerts(snap, side, perSide);
  if (primary.length >= perSide) return primary;
  const exclude = new Set(primary.map((r) => r.strike));
  const extra = fromRunners(snap, side, perSide - primary.length, exclude);
  const merged = [...primary, ...extra];
  if (merged.length === 0 && snap.atmStrike) {
    return [{
      symbol: snap.symbol,
      side,
      strike: Number(snap.atmStrike),
      premium: 0,
      score: Number(snap.tradeQualityScore || 0),
      tier: 'ATM',
      movePct: 0,
      source: 'atm_anchor',
      priority: Number(snap.tradeQualityScore || 0),
      expiry: snap.optionExpiry,
      atmStrike: snap.atmStrike,
    }];
  }
  return merged;
}

function buildLiveWatchlist(snapshots: Record<string, SymbolSnapshot>, perSide = 3): StrikeWatchRow[] {
  const rows: StrikeWatchRow[] = [];
  for (const sym of ['NIFTY', 'SENSEX']) {
    const snap = snapshots[sym];
    if (!snap?.dataAvailable) continue;
    rows.push(...sideWatch(snap, 'CALL', perSide));
    rows.push(...sideWatch(snap, 'PUT', perSide));
  }
  return rows.sort((a, b) => b.priority - a.priority);
}

function flattenNextDay(strikeWatchlist: any): StrikeWatchRow[] {
  const queue = strikeWatchlist?.priorityQueue;
  if (Array.isArray(queue) && queue.length) {
    return queue
      .map((r: any) => ({
        symbol: String(r.symbol || ''),
        side: (String(r.side || 'CALL').toUpperCase() === 'PUT' ? 'PUT' : 'CALL') as Side,
        strike: Number(r.strike || 0),
        premium: Number(r.premium || 0),
        score: Number(r.score || 0),
        tier: String(r.tier || '—'),
        movePct: Number(r.movePct || 0),
        source: String(r.source || 'eod'),
        priority: Number(r.priority || 0),
        expiry: r.expiry ?? null,
        atmStrike: r.atmStrike ?? null,
      }))
      .filter((r: StrikeWatchRow) => r.strike > 0);
  }
  const rows: StrikeWatchRow[] = [];
  for (const idx of strikeWatchlist?.indexes || []) {
    for (const r of idx.calls || []) {
      rows.push({
        symbol: idx.symbol,
        side: 'CALL',
        strike: Number(r.strike || 0),
        premium: Number(r.premium || 0),
        score: Number(r.score || 0),
        tier: String(r.tier || '—'),
        movePct: Number(r.movePct || 0),
        source: String(r.source || 'eod'),
        priority: Number(r.priority || 0),
        expiry: idx.optionExpiry,
        atmStrike: idx.atmStrike,
      });
    }
    for (const r of idx.puts || []) {
      rows.push({
        symbol: idx.symbol,
        side: 'PUT',
        strike: Number(r.strike || 0),
        premium: Number(r.premium || 0),
        score: Number(r.score || 0),
        tier: String(r.tier || '—'),
        movePct: Number(r.movePct || 0),
        source: String(r.source || 'eod'),
        priority: Number(r.priority || 0),
        expiry: idx.optionExpiry,
        atmStrike: idx.atmStrike,
      });
    }
  }
  return rows.filter((r) => r.strike > 0).sort((a, b) => b.priority - a.priority);
}

const TIER_COLOR: Record<string, string> = {
  ELITE: 'text-nexus-yellow',
  EXPLODING: 'text-nexus-accent',
  BUILDING: 'text-gray-300',
  WATCH: 'text-nexus-muted',
  ATM: 'text-nexus-muted',
};

export function StrikeWatchlistPanel({
  snapshots,
}: {
  snapshots: Record<string, SymbolSnapshot>;
}) {
  const liveRows = useMemo(() => buildLiveWatchlist(snapshots, 3), [snapshots]);
  const [nextDayRows, setNextDayRows] = useState<StrikeWatchRow[]>([]);
  const [targetDate, setTargetDate] = useState<string | null>(null);

  const loadNextDay = useCallback(async () => {
    try {
      const res = await fetch('/api/playbook/tomorrow');
      if (!res.ok) return;
      const pb = await res.json();
      setTargetDate(pb?.targetDate ?? null);
      setNextDayRows(flattenNextDay(pb?.strikeWatchlist));
    } catch {
      /* optional until EOD generate */
    }
  }, []);

  useEffect(() => {
    loadNextDay();
    const id = setInterval(loadNextDay, 120_000);
    return () => clearInterval(id);
  }, [loadNextDay]);

  const showNext = nextDayRows.length > 0;

  const byIndex = useMemo(() => {
    const map: Record<string, { calls: StrikeWatchRow[]; puts: StrikeWatchRow[] }> = {
      NIFTY: { calls: [], puts: [] },
      SENSEX: { calls: [], puts: [] },
    };
    for (const r of liveRows) {
      const bucket = map[r.symbol] || (map[r.symbol] = { calls: [], puts: [] });
      if (r.side === 'CALL') bucket.calls.push(r);
      else bucket.puts.push(r);
    }
    return map;
  }, [liveRows]);

  return (
    <Panel
      title="Strike Watchlist · CE / PE"
      badge={showNext ? `LIVE + ${targetDate ?? 'NEXT'}` : 'LIVE'}
      badgeColor="bg-nexus-accent/90"
    >
      <p className="text-[10px] text-nexus-muted mb-2 leading-relaxed">
        Priority CE and PE strikes for both indexes — trade radar first, next-day seed from EOD playbook.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
        {(['NIFTY', 'SENSEX'] as const).map((sym) => {
          const block = byIndex[sym];
          const snap = snapshots[sym];
          return (
            <div key={sym} className="rounded border border-nexus-border/50 bg-black/25 p-2">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold text-white tracking-wide">{sym}</span>
                <span className="text-[9px] font-mono text-nexus-muted">
                  spot {snap?.spot?.toFixed?.(0) ?? '—'} · ATM {snap?.atmStrike ?? '—'}
                  {snap?.optionExpiry ? ` · exp ${snap.optionExpiry}` : ''}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <SideTable label="CE" rows={block?.calls || []} tone="text-nexus-green" />
                <SideTable label="PE" rows={block?.puts || []} tone="text-nexus-red" />
              </div>
            </div>
          );
        })}
      </div>

      <div className="text-[9px] text-nexus-accent uppercase mb-1">Priority queue</div>
      <div className="max-h-36 overflow-y-auto">
        <table className="w-full text-[10px] font-mono">
          <thead>
            <tr className="text-nexus-muted border-b border-nexus-border">
              <th className="text-left py-1">#</th>
              <th className="text-left">Index</th>
              <th className="text-left">Side</th>
              <th className="text-right">Strike</th>
              <th className="text-right">₹</th>
              <th className="text-left">Tier</th>
              <th className="text-right">Score</th>
              <th className="text-right">Move%</th>
            </tr>
          </thead>
          <tbody>
            {liveRows.slice(0, 12).map((r, i) => (
              <tr key={`${r.symbol}-${r.side}-${r.strike}-${i}`} className="border-b border-nexus-border/40">
                <td className="py-1 text-nexus-muted">{i + 1}</td>
                <td>{r.symbol}</td>
                <td className={r.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>{r.side === 'CALL' ? 'CE' : 'PE'}</td>
                <td className="text-right text-white">{r.strike}</td>
                <td className="text-right">{r.premium > 0 ? r.premium.toFixed(1) : '—'}</td>
                <td className={TIER_COLOR[r.tier] || 'text-white'}>{r.tier}</td>
                <td className="text-right">{r.score.toFixed(0)}</td>
                <td className="text-right text-nexus-accent">{r.movePct ? r.movePct.toFixed(0) : '—'}</td>
              </tr>
            ))}
            {liveRows.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-2 text-nexus-muted">Waiting for live CE/PE radar…</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {showNext ? (
        <div className="mt-3 pt-2 border-t border-nexus-border/50">
          <div className="text-[9px] text-purple-300 uppercase mb-1">
            Next-day watchlist {targetDate ? `· ${targetDate}` : ''}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5 text-[10px] font-mono">
            {nextDayRows.slice(0, 8).map((r, i) => (
              <div key={`nd-${i}`} className="rounded bg-purple-900/20 border border-purple-500/30 px-1.5 py-1">
                <span className="text-white">{r.symbol}</span>{' '}
                <span className={r.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                  {r.side === 'CALL' ? 'CE' : 'PE'}
                </span>{' '}
                <span className="text-white">{r.strike}</span>
                {r.tier ? <span className="text-nexus-muted"> · {r.tier}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function SideTable({
  label,
  rows,
  tone,
}: {
  label: string;
  rows: StrikeWatchRow[];
  tone: string;
}) {
  return (
    <div>
      <div className={`text-[9px] uppercase mb-0.5 ${tone}`}>{label}</div>
      {rows.length === 0 ? (
        <div className="text-[9px] text-nexus-muted">—</div>
      ) : (
        rows.map((r) => (
          <div key={`${label}-${r.strike}`} className="text-[10px] font-mono leading-relaxed">
            <span className="text-white">{r.strike}</span>
            <span className="text-nexus-muted"> · </span>
            <span className={TIER_COLOR[r.tier] || 'text-white'}>{r.tier}</span>
            {r.premium > 0 ? <span className="text-nexus-muted"> · ₹{r.premium.toFixed(0)}</span> : null}
          </div>
        ))
      )}
    </div>
  );
}
