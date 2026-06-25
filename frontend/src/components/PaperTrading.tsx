import { Panel, Metric } from './Panel';
import type { AutoTraderState } from '../types';

export function PaperTrading({ auto }: { auto: AutoTraderState }) {
  const report = auto.dailyReport;
  const pfColor = report.profitFactor >= 1.2 ? 'text-nexus-green' : report.profitFactor < 1 ? 'text-nexus-red' : 'text-nexus-yellow';

  return (
    <Panel title="Paper Trading" badge={auto.paperTrading ? 'PAPER' : 'LIVE'}>
      <div className="grid grid-cols-4 gap-2 mb-3">
        <Metric label="Wins" value={report.wins} color="text-nexus-green" />
        <Metric label="Losses" value={report.losses} color="text-nexus-red" />
        <Metric label="PF" value={report.profitFactor.toFixed(2)} color={pfColor} />
        <Metric
          label="Net PnL"
          value={`₹${report.netPnlInr.toFixed(0)}`}
          color={report.netPnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}
        />
      </div>

      <div className="text-[10px] text-nexus-muted uppercase mb-1">Open Trades ({auto.openPaperTrades.length})</div>
      {auto.openPaperTrades.length === 0 ? (
        <p className="text-xs text-nexus-muted py-2">No open positions</p>
      ) : (
        <div className="space-y-1.5 max-h-32 overflow-y-auto">
          {auto.openPaperTrades.map((t) => {
            const plan = t.entryContext?.exitPlan as Record<string, number> | undefined;
            const selScore = t.entryContext?.selectionScore as number | undefined;
            const sl = plan?.stopPct
              ? `−${plan.stopPct}%`
              : plan?.stopPoints
                ? `−${plan.stopPoints}pt`
                : null;
            const tp = plan?.targetPct
              ? `+${plan.targetPct}%`
              : plan?.targetPoints
                ? `+${plan.targetPoints}pt`
                : null;
            return (
              <div key={t.id} className="p-1.5 bg-black/30 rounded text-[11px]">
                <div className="flex justify-between">
                  <span className={t.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                    {t.symbol} {t.side} {t.strike} ×{t.lots}
                  </span>
                  <span className={`font-mono font-bold ${t.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
                    {t.pnlPoints >= 0 ? '+' : ''}{t.pnlPoints.toFixed(1)}pt / ₹{t.pnlInr.toFixed(0)}
                  </span>
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5 text-[9px] text-nexus-muted font-mono">
                  {selScore != null && <span>score {selScore.toFixed(0)}</span>}
                  {sl && <span>SL {sl}</span>}
                  {tp && <span>TP {tp}</span>}
                  {plan?.trailArmPoints != null && (
                    <span className="text-nexus-accent">
                      Trail @{plan.trailArmPoints}pt / {((plan.trailKeepRatio ?? 0.55) * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {Object.keys(report.exitReasons).length > 0 && (
        <div className="mt-2 pt-2 border-t border-nexus-border">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Exit Reasons</div>
          <div className="flex flex-wrap gap-1">
            {Object.entries(report.exitReasons).map(([reason, count]) => (
              <span key={reason} className="text-[9px] bg-gray-800 px-1.5 py-0.5 rounded text-nexus-muted">
                {reason.replace('simple_', '')}: {count}
              </span>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
