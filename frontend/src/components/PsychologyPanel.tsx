import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

interface PsychologyData {
  label?: string;
  fearGreedIndex?: number;
  exitBias?: string;
  analysis?: string;
}

interface AdaptiveExitHint {
  mlWinProb?: number;
  targetPoints?: number;
  stopPoints?: number;
  trailArmPoints?: number;
  trailKeepRatio?: number;
  targetPct?: number;
  stopPct?: number;
  reasoning?: string[];
}

export function PsychologyPanel({ snap }: { snap: SymbolSnapshot }) {
  const ps = (snap.psychology || {}) as PsychologyData;
  const hint = (snap.adaptiveExitHint || {}) as AdaptiveExitHint;

  const label = ps.label || 'NEUTRAL';
  const labelColor =
    label === 'EUPHORIA' || label === 'GREED'
      ? 'text-nexus-green'
      : label === 'FEAR' || label === 'CAUTION'
        ? 'text-nexus-red'
        : 'text-nexus-yellow';

  return (
    <Panel title="Psychology & Adaptive Exits" badge={label}>
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div>
          <div className="text-[10px] text-nexus-muted">Fear/Greed</div>
          <div className="text-sm font-mono font-bold">{ps.fearGreedIndex ?? 50}</div>
        </div>
        <div>
          <div className="text-[10px] text-nexus-muted">ML Win Prob</div>
          <div className="text-sm font-mono font-bold text-nexus-accent">
            {hint.mlWinProb != null ? `${(hint.mlWinProb * 100).toFixed(0)}%` : '—'}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-nexus-muted">Exit Bias</div>
          <div className={`text-xs font-bold ${labelColor}`}>{ps.exitBias || 'BALANCED'}</div>
        </div>
      </div>

      {hint.targetPoints != null ? (
        <div className="grid grid-cols-3 gap-2 mb-2 text-[10px] font-mono">
          <div className="p-1.5 rounded bg-nexus-green/10 border border-nexus-green/30">
            <div className="text-nexus-muted">TP</div>
            <div className="font-bold text-nexus-green">+{hint.targetPoints}pt</div>
          </div>
          <div className="p-1.5 rounded bg-nexus-red/10 border border-nexus-red/30">
            <div className="text-nexus-muted">SL</div>
            <div className="font-bold text-nexus-red">−{hint.stopPoints}pt</div>
          </div>
          <div className="p-1.5 rounded bg-nexus-accent/10 border border-nexus-accent/30">
            <div className="text-nexus-muted">Trail</div>
            <div className="font-bold text-nexus-accent">
              @{hint.trailArmPoints}pt / {((hint.trailKeepRatio ?? 0.55) * 100).toFixed(0)}%
            </div>
          </div>
        </div>
      ) : hint.targetPct != null ? (
        <div className="grid grid-cols-2 gap-2 mb-2 text-[10px] font-mono">
          <div className="p-1.5 rounded bg-nexus-green/10">TP +{hint.targetPct}%</div>
          <div className="p-1.5 rounded bg-nexus-red/10">SL −{hint.stopPct}%</div>
        </div>
      ) : null}

      {ps.analysis && (
        <p className="text-[10px] text-gray-400 leading-relaxed border-t border-nexus-border pt-2">
          {ps.analysis}
        </p>
      )}

      {hint.reasoning && hint.reasoning.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[9px] text-nexus-muted">
          {hint.reasoning.slice(0, 3).map((r, i) => (
            <li key={i}>• {r}</li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
