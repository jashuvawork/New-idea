import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

export function MarketProfilePanel({ snap }: { snap: SymbolSnapshot }) {
  const mp = snap.marketProfile;
  if (!mp) {
    return (
      <Panel title="Market Profile">
        <p className="text-xs text-nexus-muted text-center py-4">Profile loading…</p>
      </Panel>
    );
  }

  return (
    <Panel title="Market Profile">
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div><span className="text-nexus-muted">POC</span> <span className="font-mono font-bold ml-2">{mp.poc.toFixed(0)}</span></div>
        <div><span className="text-nexus-muted">VAH</span> <span className="font-mono font-bold ml-2 text-nexus-green">{mp.vah.toFixed(0)}</span></div>
        <div><span className="text-nexus-muted">VAL</span> <span className="font-mono font-bold ml-2 text-nexus-red">{mp.val.toFixed(0)}</span></div>
        <div><span className="text-nexus-muted">ORH</span> <span className="font-mono font-bold ml-2">{mp.openingRangeHigh.toFixed(0)}</span></div>
        <div><span className="text-nexus-muted">ORL</span> <span className="font-mono font-bold ml-2">{mp.openingRangeLow.toFixed(0)}</span></div>
        <div><span className="text-nexus-muted">Session</span> <span className="font-mono font-bold ml-2 text-nexus-accent">{snap.optimizedProfile?.sessionLabel ?? '—'}</span></div>
      </div>
    </Panel>
  );
}
