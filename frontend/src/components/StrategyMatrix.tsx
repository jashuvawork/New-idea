import { Panel, ScoreBar } from './Panel';
import type { SymbolSnapshot } from '../types';

export function StrategyMatrix({ snap }: { snap: SymbolSnapshot }) {
  const matrix = snap.strategyMatrix || [];
  const ml = snap.mlInsights || {};

  return (
    <Panel title="AI Strategy Matrix" badge={`${ml.activeStrategies || 0} active`} badgeColor="bg-purple-600">
      <div className="flex gap-4 mb-3 text-[10px]">
        <span className="text-nexus-muted">PCR: <b className="text-white">{snap.pcr?.toFixed(2) ?? '—'}</b></span>
        <span className="text-nexus-muted">Max Pain: <b className="text-nexus-accent">{snap.maxPain?.toFixed(0) ?? '—'}</b></span>
        <span className="text-nexus-muted">ML: <b className={ml.modelTrained ? 'text-nexus-green' : 'text-nexus-yellow'}>{ml.modelTrained ? 'Trained' : 'Bootstrap'}</b></span>
      </div>

      <div className="max-h-52 overflow-y-auto space-y-1.5">
        {matrix.map((s) => (
          <div
            key={s.id}
            className={`p-1.5 rounded border text-[10px] ${
              s.status === 'active'
                ? 'border-nexus-green/40 bg-nexus-green/5'
                : 'border-nexus-border/50 bg-black/10'
            }`}
          >
            <div className="flex justify-between items-center">
              <span className="font-bold text-gray-200">{s.name}</span>
              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                s.status === 'active' ? 'bg-nexus-green/20 text-nexus-green' : 'bg-gray-800 text-nexus-muted'
              }`}>
                {s.status === 'active' ? `${s.confidence?.toFixed(0)}%` : s.status}
              </span>
            </div>
            {s.status === 'active' && (
              <div className="flex gap-3 mt-0.5 text-nexus-muted">
                <span>ML: {(s.mlProbability * 100).toFixed(0)}%</span>
                {s.sessionMatch && <span className="text-nexus-accent">Session ✓</span>}
              </div>
            )}
            {s.status === 'active' && <ScoreBar value={s.confidence || 0} />}
          </div>
        ))}
      </div>

      {ml.featureImportance && Object.keys(ml.featureImportance).length > 0 && (
        <div className="mt-2 pt-2 border-t border-nexus-border">
          <div className="text-[9px] text-nexus-muted uppercase mb-1">Top ML Features</div>
          <div className="flex flex-wrap gap-1">
            {Object.entries(ml.featureImportance as Record<string, number>)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 4)
              .map(([name, imp]) => (
                <span key={name} className="text-[8px] bg-purple-900/30 text-purple-300 px-1.5 py-0.5 rounded">
                  {name}: {(imp * 100).toFixed(0)}%
                </span>
              ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
