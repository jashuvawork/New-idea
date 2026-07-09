import { Panel } from './Panel';
import type { SymbolSnapshot } from '../types';

const TIER_COLORS: Record<string, string> = {
  ELITE: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
  EXPLODING: 'bg-nexus-green/20 text-nexus-green border-nexus-green/50',
  BUILDING: 'bg-nexus-accent/20 text-nexus-accent border-nexus-accent/50',
  WATCH: 'bg-gray-800 text-nexus-muted border-nexus-border',
};

export function ExplosionRadar({ snap }: { snap: SymbolSnapshot }) {
  const alerts = snap.explosionAlerts || [];
  const top = snap.topExplosion;

  return (
    <Panel
      title="Explosion Radar"
      badge={top?.tier || 'SCAN'}
      badgeColor={top?.tier === 'ELITE' ? 'bg-yellow-500' : top?.tier === 'EXPLODING' ? 'bg-nexus-green' : 'bg-gray-600'}
    >
      {top && (
        <div className={`mb-3 p-2 rounded border ${TIER_COLORS[top.tier] || TIER_COLORS.WATCH}`}>
          <div className="flex justify-between items-center">
            <span className="font-bold text-sm">
              {top.side} {top.strike}
            </span>
            <span className="font-mono">₹{top.premium?.toFixed(2)}</span>
          </div>
          <div className="flex gap-3 mt-1 text-[10px]">
            <span>3s: <b>+{top.velocity3s?.toFixed(1)}%</b></span>
            <span>9s: <b>+{top.velocity9s?.toFixed(1)}%</b></span>
            <span>Vol: <b>×{top.volumeSurge?.toFixed(1)}</b></span>
            <span>Score: <b>{top.explosionScore}</b></span>
          </div>
          <div className="text-[9px] mt-1 opacity-80">{top.reason}</div>
        </div>
      )}

      <div className="max-h-44 overflow-y-auto space-y-1">
        {alerts.length === 0 ? (
          <p className="text-xs text-nexus-muted text-center py-2">Scanning chain for premium explosions…</p>
        ) : (
          alerts.slice(0, 8).map((a, i) => (
            <div
              key={i}
              className={`flex justify-between items-center text-[10px] p-1 rounded border ${
                TIER_COLORS[a.tier] || TIER_COLORS.WATCH
              }`}
            >
              <span>
                <span className={`font-bold ${a.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}`}>
                  {a.side} {a.strike}
                </span>
                <span className="ml-2 opacity-70">
                {a.tier}
                {a.allDayExplosion ? ' · ALL-DAY' : ''}
                {a.morningCapture ? ' · AM' : ''}
                {a.afternoonCapture ? ' · PM' : ''}
              </span>
              </span>
              <span className="font-mono">
                +{a.velocity3s?.toFixed(1)}%
                {a.peakMovePct != null && a.peakMovePct > (a.dailyMovePct ?? 0)
                  ? ` · peak ${a.peakMovePct.toFixed(0)}%`
                  : ''}
                {' · '}
                {a.explosionScore}
              </span>
            </div>
          ))
        )}
      </div>

      <div className="mt-2 text-[9px] text-nexus-muted border-t border-nexus-border pt-1">
        ALL-DAY · AM · PM = capture windows · Auto-enters EXPLODING/ELITE/BUILDING when tradeable
      </div>
    </Panel>
  );
}
