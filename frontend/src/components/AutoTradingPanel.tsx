import { Panel, Metric } from './Panel';
import type { AutoTraderState, ExecutionChartContext } from '../types';

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
          {auto.lastEntry.chartDirection && (
            <div className="mt-0.5 text-[9px] text-nexus-muted">
              Scan chart {auto.lastEntry.chartDirection}
              {auto.lastEntry.execChartDirection
                && auto.lastEntry.execChartDirection !== auto.lastEntry.chartDirection && (
                <span> · live {auto.lastEntry.execChartDirection}</span>
              )}
              {auto.lastEntry.chartBypass ? (
                <span className="text-nexus-green"> · {auto.lastEntry.chartBypass} bypass</span>
              ) : auto.lastEntry.chartAligned === false ? (
                <span className="text-nexus-yellow"> · misaligned at scan</span>
              ) : auto.lastEntry.chartAligned ? (
                <span className="text-nexus-green"> · aligned</span>
              ) : null}
            </div>
          )}
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
            const plan = t.entryContext?.exitPlan as Record<string, number | string | boolean> | undefined;
            const chartLive = t.entryContext?.chartExitLive as Record<string, number | boolean> | undefined;
            const execMode = t.entryContext?.executionMode as string | undefined;
            const brokerId = t.entryContext?.brokerOrderId as string | undefined;
            const execChart = t.entryContext?.executionChart as ExecutionChartContext | undefined;
            const sl = plan?.stopPct ? `−${plan.stopPct}%` : plan?.stopPoints ? `−${Number(plan.stopPoints).toFixed(1)}pt` : null;
            const fmtTp = (v: unknown) => {
              const n = Number(v);
              if (!Number.isFinite(n) || n <= 0 || n > 500) return null;
              return `+${n.toFixed(1)}pt`;
            };
            const tpHalf = fmtTp(plan?.targetPointsHalf);
            const tpFull = fmtTp(plan?.targetPoints);
            const tp2 = fmtTp(plan?.targetPoints2);
            const tpLine = plan?.targetPct
              ? `+${plan.targetPct}%`
              : [tpHalf ? `${tpHalf}½` : null, tpFull, tp2].filter(Boolean).join(' / ');
            const trailKeep = plan?.trailKeepRatio != null ? `${(Number(plan.trailKeepRatio) * 100).toFixed(0)}%` : null;
            const chartConf = plan?.chartConfidenceLive ?? plan?.chartConfidence;
            const chartDelta = plan?.chartConfidenceDelta;
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
                  {tpLine && <span>TP {tpLine}</span>}
                  {trailKeep && <span>trail keep {trailKeep}</span>}
                  {chartConf != null && (
                    <span className={Number(chartConf) >= 62 ? 'text-nexus-green' : 'text-nexus-yellow'}>
                      chart {Number(chartConf).toFixed(0)}%
                      {chartDelta != null && Number(chartDelta) !== 0
                        ? ` (${Number(chartDelta) > 0 ? '+' : ''}${Number(chartDelta).toFixed(0)})`
                        : ''}
                    </span>
                  )}
                  {chartLive?.letRun ? <span className="text-nexus-green">LET RUN</span> : null}
                  {chartLive?.tighten ? <span className="text-nexus-red">TIGHTEN</span> : null}
                  {brokerId && <span>ord {brokerId}</span>}
                  {execChart?.indexChart?.direction && (
                    <span>
                      idx {execChart.indexChart.direction}
                      {execChart.premiumChart?.momentum5Pct != null
                        ? ` · prem ${execChart.premiumChart.momentum5Pct > 0 ? '+' : ''}${execChart.premiumChart.momentum5Pct.toFixed(2)}%`
                        : ''}
                    </span>
                  )}
                  {execChart?.indexMtf?.consensus && (
                    <span>
                      MTF {execChart.indexMtf.consensus} ({execChart.indexMtf.alignedCount}/{execChart.indexMtf.total})
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {(auto.closedPaperTrades?.length ?? 0) > 0 ? (
        <div className="mt-2 pt-2 border-t border-nexus-border">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">
            Recent closed ({auto.closedPaperTrades.length})
          </div>
          <div className="space-y-1 max-h-24 overflow-y-auto">
            {auto.closedPaperTrades.slice(-3).reverse().map((t) => (
              <div key={`closed-${t.id}`} className="p-1 rounded bg-black/20 text-[10px] font-mono flex justify-between gap-2">
                <span className={t.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                  {t.symbol} {t.side} {t.strike} ×{t.lots}
                </span>
                <span className={t.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}>
                  ₹{t.pnlInr.toFixed(0)}
                  {t.exitReason ? ` · ${t.exitReason.replace('simple_', '').replace('adaptive_', '')}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {!liveMode && (
        <div className="mt-2 pt-2 border-t border-nexus-border text-[9px] text-nexus-muted leading-relaxed">
          Paper auto-trading with slippage-adjusted fills. Set ENABLE_LIVE_TRADING=true on the server for broker execution.
        </div>
      )}
    </Panel>
  );
}
