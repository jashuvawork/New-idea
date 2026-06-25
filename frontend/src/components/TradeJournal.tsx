import { Panel } from './Panel';
import type { MultiSnapshot, TradeHistoryResponse, TradeLogResponse } from '../types';

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
  return (
    <div className="text-[10px] p-1.5 border border-nexus-border/50 rounded bg-black/20">
      <div className="flex justify-between">
        <span>
          <span className={trade.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
            {trade.symbol} {trade.side} {trade.strike}
          </span>
          {' · '}
          <span className={mode === 'LIVE' ? 'text-nexus-red' : 'text-nexus-accent'}>[{mode}]</span>
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

export function NewsPanel({ news }: { news: MultiSnapshot['news'] }) {
  return (
    <Panel title="News & Events">
      {news.length === 0 ? (
        <p className="text-xs text-nexus-muted">No news feed configured</p>
      ) : (
        <div className="max-h-32 overflow-y-auto space-y-2">
          {news.slice(0, 5).map((n, i) => (
            <div key={i} className="text-[10px] border-b border-nexus-border/30 pb-1.5">
              <div className="flex gap-2">
                <span
                  className={`font-bold ${
                    n.sentiment === 'BULLISH'
                      ? 'text-nexus-green'
                      : n.sentiment === 'BEARISH'
                        ? 'text-nexus-red'
                        : 'text-nexus-muted'
                  }`}
                >
                  {n.sentiment[0]}
                </span>
                <span className="text-gray-300 line-clamp-2">{n.headline}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
