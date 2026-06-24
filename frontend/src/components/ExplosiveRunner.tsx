import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

export function ExplosiveRunner({ snap }: { snap: SymbolSnapshot }) {
  const runner = snap.explosiveRunner;
  const watchlist = snap.explosiveRunnerWatchlist || [];

  return (
    <Panel
      title="Explosive Runner"
      badge={runner.candidate ? 'ACTIVE' : 'SCAN'}
      badgeColor={runner.candidate ? 'bg-nexus-green' : 'bg-gray-600'}
    >
      {runner.candidate && (
        <div className="mb-3 p-2 bg-nexus-green/10 border border-nexus-green/30 rounded">
          <div className="flex justify-between items-center">
            <span className="font-bold text-nexus-green">
              {runner.side} {runner.strike}
            </span>
            <span className="font-mono text-sm">₹{runner.premium?.toFixed(2)}</span>
          </div>
          <div className="flex gap-4 mt-1 text-xs text-nexus-muted">
            <span>Score: <b className="text-white">{runner.score}</b></span>
            <span>Vel: <b className="text-nexus-accent">{runner.signal?.premiumVelocityPct?.toFixed(1)}%</b></span>
            {runner.signal?.elite && <span className="text-nexus-yellow font-bold">ELITE</span>}
          </div>
        </div>
      )}
      <div className="max-h-48 overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-nexus-muted border-b border-nexus-border">
              <th className="text-left py-1">Strike</th>
              <th className="text-left">Side</th>
              <th className="text-right">Score</th>
              <th className="text-right">Vel%</th>
            </tr>
          </thead>
          <tbody>
            {watchlist.slice(0, 10).map((w, i) => (
              <tr key={i} className={`border-b border-nexus-border/50 ${w.elite ? 'bg-nexus-yellow/5' : ''}`}>
                <td className="py-1 font-mono">{w.strike}</td>
                <td className={w.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>{w.side}</td>
                <td className="text-right font-mono">{w.score}</td>
                <td className="text-right font-mono text-nexus-accent">{w.premiumVelocityPct.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
