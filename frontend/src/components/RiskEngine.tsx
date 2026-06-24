import { Panel } from './Panel';
import type { AutoTraderState } from '../types';

export function RiskEngine({ auto }: { auto: AutoTraderState }) {
  const blocks = auto.calibrationBlocks;
  const skipped = auto.skipped || [];

  return (
    <Panel title="Risk Engine">
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
        <div className="flex justify-between">
          <span className="text-nexus-muted">Live Trading</span>
          <span className={auto.liveTradingEnabled ? 'text-nexus-yellow' : 'text-nexus-muted'}>
            {auto.liveTradingEnabled ? 'ENABLED' : 'Disabled'}
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
