import { Panel, Metric, ScoreBar, BiasBadge } from './Panel';
import type { SymbolSnapshot, AutoTraderState } from '../types';

export function ExecutionHUD({ snap, auto }: { snap: SymbolSnapshot; auto: AutoTraderState }) {
  const tqs = snap.tradeQualityScore ?? 0;
  const tqsColor = tqs >= 75 ? 'text-nexus-green' : tqs >= 60 ? 'text-nexus-yellow' : 'text-nexus-red';
  const pm = snap.premarket;
  const profile = snap.optimizedProfile;
  const phaseBadge =
    snap.marketPhase === 'PREMARKET'
      ? 'bg-amber-500/80 text-black'
      : 'bg-nexus-accent/80';

  return (
    <Panel title="Execution HUD" badge={snap.marketPhase ?? 'MARKET'} badgeColor={phaseBadge}>
      {pm && (
        <div className="mb-3 p-2 rounded border border-amber-500/30 bg-amber-500/5 text-[10px]">
          <div className="flex justify-between font-mono">
            <span className={pm.gapDirection === 'GAP_UP' ? 'text-nexus-green' : pm.gapDirection === 'GAP_DOWN' ? 'text-nexus-red' : 'text-nexus-yellow'}>
              Gap {pm.gapPct >= 0 ? '+' : ''}{pm.gapPct.toFixed(2)}% ({pm.gapSize})
            </span>
            <span className="text-nexus-accent">{pm.openPlay.replace(/_/g, ' ')}</span>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Metric label="TQS" value={tqs.toFixed(0)} color={tqsColor} />
        <Metric label="Regime" value={(snap.regime ?? 'UNKNOWN').replace(/_/g, ' ')} color="text-nexus-accent" />
        <Metric label="Spot" value={snap.spot?.toFixed(2) ?? '—'} />
        <Metric label="ATM" value={snap.atmStrike?.toFixed(0) ?? '—'} />
      </div>
      <div className="mt-3">
        <div className="flex justify-between text-[10px] text-nexus-muted mb-1">
          <span>Trade Quality</span>
          <span>{tqs}%</span>
        </div>
        <ScoreBar value={tqs} />
      </div>
      <div className="mt-3 flex items-center justify-between">
        <BiasBadge bias={snap.breadth?.bias ?? 'NEUTRAL'} />
        <span className={`text-xs font-mono ${auto.running && auto.autoTradingEnabled ? 'text-nexus-green' : 'text-nexus-red'}`}>
          {auto.running && auto.autoTradingEnabled ? '● AUTO ON' : '○ AUTO STOPPED'}
        </span>
      </div>
      <div className="mt-2 text-[10px] text-nexus-muted">
        Mode: {auto.tradeMastermind?.enhancedMode ? 'Enhanced Simple Profit' : 'Simple Profit'}
        {profile ? (
          <>
            {' · '}
            Target {profile.targetPoints}pt · Micro {profile.microTargetPoints}pt
          </>
        ) : null}
      </div>
    </Panel>
  );
}
