import { Panel } from './Panel';
import type { MultiSnapshot, PaperTrade, TradeHistoryResponse, TradeLogResponse } from '../types';
import {
  formatLtp,
  formatTradeDateTime,
  formatTradeTime,
  tradeBuyLtp,
  tradeQuantity,
  tradeSoldLtp,
} from '../utils/tradeFormat';

export function TradeJournal({
  data,
  history,
  tradeLog,
  archivedTrades = [],
}: {
  data: MultiSnapshot;
  history: TradeHistoryResponse | null;
  tradeLog?: TradeLogResponse | null;
  archivedTrades?: PaperTrade[];
}) {
  const sessionClosed = data.autoTrader.closedPaperTrades || [];
  const sessionOpen = data.autoTrader.openPaperTrades || [];
  const archived = history?.days?.filter((d) => d.tradeCount > 0) || [];
  const logEntries = tradeLog?.entries?.filter((e) => e.event === 'TRADE_OPENED' || e.event === 'TRADE_CLOSED') || [];

  const sessionIds = new Set([...sessionOpen, ...sessionClosed].map((t) => t.id));
  const olderClosed = archivedTrades.filter((t) => !sessionIds.has(t.id));

  const ledgerRows: Array<{ trade: PaperTrade; open: boolean; sortAt: string }> = [
    ...sessionOpen.map((t) => ({ trade: t, open: true, sortAt: t.openedAt })),
    ...sessionClosed.map((t) => ({ trade: t, open: false, sortAt: t.closedAt || t.openedAt })),
    ...olderClosed.map((t) => ({ trade: t, open: false, sortAt: t.closedAt || t.openedAt })),
  ].sort((a, b) => new Date(b.sortAt).getTime() - new Date(a.sortAt).getTime());

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

      {ledgerRows.length === 0 ? (
        <p className="text-xs text-nexus-muted text-center py-3">
          No trades yet — each paper/live trade is appended to trades.log
        </p>
      ) : (
        <div className="overflow-x-auto -mx-1">
          <TradeLedgerTable rows={ledgerRows.slice(0, 20)} />
        </div>
      )}

      {logEntries.length > 0 && (
        <div className="pt-2 mt-2 border-t border-nexus-border/50">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Recent log events</div>
          <div className="max-h-20 overflow-y-auto space-y-1">
            {logEntries.slice(0, 4).map((e, i) => (
              <LogEventRow key={`${e.ts}-${i}`} entry={e} />
            ))}
          </div>
        </div>
      )}

      {archived.length > 0 && (
        <div className="pt-2 mt-2 border-t border-nexus-border/50">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Archived days</div>
          <div className="max-h-20 overflow-y-auto space-y-1">
            {archived.slice(0, 5).map((day) => (
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
    </Panel>
  );
}

function TradeLedgerTable({
  rows,
}: {
  rows: Array<{ trade: PaperTrade; open: boolean; sortAt: string }>;
}) {
  return (
    <table className="w-full text-[10px] min-w-[520px]">
      <thead>
        <tr className="text-nexus-muted border-b border-nexus-border/60">
          <th className="text-left py-1.5 pr-2 font-medium">Time (IST)</th>
          <th className="text-left py-1.5 pr-2 font-medium">Contract</th>
          <th className="text-right py-1.5 pr-2 font-medium">Qty</th>
          <th className="text-right py-1.5 pr-2 font-medium">Buy LTP</th>
          <th className="text-right py-1.5 pr-2 font-medium">Sold LTP</th>
          <th className="text-right py-1.5 font-medium">PnL</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ trade, open }) => (
          <TradeLedgerRow key={trade.id} trade={trade} open={open} />
        ))}
      </tbody>
    </table>
  );
}

function TradeLedgerRow({ trade, open }: { trade: PaperTrade; open: boolean }) {
  const mode = (trade.entryContext?.executionMode as string) || 'PAPER';
  const qty = tradeQuantity(trade);
  const buy = tradeBuyLtp(trade);
  const sold = tradeSoldLtp(trade, open);
  const timeIso = open ? trade.openedAt : trade.closedAt || trade.openedAt;

  return (
    <tr className="border-b border-nexus-border/30 hover:bg-black/20">
      <td className="py-1.5 pr-2 font-mono text-gray-400 whitespace-nowrap" title={formatTradeDateTime(timeIso)}>
        {formatTradeTime(timeIso)}
      </td>
      <td className="py-1.5 pr-2">
        <span className={trade.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
          {trade.symbol} {trade.side} {trade.strike}
        </span>
        <span className="text-nexus-muted ml-1">
          · {open ? 'OPEN' : trade.exitReason?.replace('simple_', '').replace('explosion_', '') ?? 'CLOSED'}
        </span>
        {mode === 'LIVE' ? <span className="text-nexus-red ml-1">LIVE</span> : null}
      </td>
      <td className="py-1.5 pr-2 text-right font-mono">{qty.toLocaleString('en-IN')}</td>
      <td className="py-1.5 pr-2 text-right font-mono">₹{formatLtp(buy)}</td>
      <td className="py-1.5 pr-2 text-right font-mono">
        {open ? (
          <span className="text-nexus-yellow" title="Mark-to-market exit price">
            ₹{formatLtp(sold)} <span className="text-[8px]">mtm</span>
          </span>
        ) : (
          `₹${formatLtp(sold)}`
        )}
      </td>
      <td className={`py-1.5 text-right font-mono font-bold ${trade.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
        {open ? `₹${(trade.pnlInr ?? 0).toFixed(0)}` : `₹${trade.pnlInr.toFixed(0)}`}
      </td>
    </tr>
  );
}

function LogEventRow({ entry }: { entry: import('../types').TradeLogEntry }) {
  const trade = entry.trade as Record<string, unknown> | undefined;
  if (!trade) return null;
  const mode = (trade.executionMode as string) || 'PAPER';
  const qty = (trade.quantity as number) ?? (trade.lots as number);
  const buy = trade.entryPremium as number | undefined;
  const sold = (trade.exitPremium as number) ?? (trade.currentPremium as number | undefined);
  const pnl = trade.pnlInr as number | undefined;
  return (
    <div className="text-[9px] p-1 bg-black/10 rounded font-mono leading-relaxed">
      <span className="text-nexus-muted">{entry.event.replace('TRADE_', '')}</span>
      {' · '}
      <span className={mode === 'LIVE' ? 'text-nexus-red' : 'text-nexus-accent'}>[{mode}]</span>
      {' '}
      {String(trade.symbol)} {String(trade.side)} {String(trade.strike)}
      {qty != null ? ` · qty ${qty}` : ''}
      {buy != null ? ` · buy ₹${buy.toFixed(2)}` : ''}
      {entry.event === 'TRADE_CLOSED' && sold != null ? ` · sold ₹${sold.toFixed(2)}` : ''}
      {entry.event === 'TRADE_CLOSED' && pnl != null && (
        <span className={pnl >= 0 ? ' text-nexus-green' : ' text-nexus-red'}> · ₹{pnl.toFixed(0)}</span>
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
