import { Panel } from './Panel';
import type { MultiSnapshot } from '../types';

export function TradeJournal({ data }: { data: MultiSnapshot }) {
  const closed = data.autoTrader.closedPaperTrades || [];

  return (
    <Panel title="Trade Journal" badge={`${closed.length} events`}>
      {closed.length === 0 ? (
        <p className="text-xs text-nexus-muted text-center py-3">No closed trades this session</p>
      ) : (
        <div className="max-h-40 overflow-y-auto space-y-1">
          {[...closed].reverse().slice(0, 15).map((t) => (
            <div key={t.id} className="text-[10px] p-1.5 border border-nexus-border/50 rounded bg-black/20">
              <div className="flex justify-between">
                <span>
                  <span className="text-nexus-muted">OPEN</span>{' '}
                  <span className={t.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                    {t.symbol} {t.side} {t.strike}
                  </span>
                  {' → '}
                  <span className="text-nexus-muted">EXIT</span>{' '}
                  <span className="text-nexus-accent">{t.exitReason?.replace('simple_', '')}</span>
                </span>
                <span className={`font-mono font-bold ${t.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
                  ₹{t.pnlInr.toFixed(0)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
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
                <span className={`font-bold ${
                  n.sentiment === 'BULLISH' ? 'text-nexus-green' :
                  n.sentiment === 'BEARISH' ? 'text-nexus-red' : 'text-nexus-muted'
                }`}>
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
