import { Panel } from './Panel';
import type { AutoTraderState, CapitalAllocation, DailyProfitGate } from '../types';

export function RiskEngine({ auto }: { auto: AutoTraderState }) {
  const blocks = auto.calibrationBlocks;
  const skipped = auto.skipped || [];
  const cap = (auto.capitalAllocation || {}) as CapitalAllocation;
  const gate = (auto.dailyProfitGate || {}) as DailyProfitGate;

  const progress = gate.progressPct ?? 0;
  const sessionPnl = gate.sessionPnlInr ?? auto.dailyReport.netPnlInr;
  const targetInr = gate.targetInr ?? 200_000;
  const trailInr = gate.trailInr ?? 20_000;
  const gateOk = gate.newEntriesAllowed !== false;

  return (
    <Panel title="Capital & Daily Target" badge={gate.status || 'ACTIVE'}>
      <div className="mb-3 p-2 rounded bg-black/30 border border-nexus-border text-[10px]">
        <div className="flex justify-between mb-1">
          <span className="text-nexus-muted">Upstox margin</span>
          <span className="font-mono font-bold text-nexus-accent">
            ₹{(cap.availableMarginInr || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className="flex justify-between text-[9px] text-nexus-muted">
          <span>50% cap/trade · ₹{((cap.perTradeCapitalInr as number) || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
          <span>Lots {cap.minLots ?? 25}–{cap.maxLots ?? 100}</span>
        </div>
      </div>

      <div className="mb-2">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-nexus-muted">Daily PnL → ₹{(targetInr / 100000).toFixed(0)}L target</span>
          <span className={`font-mono font-bold ${sessionPnl >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
            ₹{sessionPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded overflow-hidden">
          <div
            className={`h-full transition-all ${progress >= 100 ? 'bg-nexus-green' : 'bg-nexus-accent'}`}
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
        <div className="flex justify-between text-[9px] text-nexus-muted mt-1">
          <span>Peak ₹{(gate.bestPnlInr || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
          <span>Trail floor ₹{(gate.trailFloorInr || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} (−₹{(trailInr / 1000).toFixed(0)}K)</span>
        </div>
      </div>

      <div className={`text-[10px] p-1.5 rounded mb-2 ${gateOk ? 'bg-nexus-green/10 text-nexus-green' : 'bg-nexus-red/10 text-nexus-red'}`}>
        {gate.message || (gateOk ? 'Entries active' : 'New entries paused')}
      </div>

      <div className="space-y-2 text-[11px]">
        <div className="flex justify-between">
          <span className="text-nexus-muted">CALL Block</span>
          <span className={blocks.CALL ? 'text-nexus-red font-bold' : 'text-nexus-green'}>
            {blocks.CALL ? 'BLOCKED' : 'Clear'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-nexus-muted">PUT Block</span>
          <span className={blocks.PUT ? 'text-nexus-red font-bold' : 'text-nexus-green'}>
            {blocks.PUT ? 'BLOCKED' : 'Clear'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-nexus-muted">Auto Trader</span>
          <span className={auto.running ? 'text-nexus-green' : 'text-nexus-red'}>
            {auto.running ? 'Running' : 'Stopped'}
          </span>
        </div>
      </div>

      {skipped.length > 0 && (
        <div className="mt-3 pt-2 border-t border-nexus-border">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Recent Skips ({skipped.length})</div>
          <div className="max-h-24 overflow-y-auto space-y-0.5">
            {skipped.slice(-5).map((s, i) => (
              <div key={i} className="text-[9px] text-nexus-muted">
                <span className="text-nexus-accent">{s.symbol}</span>: {s.reason}
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
