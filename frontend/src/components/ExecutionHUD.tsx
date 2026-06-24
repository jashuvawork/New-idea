import { Panel, Metric, ScoreBar, BiasBadge } from './Panel';
import type { SymbolSnapshot, AutoTraderState } from '../types';

export function ExecutionHUD({ snap, auto }: { snap: SymbolSnapshot; auto: AutoTraderState }) {
  const tqs = snap.tradeQualityScore;
  const tqsColor = tqs >= 75 ? 'text-nexus-green' : tqs >= 60 ? 'text-nexus-yellow' : 'text-nexus-red';

  return (
    <Panel title="Execution HUD" badge={snap.marketPhase} badgeColor="bg-nexus-accent/80">
      <div className="grid grid-cols-2 gap-3">
        <Metric label="TQS" value={tqs.toFixed(0)} color={tqsColor} />
        <Metric label="Regime" value={snap.regime.replace(/_/g, ' ')} color="text-nexus-accent" />
        <Metric label="Spot" value={snap.spot?.toFixed(2) ?? '—'} />
        <Metric label="ATM" value={snap.atmStrike?.toFixed(0) ?? '—'} />
      </div>
      <div className="mt-3">
        <div className="flex justify-between text-[10px] text-nexus-muted mb-1">
          <span>Trade Quality</span>
          <span>{tqs}%</span>
        </div>
        <ScoreBar value={tqs} />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <BiasBadge bias={snap.breadth.bias} />
        <span className={`text-xs font-mono ${auto.running ? 'text-nexus-green' : 'text-nexus-red'}`}>
          {auto.running ? '● AUTO ON' : '○ AUTO STOPPED'}
        </span>
      </div>
      <div className="mt-2 text-[10px] text-nexus-muted">
        Mode: {auto.tradeMastermind.enhancedMode ? 'Enhanced Simple Profit' : 'Simple Profit'}
        {' · '}
        Target {snap.optimizedProfile.targetPoints}pt · Micro {snap.optimizedProfile.microTargetPoints}pt
      </div>
    </Panel>
  );
}
