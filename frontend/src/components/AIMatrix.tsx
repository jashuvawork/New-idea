import { Panel, ScoreBar } from './Panel';
import type { SymbolSnapshot } from '../types';

export function AIMatrix({ snap }: { snap: SymbolSnapshot }) {
  const components = [
    { label: 'Orderflow', weight: '30%', value: snap.orderflow.deltaVelocity },
    { label: 'Breadth', weight: '20%', value: snap.breadth.score },
    { label: 'Greeks/IV', weight: '15%', value: snap.greeks.ivRank },
    { label: 'Profile', weight: '15%', value: 65 },
    { label: 'Regime', weight: '10%', value: snap.regime === 'TREND_EXPANSION' ? 80 : 50 },
    { label: 'Velocity', weight: '10%', value: (snap.explosiveRunner.signal?.premiumVelocityPct || 0) * 25 },
  ];

  return (
    <Panel title="AI Matrix — TQS Breakdown">
      <div className="text-center mb-3">
        <span className="text-3xl font-mono font-bold text-nexus-accent">
          {snap.tradeQualityScore.toFixed(0)}
        </span>
        <span className="text-nexus-muted text-sm ml-1">/ 100</span>
      </div>
      <div className="space-y-2">
        {components.map((c) => (
          <div key={c.label}>
            <div className="flex justify-between text-[10px]">
              <span className="text-nexus-muted">{c.label} <span className="opacity-50">({c.weight})</span></span>
              <span className="font-mono">{Math.min(100, c.value).toFixed(0)}</span>
            </div>
            <ScoreBar value={Math.min(100, c.value)} />
          </div>
        ))}
      </div>
    </Panel>
  );
}
