import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

export function StrategyRouter({ snap }: { snap: SymbolSnapshot }) {
  const trades = snap.suggestedTrades ?? [];

  return (
    <Panel title="Strategy Router" badge={`${trades.length} signals`}>
      {trades.length === 0 ? (
        <p className="text-nexus-muted text-xs text-center py-4">No candidates passing entry gates</p>
      ) : (
        <div className="space-y-2">
          {trades.map((t) => (
            <div key={t.id} className="p-2 border border-nexus-border rounded bg-black/20">
              <div className="flex justify-between items-center">
                <span className={`font-bold text-sm ${t.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}`}>
                  {t.symbol} {t.side} {t.strike}
                </span>
                <span className="text-xs bg-nexus-accent/20 text-nexus-accent px-2 py-0.5 rounded">
                  {t.strategyType}
                </span>
              </div>
              <div className="flex gap-3 mt-1 text-[11px] text-nexus-muted">
                <span>Premium: <b className="text-white">₹{(t.lastPremium ?? 0).toFixed(2)}</b></span>
                <span>TQS: <b className="text-nexus-accent">{(t.tqs ?? 0).toFixed(0)}</b></span>
                <span>Conf: {(t.confidence ?? 0).toFixed(0)}%</span>
                {t.adaptiveTarget && <span>Target: {t.adaptiveTarget}pt</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
