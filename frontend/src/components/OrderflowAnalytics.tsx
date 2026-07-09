import { Panel, ScoreBar } from './Panel';
import type { SymbolSnapshot } from '../types';

export function OrderflowAnalytics({ snap }: { snap: SymbolSnapshot }) {
  const of = snap.orderflow ?? {};
  const signed = of.signedMomentumPct ?? 0;
  const metrics = [
    { label: 'Delta Velocity', value: of.deltaVelocity ?? 0 },
    { label: 'Volume Accel', value: of.volumeAcceleration ?? 0 },
    { label: 'Breakout Vel', value: of.breakoutVelocity ?? 0 },
    { label: 'Bid/Ask Imb', value: of.bidAskImbalance ?? 50 },
    { label: 'Tick Momentum', value: of.tickMomentum ?? 0 },
  ];

  return (
    <Panel title="Orderflow Analytics" badge="ENHANCED">
      {signed !== 0 ? (
        <div className="text-[9px] text-nexus-muted mb-2 font-mono">
          5m move {signed > 0 ? '+' : ''}{signed.toFixed(2)}%
          {snap.spotChart?.direction ? ` · chart ${snap.spotChart.direction}` : ''}
        </div>
      ) : null}
      <div className="space-y-2.5">
        {metrics.map((m) => (
          <div key={m.label}>
            <div className="flex justify-between text-[10px] mb-0.5">
              <span className="text-nexus-muted">{m.label}</span>
              <span className="font-mono font-bold">{m.value.toFixed(0)}</span>
            </div>
            <ScoreBar value={m.value} />
          </div>
        ))}
      </div>
    </Panel>
  );
}
