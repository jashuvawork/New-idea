import { Panel } from './Panel';
import type { MultiSnapshot, TradeHistoryResponse } from '../types';

export function TradeJournal({
  data,
  history,
}: {
  data: MultiSnapshot;
  history: TradeHistoryResponse | null;
}) {
  const sessionClosed = data.autoTrader.closedPaperTrades || [];
  const archived = history?.days?.filter((d) => d.tradeCount > 0) || [];

  return (
    <Panel title="Trade Journal" badge={`${sessionClosed.length} today`}>
      {sessionClosed.length === 0 && archived.length === 0 ? (
        <p className="text-xs text-nexus-muted text-center py-3">No closed trades yet — paper trades are stored daily</p>
      ) : (
        <div className="space-y-2">
          {sessionClosed.length > 0 && (
            <div>
              <div className="text-[10px] text-nexus-muted uppercase mb-1">Today (live session)</div>
              <div className="max-h-28 overflow-y-auto space-y-1">
                {[...sessionClosed].reverse().slice(0, 8).map((t) => (
                  <TradeRow key={t.id} trade={t} />
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

function TradeRow({ trade }: { trade: MultiSnapshot['autoTrader']['closedPaperTrades'][0] }) {
  return (
    <div className="text-[10px] p-1.5 border border-nexus-border/50 rounded bg-black/20">
      <div className="flex justify-between">
        <span>
          <span className={trade.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
            {trade.symbol} {trade.side} {trade.strike}
          </span>
          {' · '}
          <span className="text-nexus-accent">{trade.exitReason?.replace('simple_', '')}</span>
        </span>
        <span className={`font-mono font-bold ${trade.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
          ₹{trade.pnlInr.toFixed(0)}
        </span>
      </div>
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
