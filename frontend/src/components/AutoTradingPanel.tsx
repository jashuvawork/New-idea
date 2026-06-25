import { Panel, Metric } from './Panel';
import type { AutoTraderState } from '../types';

export function AutoTradingPanel({ auto }: { auto: AutoTraderState }) {
  const report = auto.dailyReport;
  const pfColor = report.profitFactor >= 1.2 ? 'text-nexus-green' : report.profitFactor < 1 ? 'text-nexus-red' : 'text-nexus-yellow';
  const liveMode = auto.liveTradingEnabled && auto.autoTradingEnabled;
  const modeLabel = liveMode ? 'LIVE AUTO' : 'PAPER AUTO';
  const modeColor = liveMode ? 'bg-nexus-red/80 text-white' : 'bg-nexus-accent/80';

  return (
    <Panel title="Auto Trading" badge={modeLabel} badgeColor={modeColor}>
      <div className="grid grid-cols-3 gap-2 mb-3">
        <Metric
          label="Status"
          value={auto.running && auto.autoTradingEnabled ? 'ACTIVE' : 'PAUSED'}
          color={auto.running && auto.autoTradingEnabled ? 'text-nexus-green' : 'text-nexus-red'}
        />
        <Metric label="Open" value={auto.openPaperTrades.length} />
        <Metric label="Broker Orders" value={auto.liveOrdersPlaced ?? 0} />
      </div>

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

      {auto.lastEntry && (
        <div className="mb-2 p-1.5 rounded bg-black/30 text-[10px] font-mono">
          <span className="text-nexus-muted">Last entry </span>
          <span className="text-nexus-accent">{auto.lastEntry.symbol} {auto.lastEntry.side} {auto.lastEntry.strike}</span>
          <span className="text-nexus-muted"> ×{auto.lastEntry.lots} </span>
          <span className={auto.lastEntry.executionMode === 'LIVE' ? 'text-nexus-red' : 'text-nexus-green'}>
            [{auto.lastEntry.executionMode}]
          </span>
        </div>
      )}

      {auto.lastExit && (
        <div className="mb-2 p-1.5 rounded bg-black/30 text-[10px] font-mono">
          <span className="text-nexus-muted">Last exit </span>
          <span>{auto.lastExit.symbol}</span>
          <span className="text-nexus-muted"> {auto.lastExit.reason?.replace('simple_', '')} </span>
          <span className={(auto.lastExit.pnlInr ?? 0) >= 0 ? 'text-nexus-green' : 'text-nexus-red'}>
            ₹{(auto.lastExit.pnlInr ?? 0).toFixed(0)}
          </span>
        </div>
      )}

      {auto.skipped.length > 0 && (
        <div className="mb-2">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Skipped / Pending</div>
          <div className="space-y-1 max-h-20 overflow-y-auto">
            {auto.skipped.slice(-4).map((s, i) => (
              <div key={`${s.symbol}-${i}`} className="text-[9px] text-nexus-yellow font-mono">
                {s.symbol}: {s.reason}{s.message ? ` — ${s.message}` : ''}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="text-[10px] text-nexus-muted uppercase mb-1">Open Positions ({auto.openPaperTrades.length})</div>
      {auto.openPaperTrades.length === 0 ? (
        <p className="text-xs text-nexus-muted py-2">Scanning for best setup — explosion &gt; scalp &gt; swing</p>
      ) : (
        <div className="space-y-1.5 max-h-36 overflow-y-auto">
          {auto.openPaperTrades.map((t) => {
            const plan = t.entryContext?.exitPlan as Record<string, number> | undefined;
            const execMode = t.entryContext?.executionMode as string | undefined;
            const brokerId = t.entryContext?.brokerOrderId as string | undefined;
            const sl = plan?.stopPct ? `−${plan.stopPct}%` : plan?.stopPoints ? `−${plan.stopPoints}pt` : null;
            const tp = plan?.targetPct ? `+${plan.targetPct}%` : plan?.targetPoints ? `+${plan.targetPoints}pt` : null;
            return (
              <div key={t.id} className="p-1.5 bg-black/30 rounded text-[11px]">
                <div className="flex justify-between">
                  <span className={t.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                    {t.symbol} {t.side} {t.strike} ×{t.lots}
                    {execMode === 'LIVE' && <span className="ml-1 text-[9px] text-nexus-red">LIVE</span>}
                  </span>
                  <span className={`font-mono font-bold ${t.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
                    {t.pnlPoints >= 0 ? '+' : ''}{t.pnlPoints.toFixed(1)}pt / ₹{t.pnlInr.toFixed(0)}
                  </span>
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5 text-[9px] text-nexus-muted font-mono">
                  <span>{t.strategyType}</span>
                  {sl && <span>SL {sl}</span>}
                  {tp && <span>TP {tp}</span>}
                  {brokerId && <span>ord {brokerId}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!liveMode && (
        <div className="mt-2 pt-2 border-t border-nexus-border text-[9px] text-nexus-muted">
          Paper auto-trading is active. Set ENABLE_LIVE_TRADING=true on the server for broker execution.
        </div>
      )}
    </Panel>
  );
}
