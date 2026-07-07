import { ReactNode } from 'react';
import { Panel } from './Panel';
import type { WeeklyDashboard } from '../types';

function GoalLayer({
  title,
  passed,
  message,
  children,
}: {
  title: string;
  passed: boolean;
  message: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded border border-nexus-border bg-black/25 p-2.5 space-y-1.5">
      <div className="flex justify-between items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-nexus-muted">{title}</span>
        <span className={`text-[10px] font-bold ${passed ? 'text-nexus-green' : 'text-nexus-yellow'}`}>
          {passed ? 'PASS' : 'REVIEW'}
        </span>
      </div>
      {children}
      <p className="text-[10px] text-nexus-muted leading-relaxed">{message}</p>
    </div>
  );
}

export function WeeklyDashboardPanel({ data }: { data: WeeklyDashboard | null }) {
  if (!data) {
    return (
      <Panel title="Weekly Review">
        <p className="text-xs text-nexus-muted text-center py-4">Loading weekly dashboard…</p>
      </Panel>
    );
  }

  const { summary, goals, policyViolations, currentSession, daily, recommendation } = data;
  const exp = summary.expectancy;

  return (
    <Panel
      title="Weekly Review"
      badge={`${data.periodStart} → ${data.periodEnd}`}
      badgeColor="bg-nexus-accent/70"
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div>
          <div className="text-nexus-muted">Trades</div>
          <div className="font-mono font-bold">{summary.tradeCount}</div>
        </div>
        <div>
          <div className="text-nexus-muted">Net PnL</div>
          <div className={`font-mono font-bold ${summary.netPnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
            ₹{summary.netPnlInr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
        </div>
        <div>
          <div className="text-nexus-muted">PF / WR</div>
          <div className="font-mono">{summary.profitFactor.toFixed(2)} / {summary.winRate.toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-nexus-muted">Expectancy</div>
          <div className={`font-mono font-bold ${exp.perTradeInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
            ₹{exp.perTradeInr.toFixed(0)}/trade
          </div>
        </div>
      </div>

      <div className="space-y-2 mb-3">
        <GoalLayer title="Safety" passed={goals.safety.passed} message={goals.safety.message}>
          <div className="text-[10px] font-mono text-gray-300">
            Violations {policyViolations.count} · Max day loss ₹{goals.safety.maxDailyLossInr.toLocaleString('en-IN')}
          </div>
        </GoalLayer>
        <GoalLayer title="Process" passed={goals.process.passed} message={goals.process.message}>
          <div className="text-[10px] font-mono text-gray-300">
            Aligned {goals.process.breadthAlignedPct}% · Cheap-prem OK {goals.process.cheapPremiumCompliancePct}%
          </div>
        </GoalLayer>
        <GoalLayer title="Outcome" passed={goals.outcome.passed} message={goals.outcome.message}>
          <div className="text-[10px] font-mono text-gray-300">
            PF {goals.outcome.profitFactor.toFixed(2)} · E ₹{goals.outcome.expectancyPerTradeInr}/trade
          </div>
        </GoalLayer>
      </div>

      {policyViolations.count > 0 ? (
        <div className="mb-3 rounded border border-nexus-red/30 bg-nexus-red/5 p-2">
          <p className="text-[10px] font-semibold text-nexus-red mb-1">Policy violations ({policyViolations.count})</p>
          <ul className="text-[10px] text-gray-300 space-y-0.5 max-h-24 overflow-y-auto">
            {policyViolations.trades.slice(0, 5).map((t, i) => (
              <li key={i}>
                {String(t.openedAt).slice(0, 16)} {t.symbol} {t.side} — {t.violations.join(', ')}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mb-3">
        <p className="text-[10px] text-nexus-muted mb-1">
          Session skips ({currentSession.skipped.total}) · Near-misses ({currentSession.nearMisses.length})
        </p>
        {currentSession.skipped.total > 0 ? (
          <div className="text-[10px] font-mono text-gray-400 max-h-16 overflow-y-auto">
            {Object.entries(currentSession.skipped.byReason).slice(0, 6).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="truncate pr-2">{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[10px] text-nexus-muted">No active skip reasons</p>
        )}
      </div>

      {daily.length > 0 ? (
        <div className="mb-3">
          <p className="text-[10px] text-nexus-muted mb-1">Daily breakdown</p>
          <div className="space-y-1 max-h-28 overflow-y-auto">
            {daily.map((d) => (
              <div key={d.date} className="flex justify-between text-[10px] font-mono">
                <span>{d.date}</span>
                <span className={d.netPnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}>
                  {d.trades}t · ₹{d.netPnlInr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="text-[10px] p-2 rounded bg-black/30 border border-nexus-border text-nexus-yellow leading-relaxed">
        {recommendation}
      </div>
    </Panel>
  );
}
