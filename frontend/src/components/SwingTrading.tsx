import { Panel, Metric } from './Panel';
import type { AutoTraderState, SymbolSnapshot } from '../types';

function holdDays(openedAt: string): string {
  const days = (Date.now() - new Date(openedAt).getTime()) / 86400000;
  if (days < 1) return `${Math.round(days * 24)}h`;
  return `${days.toFixed(1)}d`;
}

export function SwingTrading({
  snap,
  auto,
}: {
  snap: SymbolSnapshot;
  auto: AutoTraderState;
}) {
  const swings = auto.openPaperTrades.filter((t) => t.strategyType === 'SWING');
  const closedSwings = auto.closedPaperTrades.filter((t) => t.strategyType === 'SWING');
  const alerts = snap.swingAlerts || [];
  const enabled = auto.tradeMastermind.swingTradingEnabled !== false;

  return (
    <Panel title="Swing Trading" badge={enabled ? '2–5 DAYS' : 'OFF'}>
      {!enabled ? (
        <p className="text-xs text-nexus-muted">Swing mode disabled in config</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2 mb-3">
            <Metric label="Open swings" value={swings.length} />
            <Metric label="Signals" value={alerts.filter((a) => a.tradeable).length} color="text-nexus-accent" />
            <Metric label="Closed" value={closedSwings.length} />
          </div>

          <div className="text-[10px] text-nexus-muted uppercase mb-1">Open positions</div>
          {swings.length === 0 ? (
            <p className="text-xs text-nexus-muted py-2">No swing holds — targets +30% / stop −12% / max 5 days</p>
          ) : (
            <div className="space-y-1.5 max-h-28 overflow-y-auto mb-3">
              {swings.map((t) => {
                const pct = t.entryPremium
                  ? ((t.pnlPoints / t.entryPremium) * 100).toFixed(1)
                  : '0';
                return (
                  <div key={t.id} className="flex justify-between text-[11px] p-1.5 bg-black/30 rounded">
                    <span>
                      <span className={t.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                        {t.symbol} {t.side} {t.strike}
                      </span>
                      <span className="text-nexus-muted ml-1">· {holdDays(t.openedAt)}</span>
                    </span>
                    <span className={`font-mono font-bold ${t.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
                      {pct}% / ₹{t.pnlInr.toFixed(0)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          <div className="text-[10px] text-nexus-muted uppercase mb-1">Setups</div>
          {alerts.length === 0 ? (
            <p className="text-xs text-nexus-muted">No swing setup — need trend, PCR extreme, or max-pain gap</p>
          ) : (
            <div className="max-h-24 overflow-y-auto space-y-1">
              {alerts.slice(0, 4).map((a, i) => (
                <div
                  key={i}
                  className={`text-[10px] p-1.5 rounded border ${
                    a.tradeable ? 'border-nexus-accent/40 bg-nexus-accent/5' : 'border-nexus-border/40'
                  }`}
                >
                  <div className="flex justify-between">
                    <span className={a.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                      {a.swingType} · {a.side} {a.strike}
                    </span>
                    <span className="text-nexus-muted">{a.confidence?.toFixed(0)}%</span>
                  </div>
                  <p className="text-nexus-muted mt-0.5 line-clamp-2">{a.reason}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
