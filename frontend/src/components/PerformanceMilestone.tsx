import { Panel, ScoreBar } from './Panel';
import type { PerformanceMilestone as MilestoneStats } from '../types';

function CheckRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="flex justify-between items-center text-[11px] gap-2">
      <span className="text-nexus-muted">{label}</span>
      <span className="text-right">
        <span className="text-gray-300 font-mono">{detail}</span>
        <span className={`ml-2 font-bold ${ok ? 'text-nexus-green' : 'text-nexus-red'}`}>
          {ok ? '✓' : '✗'}
        </span>
      </span>
    </div>
  );
}

function isMilestoneStats(stats: MilestoneStats | null): stats is MilestoneStats {
  return Boolean(stats && typeof stats.tradeCount === 'number' && stats.checks);
}

export function PerformanceMilestone({ stats }: { stats: MilestoneStats | null }) {
  if (!isMilestoneStats(stats)) {
    return (
      <Panel title="50-Trade Milestone">
        <p className="text-xs text-nexus-muted text-center py-4">Loading track record… (requires backend milestone API)</p>
      </Panel>
    );
  }

  const batchLabel = stats.batchNumber > 1 || stats.completedBatches > 0
    ? `Batch ${stats.batchNumber}`
    : '50-Trade Milestone';
  const badge = stats.readyForLiveMilestone
    ? 'LIVE READY'
    : `${stats.tradeCount}/${stats.targetTrades}`;
  const badgeColor = stats.readyForLiveMilestone ? 'bg-nexus-green' : 'bg-nexus-accent/80';

  return (
    <Panel title={batchLabel} badge={badge} badgeColor={badgeColor}>
      <div className="mb-3">
        <div className="flex justify-between text-[10px] text-nexus-muted mb-1">
          <span>Current batch toward live review</span>
          <span className="font-mono">
            {stats.tradeCount} / {stats.targetTrades}
            {stats.lifetimeTradeCount > stats.tradeCount && (
              <span className="text-nexus-muted ml-1">({stats.lifetimeTradeCount} lifetime)</span>
            )}
          </span>
        </div>
        <ScoreBar value={stats.tradeProgressPct} max={100} />
      </div>

      <div className="space-y-2 mb-3">
        <CheckRow
          label={`Batch ${stats.batchNumber} · 50 trades`}
          ok={stats.checks.tradeCountMet}
          detail={`${stats.tradeCount} closed`}
        />
        <CheckRow
          label="Profit factor"
          ok={stats.checks.profitFactorMet}
          detail={`${stats.profitFactor.toFixed(2)} / ${stats.targetProfitFactor}+`}
        />
        <CheckRow
          label="Win rate"
          ok={stats.checks.winRateMet}
          detail={`${stats.winRate.toFixed(0)}% / ${stats.targetWinRate}%+`}
        />
        <CheckRow
          label="Max drawdown"
          ok={stats.checks.drawdownMet}
          detail={`${stats.maxDrawdownPct.toFixed(1)}% / ≤${stats.maxDrawdownLimitPct}%`}
        />
      </div>

      <div className="text-[10px] p-2 rounded bg-black/30 border border-nexus-border">
        <div className="flex justify-between mb-1">
          <span className="text-nexus-muted">Net PnL (this batch)</span>
          <span className={`font-mono font-bold ${stats.netPnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
            ₹{stats.netPnlInr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <p className={`${stats.readyForLiveMilestone ? 'text-nexus-green' : 'text-nexus-yellow'}`}>
          {stats.message}
        </p>
        {stats.slippageAdjusted ? (
          <p className="text-nexus-muted mt-1.5 leading-relaxed">
            Live-like paper fills: +entry / −exit slippage and round-trip fees applied to new trades.
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
