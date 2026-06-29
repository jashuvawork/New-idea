import { Panel } from './Panel';
import type { AutoTraderState, CapitalAllocation, DailyProfitGate } from '../types';

export function RiskEngine({ auto }: { auto: AutoTraderState }) {
  const blocks = auto.calibrationBlocks;
  const skipped = auto.skipped || [];
  const cap = (auto.capitalAllocation || {}) as CapitalAllocation;
  const gate = (auto.dailyProfitGate || {}) as DailyProfitGate;

  const sessionPnl = gate.sessionPnlInr ?? auto.dailyReport.netPnlInr;
  const minTarget = gate.minTargetInr ?? gate.targetInr ?? 22_000;
  const capitalBase = gate.capitalBaseInr ?? 200_000;
  const lockedFloor = gate.lockedFloorInr ?? gate.trailFloorInr ?? 0;
  const gateOk = gate.newEntriesAllowed !== false;
  const lotSizes = cap.lotSizes || {};
  const lotShort: Record<string, string> = { NIFTY: 'N', BANKNIFTY: 'BN', SENSEX: 'SX' };
  const lotLabel = Object.keys(lotSizes).length
    ? Object.entries(lotSizes).map(([s, n]) => `${lotShort[s] || s}${n}`).join(' · ')
    : 'Upstox pending';

  const stages = gate.stages || [
    { stage: 1, pct: 0.55, thresholdInr: capitalBase * 0.55, reached: false, label: '55% lock' },
    { stage: 2, pct: 0.88, thresholdInr: capitalBase * 0.88, reached: false, label: '88% lock' },
    { stage: 3, pct: 1.12, thresholdInr: capitalBase * 1.12, reached: false, label: '112% lock' },
  ];

  const minProgress = Math.min(100, (sessionPnl / minTarget) * 100);

  return (
    <Panel title="Capital & Stage Locks" badge={gate.status || 'ACTIVE'}>
      <div className="mb-3 p-2 rounded bg-black/30 border border-nexus-border text-[10px]">
        <div className="flex justify-between mb-1">
          <span className="text-nexus-muted">Upstox margin</span>
          <span className="font-mono font-bold text-nexus-accent">
            ₹{(cap.availableMarginInr || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className="flex justify-between text-[9px] text-nexus-muted">
          <span>85% cap/trade · ₹{((cap.perTradeCapitalInr as number) || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
          <span>Lots {cap.minLots ?? 1}–{cap.maxLots ?? '∞'} · {lotLabel}</span>
        </div>
      </div>

      <div className="mb-2">
        <div className="flex justify-between text-[10px] mb-1">
          <span className="text-nexus-muted">
            Session PnL · min ₹{(minTarget / 1000).toFixed(0)}K
            {gate.minTargetHit ? ' ✓' : ''}
          </span>
          <span className={`font-mono font-bold ${sessionPnl >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
            ₹{sessionPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded overflow-hidden mb-2">
          <div
            className={`h-full transition-all ${minProgress >= 100 ? 'bg-nexus-green' : 'bg-nexus-accent'}`}
            style={{ width: `${Math.min(100, minProgress)}%` }}
          />
        </div>
        <div className="grid grid-cols-2 gap-1 text-[9px]">
          {stages.slice(0, 3).map((s) => (
            <div
              key={s.stage}
              className={`px-1.5 py-1 rounded border ${
                s.reached ? 'border-nexus-green/40 bg-nexus-green/10 text-nexus-green' : 'border-nexus-border text-nexus-muted'
              }`}
            >
              <span className="font-semibold">S{s.stage}</span> ₹{s.thresholdInr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </div>
          ))}
          <div
            className={`px-1.5 py-1 rounded border ${
              (gate.currentStage ?? 0) >= 4
                ? 'border-nexus-green/40 bg-nexus-green/10 text-nexus-green'
                : 'border-nexus-border text-nexus-muted'
            }`}
          >
            <span className="font-semibold">S4</span> Peak ₹{(gate.bestPnlInr || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
        </div>
        <div className="flex justify-between text-[9px] text-nexus-muted mt-1">
          <span>Peak ₹{(gate.bestPnlInr || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
          <span>Floor ₹{lockedFloor.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
        </div>
      </div>

      <div className={`text-[10px] p-1.5 rounded mb-2 ${gateOk ? 'bg-nexus-green/10 text-nexus-green' : 'bg-nexus-red/10 text-nexus-red'}`}>
        {gate.message || (gateOk ? 'Entries active — no upside cap' : 'New entries paused')}
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
