import { useEffect, useState } from 'react';
import { Panel } from './Panel';
import type {
  MarketNewsResponse,
  MultiSnapshot,
  NewsAggregate,
  NewsItem,
  TradeHistoryResponse,
  TradeLogResponse,
} from '../types';

const NEWS_POLL_MS = 5 * 60 * 1000; // match backend NEWS_CACHE_SECONDS (5 min)

export function TradeJournal({
  data,
  history,
  tradeLog,
}: {
  data: MultiSnapshot;
  history: TradeHistoryResponse | null;
  tradeLog?: TradeLogResponse | null;
}) {
  const sessionClosed = data.autoTrader.closedPaperTrades || [];
  const sessionOpen = data.autoTrader.openPaperTrades || [];
  const archived = history?.days?.filter((d) => d.tradeCount > 0) || [];
  const logEntries = tradeLog?.entries?.filter((e) => e.event === 'TRADE_OPENED' || e.event === 'TRADE_CLOSED') || [];

  return (
    <Panel
      title="Trade Journal"
      badge={`${sessionClosed.length} closed · ${sessionOpen.length} open`}
    >
      {history?.logFile && (
        <div className="mb-2 text-[9px] text-nexus-muted font-mono truncate" title={history.logFile}>
          Log: {history.logFile.split('/').slice(-2).join('/')}
          {history.logSizeBytes != null && ` (${(history.logSizeBytes / 1024).toFixed(1)} KB)`}
        </div>
      )}

      {sessionOpen.length > 0 && (
        <div className="mb-2">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Open positions</div>
          <div className="max-h-20 overflow-y-auto space-y-1">
            {sessionOpen.map((t) => (
              <TradeRow key={t.id} trade={t} open />
            ))}
          </div>
        </div>
      )}

      {sessionClosed.length === 0 && archived.length === 0 && logEntries.length === 0 ? (
        <p className="text-xs text-nexus-muted text-center py-3">
          No trades yet — each paper/live trade is appended to trades.log
        </p>
      ) : (
        <div className="space-y-2">
          {sessionClosed.length > 0 && (
            <div>
              <div className="text-[10px] text-nexus-muted uppercase mb-1">Today (session)</div>
              <div className="max-h-28 overflow-y-auto space-y-1">
                {[...sessionClosed].reverse().slice(0, 8).map((t) => (
                  <TradeRow key={t.id} trade={t} />
                ))}
              </div>
            </div>
          )}

          {logEntries.length > 0 && (
            <div className="pt-2 border-t border-nexus-border/50">
              <div className="text-[10px] text-nexus-muted uppercase mb-1">Recent log events</div>
              <div className="max-h-24 overflow-y-auto space-y-1">
                {logEntries.slice(0, 6).map((e, i) => (
                  <LogEventRow key={`${e.ts}-${i}`} entry={e} />
                ))}
              </div>
            </div>
          )}

          {archived.length > 0 && (
            <div className="pt-2 border-t border-nexus-border/50">
              <div className="text-[10px] text-nexus-muted uppercase mb-1">Archived days</div>
              <div className="max-h-24 overflow-y-auto space-y-1">
                {archived.slice(0, 7).map((day) => (
                  <div
                    key={day.date}
                    className="flex justify-between text-[10px] p-1.5 bg-black/20 rounded border border-nexus-border/30"
                  >
                    <span className="text-gray-300">{day.date}</span>
                    <span className="text-nexus-muted">{day.summary?.totalTrades ?? day.tradeCount} trades</span>
                    <span
                      className={`font-mono font-bold ${
                        (day.summary?.netPnlInr ?? 0) >= 0 ? 'text-nexus-green' : 'text-nexus-red'
                      }`}
                    >
                      ₹{(day.summary?.netPnlInr ?? 0).toFixed(0)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function TradeRow({
  trade,
  open = false,
}: {
  trade: MultiSnapshot['autoTrader']['closedPaperTrades'][0];
  open?: boolean;
}) {
  const mode = (trade.entryContext?.executionMode as string) || 'PAPER';
  const rankGrade = trade.entryContext?.rankGrade as string | undefined;
  const rankScore = trade.entryContext?.rankScore as number | undefined;
  const cycleRank = trade.entryContext?.cycleRank as number | undefined;
  return (
    <div className="text-[10px] p-1.5 border border-nexus-border/50 rounded bg-black/20">
      <div className="flex justify-between">
        <span>
          <span className={trade.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
            {trade.symbol} {trade.side} {trade.strike}
          </span>
          {' · '}
          <span className={mode === 'LIVE' ? 'text-nexus-red' : 'text-nexus-accent'}>[{mode}]</span>
          {rankGrade && (
            <>
              {' · '}
              <span className="text-nexus-yellow">
                {rankGrade} {rankScore?.toFixed(1)}
                {cycleRank ? ` · #${cycleRank}` : ''}
              </span>
            </>
          )}
          {!open && (
            <>
              {' · '}
              <span className="text-nexus-accent">{trade.exitReason?.replace('simple_', '')}</span>
            </>
          )}
        </span>
        <span className={`font-mono font-bold ${trade.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
          {open ? `₹${(trade.pnlInr ?? 0).toFixed(0)} mtm` : `₹${trade.pnlInr.toFixed(0)}`}
        </span>
      </div>
    </div>
  );
}

function LogEventRow({ entry }: { entry: import('../types').TradeLogEntry }) {
  const trade = entry.trade as Record<string, unknown> | undefined;
  if (!trade) return null;
  const mode = (trade.executionMode as string) || 'PAPER';
  const pnl = trade.pnlInr as number | undefined;
  return (
    <div className="text-[9px] p-1 bg-black/10 rounded font-mono">
      <span className="text-nexus-muted">{entry.event.replace('TRADE_', '')}</span>
      {' '}
      <span className={mode === 'LIVE' ? 'text-nexus-red' : 'text-nexus-accent'}>[{mode}]</span>
      {' '}
      {String(trade.symbol)} {String(trade.side)} {String(trade.strike)}
      {entry.event === 'TRADE_CLOSED' && pnl != null && (
        <span className={pnl >= 0 ? ' text-nexus-green' : ' text-nexus-red'}> ₹{pnl.toFixed(0)}</span>
      )}
    </div>
  );
}

function formatNewsAge(refreshedAt: string | null): string {
  if (!refreshedAt) return '—';
  const ms = Date.now() - new Date(refreshedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return 'just now';
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return 'just now';
  if (mins === 1) return '1 min ago';
  return `${mins} min ago`;
}

function formatHeadlineTime(epochSec?: number): string {
  if (!epochSec) return '';
  try {
    return new Date(epochSec * 1000).toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

export function NewsPanel({ news: seedNews = [] }: { news?: NewsItem[] }) {
  const [items, setItems] = useState<NewsItem[]>(seedNews);
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);
  const [aggregate, setAggregate] = useState<NewsAggregate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    if (seedNews.length > 0 && items.length === 0) {
      setItems(seedNews);
    }
  }, [seedNews, items.length]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch('/api/market/news');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as MarketNewsResponse;
        if (cancelled) return;
        setItems(json.items ?? []);
        setRefreshedAt(json.refreshedAt ?? null);
        setAggregate(json.aggregate ?? null);
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'News unavailable');
        }
      }
    }

    void load();
    const pollId = window.setInterval(() => void load(), NEWS_POLL_MS);
    const ageId = window.setInterval(() => setTick((t) => t + 1), 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(pollId);
      window.clearInterval(ageId);
    };
  }, []);

  const badge = [
    aggregate?.riskLevel ? `${aggregate.riskLevel} RISK` : null,
    `↻ ${formatNewsAge(refreshedAt)}`,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <Panel title="India Market News Intelligence" badge={badge || undefined}>
      <div className="space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <NewsOutlookCard label="Current session" outlook={aggregate?.currentSession} />
          <NewsOutlookCard label="Next session" outlook={aggregate?.nextSession} />
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-[9px]">
          {(aggregate?.providerCoverage ?? []).map((provider) => (
            <span key={provider} className="rounded border border-nexus-border bg-black/20 px-1.5 py-0.5 uppercase text-nexus-muted">
              {provider}
            </span>
          ))}
          <span className="text-nexus-muted">
            {aggregate?.guardrail ?? 'News is confirmation only — price and orderflow must agree.'}
          </span>
        </div>

        {error && items.length === 0 ? (
          <p className="text-xs text-nexus-muted">{error}</p>
        ) : items.length === 0 ? (
          <div className="text-xs text-nexus-muted">
            No fresh articles. Upstox instrument/position news and configured global cues will appear here automatically.
          </div>
        ) : (
          <div className="max-h-64 overflow-y-auto grid grid-cols-1 xl:grid-cols-2 gap-2 pr-1">
            {items.slice(0, 12).map((n, i) => (
              <NewsRow key={`${n.headline.slice(0, 40)}-${i}`} item={n} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

function NewsOutlookCard({
  label,
  outlook,
}: {
  label: string;
  outlook?: import('../types').NewsSessionOutlook;
}) {
  const side = outlook?.sideBias ?? 'NEUTRAL';
  const tone =
    side === 'CALL' ? 'text-nexus-green' : side === 'PUT' ? 'text-nexus-red' : 'text-nexus-muted';
  return (
    <div className="rounded-lg border border-nexus-border/70 bg-black/20 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wide text-nexus-muted">{label}</span>
        <span className={`font-mono text-sm font-bold ${tone}`}>{side}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[9px] text-nexus-muted">
        <span>{outlook?.confidence ?? 'LOW'} confidence</span>
        <span>score {outlook?.score?.toFixed(1) ?? '0.0'}</span>
        <span>{outlook?.headlineCount ?? 0} verified cues</span>
        <span>{outlook?.highImpactCount ?? 0} high impact</span>
      </div>
    </div>
  );
}

function NewsRow({ item }: { item: NewsItem }) {
  const when = formatHeadlineTime(item.datetime);
  const sideTone =
    item.sideBias === 'CALL'
      ? 'text-nexus-green border-nexus-green/30'
      : item.sideBias === 'PUT'
        ? 'text-nexus-red border-nexus-red/30'
        : 'text-nexus-muted border-nexus-border';
  const impactTone =
    item.impact === 'HIGH' ? 'text-nexus-yellow' : item.impact === 'MEDIUM' ? 'text-nexus-accent' : 'text-nexus-muted';
  const headline = item.url ? (
    <a href={item.url} target="_blank" rel="noreferrer" className="text-gray-200 hover:text-white line-clamp-2">
      {item.headline}
    </a>
  ) : (
    <span className="text-gray-200 line-clamp-2">{item.headline}</span>
  );
  return (
    <article className="rounded-lg border border-nexus-border/50 bg-black/20 p-2.5 text-[10px]">
      <div className="flex items-start gap-2">
        <span className={`shrink-0 rounded border px-1.5 py-0.5 font-bold ${sideTone}`}>
          {item.sideBias ?? 'NEUTRAL'}
        </span>
        <div className="min-w-0 flex-1">
          {headline}
          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[9px] text-nexus-muted">
            <span className={impactTone}>{item.impact ?? 'LOW'} IMPACT</span>
            <span>{item.horizon?.replace('_', ' ') ?? 'BACKGROUND'}</span>
            <span>{item.verification ?? 'UNVERIFIED'}</span>
            {item.source ? <span>{item.source}</span> : null}
            {when ? <span>{when}</span> : null}
            {(item.affectedSymbols ?? []).length ? <span>{item.affectedSymbols?.join(' · ')}</span> : null}
          </div>
        </div>
      </div>
    </article>
  );
}
