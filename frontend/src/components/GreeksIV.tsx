import { Panel, Metric } from './Panel';
import type { SymbolSnapshot } from '../types';

export function GreeksIV({ snap }: { snap: SymbolSnapshot }) {
  const g = snap.greeks;
  if (!g) {
    return (
      <Panel title="Greeks & IV">
        <p className="text-xs text-nexus-muted text-center py-4">Greeks loading…</p>
      </Panel>
    );
  }

  return (
    <Panel title="Greeks & IV">
      <div className="grid grid-cols-3 gap-2">
        <Metric label="Delta" value={(g.delta ?? 0).toFixed(3)} />
        <Metric label="Gamma" value={(g.gamma ?? 0).toFixed(4)} />
        <Metric label="Theta" value={(g.theta ?? 0).toFixed(1)} />
        <Metric label="Vega" value={(g.vega ?? 0).toFixed(1)} />
        <Metric label="IV Exp" value={`${(g.ivExpansion ?? 0).toFixed(2)}x`} color="text-nexus-accent" />
        <Metric label="IV Rank" value={`${(g.ivRank ?? 0).toFixed(0)}%`} />
      </div>
    </Panel>
  );
}
