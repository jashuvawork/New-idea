import { Panel, ScoreBar } from './Panel';
import type { SymbolSnapshot } from '../types';

export function OrderflowAnalytics({ snap }: { snap: SymbolSnapshot }) {
  const of = snap.orderflow;
  const metrics = [
    { label: 'Delta Velocity', value: of.deltaVelocity },
    { label: 'Volume Accel', value: of.volumeAcceleration },
    { label: 'Breakout Vel', value: of.breakoutVelocity },
    { label: 'Bid/Ask Imb', value: of.bidAskImbalance },
    { label: 'Tick Momentum', value: of.tickMomentum },
  ];

  return (
    <Panel title="Orderflow Analytics" badge="ENHANCED">
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
