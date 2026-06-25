import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

const GAP_COLORS: Record<string, string> = {
  GAP_UP: 'text-nexus-green',
  GAP_DOWN: 'text-nexus-red',
  FLAT: 'text-nexus-yellow',
};

const SIZE_COLORS: Record<string, string> = {
  EXTREME: 'bg-nexus-red/20 text-nexus-red border-nexus-red/40',
  LARGE: 'bg-orange-500/20 text-orange-400 border-orange-500/40',
  MODERATE: 'bg-nexus-yellow/20 text-nexus-yellow border-nexus-yellow/40',
  SMALL: 'bg-nexus-accent/10 text-nexus-accent border-nexus-accent/30',
  FLAT: 'bg-gray-800 text-gray-400 border-gray-700',
};

const RISK_COLORS: Record<string, string> = {
  HIGH: 'text-nexus-red',
  MEDIUM: 'text-nexus-yellow',
  LOW: 'text-nexus-green',
};

export function PremarketPanel({ snap }: { snap: SymbolSnapshot }) {
  const pm = snap.premarket;
  if (!pm) {
    return (
      <Panel title="Premarket Analysis" badge="N/A">
        <p className="text-xs text-nexus-muted py-2">
          Premarket gap analysis appears 9:00–9:15 IST and during the first 45 minutes after open.
        </p>
      </Panel>
    );
  }

  const gapColor = GAP_COLORS[pm.gapDirection] || 'text-gray-300';
  const sizeClass = SIZE_COLORS[pm.gapSize] || SIZE_COLORS.FLAT;

  return (
    <Panel
      title="Premarket Analysis"
      badge={pm.minutesToOpen > 0 ? `${pm.minutesToOpen}m to open` : 'LIVE OPEN'}
      badgeColor="bg-amber-500/80 text-black"
    >
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className={`p-2 rounded border text-center ${sizeClass}`}>
          <div className="text-[9px] uppercase opacity-80">Gap</div>
          <div className={`text-sm font-mono font-bold ${gapColor}`}>
            {pm.gapPct >= 0 ? '+' : ''}{pm.gapPct.toFixed(2)}%
          </div>
          <div className="text-[9px]">{pm.gapSize}</div>
        </div>
        <div className="p-2 rounded border border-nexus-border bg-black/30 text-center">
          <div className="text-[9px] text-nexus-muted">Indicative</div>
          <div className="text-sm font-mono font-bold">{pm.indicativeOpen.toLocaleString('en-IN')}</div>
          <div className="text-[9px] text-nexus-muted">vs {pm.prevClose.toLocaleString('en-IN')}</div>
        </div>
        <div className="p-2 rounded border border-nexus-border bg-black/30 text-center">
          <div className="text-[9px] text-nexus-muted">Gap pts</div>
          <div className={`text-sm font-mono font-bold ${gapColor}`}>
            {pm.gapPoints >= 0 ? '+' : ''}{pm.gapPoints.toFixed(1)}
          </div>
          <div className="text-[9px] text-nexus-muted">{pm.gapDirection.replace('_', ' ')}</div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 mb-3 text-[10px] font-mono">
        <div>
          <div className="text-nexus-muted">Pre-open H/L</div>
          <div className="font-bold">{pm.preOpenHigh.toFixed(0)} / {pm.preOpenLow.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-nexus-muted">Stock breadth</div>
          <div className="font-bold">{pm.constituentGapBreadth.toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-nexus-muted">Vol surge</div>
          <div className="font-bold text-nexus-accent">{pm.volumeSurgeScore.toFixed(0)}</div>
        </div>
        <div>
          <div className="text-nexus-muted">Explosion</div>
          <div className={`font-bold ${RISK_COLORS[pm.explosionRisk] || ''}`}>{pm.explosionRisk}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-2 text-[10px]">
        <span className="px-2 py-0.5 rounded bg-nexus-accent/10 text-nexus-accent font-bold">
          {pm.openPlay.replace(/_/g, ' ')}
        </span>
        <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-300">
          Auction: {pm.auctionBias}
        </span>
        <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-300">
          Confidence {pm.confidence.toFixed(0)}%
        </span>
      </div>

      {pm.gapLeaders.length > 0 && (
        <div className="text-[9px] mb-1">
          <span className="text-nexus-green font-bold">Leaders: </span>
          <span className="text-gray-400">{pm.gapLeaders.join(' · ')}</span>
        </div>
      )}
      {pm.gapLaggards.length > 0 && (
        <div className="text-[9px] mb-2">
          <span className="text-nexus-red font-bold">Laggards: </span>
          <span className="text-gray-400">{pm.gapLaggards.join(' · ')}</span>
        </div>
      )}

      {pm.scenarios.length > 0 && (
        <ul className="space-y-0.5 text-[9px] text-nexus-muted border-t border-nexus-border pt-2 mb-2">
          {pm.scenarios.map((s, i) => (
            <li key={i}>• {s}</li>
          ))}
        </ul>
      )}

      <p className="text-[10px] text-gray-400 leading-relaxed border-t border-nexus-border pt-2">
        {pm.analysis}
      </p>
    </Panel>
  );
}
