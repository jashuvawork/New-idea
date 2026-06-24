import { Panel, Metric } from './Panel';
import type { SymbolSnapshot } from '../types';

export function GreeksIV({ snap }: { snap: SymbolSnapshot }) {
  const g = snap.greeks;
  return (
    <Panel title="Greeks & IV">
      <div className="grid grid-cols-3 gap-2">
        <Metric label="Delta" value={g.delta.toFixed(3)} />
        <Metric label="Gamma" value={g.gamma.toFixed(4)} />
        <Metric label="Theta" value={g.theta.toFixed(1)} />
        <Metric label="Vega" value={g.vega.toFixed(1)} />
        <Metric label="IV Exp" value={`${g.ivExpansion.toFixed(2)}x`} color="text-nexus-accent" />
        <Metric label="IV Rank" value={`${g.ivRank.toFixed(0)}%`} />
      </div>
    </Panel>
  );
}
