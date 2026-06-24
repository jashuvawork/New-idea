import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

export function OptionHeatmap({ snap }: { snap: SymbolSnapshot }) {
  const rows = snap.heatmap.filter((h) => Math.abs(h.strike - (snap.atmStrike || 0)) <= 200);

  return (
    <Panel title="Option Heatmap">
      <div className="max-h-56 overflow-y-auto">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="text-nexus-muted border-b border-nexus-border">
              <th className="text-left py-1">Strike</th>
              <th className="text-right">Call OI</th>
              <th className="text-right">Put OI</th>
              <th className="text-right">Liq</th>
              <th className="text-right">Sweep</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr
                key={h.strike}
                className={`border-b border-nexus-border/30 ${h.gammaWall ? 'bg-nexus-yellow/10' : ''} ${
                  h.strike === snap.atmStrike ? 'bg-nexus-accent/10' : ''
                }`}
              >
                <td className="py-0.5 font-mono font-bold">{h.strike}</td>
                <td className="text-right font-mono text-nexus-green">{(h.callOi / 1000).toFixed(0)}k</td>
                <td className="text-right font-mono text-nexus-red">{(h.putOi / 1000).toFixed(0)}k</td>
                <td className="text-right">
                  <span
                    className="inline-block w-8 h-1.5 rounded"
                    style={{
                      background: `linear-gradient(90deg, #06b6d4 ${h.liquidityScore}%, #1f2937 ${h.liquidityScore}%)`,
                    }}
                  />
                </td>
                <td className="text-right font-mono text-nexus-yellow">{h.sweepRisk.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
