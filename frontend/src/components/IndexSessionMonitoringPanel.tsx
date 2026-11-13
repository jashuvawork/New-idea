import type { AutoTraderState, ChopGuards, DeploymentStatus } from '../types';

type IndexLegRow = {
  dominantLeg?: string;
  bullishOptionSide?: string | null;
  rallyPoints?: number;
  slidePoints?: number;
  dominantTrendFlipped?: boolean;
  dominantTrendPrevious?: string;
  callRallyUnlockArmed?: boolean;
  putSlideUnlockArmed?: boolean;
  slideCaptureLane?: { armed?: boolean; reason?: string };
  alignedBookPicks?: Array<{
    strike?: number;
    side?: string;
    tier?: string;
    explosionScore?: number;
    localBasePct?: number;
    nearBase676?: boolean;
    momentType?: string;
  }>;
  timingHint?: string;
};

function legTone(leg?: string): string {
  const u = (leg || '').toUpperCase();
  if (u === 'RALLY') return 'text-nexus-green';
  if (u === 'SLIDE') return 'text-nexus-red';
  return 'text-nexus-yellow';
}

function IndexCard({ symbol, row }: { symbol: string; row: IndexLegRow }) {
  const side = row.bullishOptionSide;
  const picks = row.alignedBookPicks ?? [];
  return (
    <div className="rounded-lg border border-nexus-border/60 bg-black/30 p-3">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="text-xs font-bold text-white">{symbol}</span>
        <span className={`text-[10px] font-mono font-semibold uppercase ${legTone(row.dominantLeg)}`}>
          {row.dominantLeg ?? 'NEUTRAL'}
        </span>
        {row.dominantTrendFlipped ? (
          <span className="text-[9px] px-1.5 py-0.5 rounded border border-nexus-accent/50 text-nexus-accent">
            FLIP {row.dominantTrendPrevious ?? '?'} → {row.dominantLeg}
          </span>
        ) : null}
        {side ? (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-nexus-accent/15 text-nexus-accent border border-nexus-accent/40">
            Bullish side: {side}
          </span>
        ) : (
          <span className="text-[9px] text-nexus-muted">No aligned side</span>
        )}
      </div>
      <p className="text-[10px] text-nexus-muted font-mono mb-2">
        Rally {row.rallyPoints ?? '—'} pts · Slide {row.slidePoints ?? '—'} pts
        {row.callRallyUnlockArmed ? ' · CE unlock' : ''}
        {row.putSlideUnlockArmed ? ' · PE unlock' : ''}
        {row.slideCaptureLane?.armed ? ' · slide lane ON' : ''}
      </p>
      {row.timingHint ? (
        <p className="text-[10px] text-gray-300 leading-snug mb-2 border-l-2 border-nexus-border pl-2">
          {row.timingHint}
        </p>
      ) : null}
      <p className="text-[9px] uppercase tracking-wide text-nexus-muted mb-1">#676-aligned book (radar)</p>
      {picks.length === 0 ? (
        <p className="text-[10px] text-gray-500">No explosion on aligned side yet — wait for base pad.</p>
      ) : (
        <ul className="space-y-1">
          {picks.map((p) => (
            <li
              key={`${p.side}-${p.strike}`}
              className="flex flex-wrap gap-2 text-[10px] font-mono text-gray-200"
            >
              <span className="text-nexus-accent">
                {p.side} {p.strike}
              </span>
              <span className="text-nexus-muted">{p.tier || '—'}</span>
              <span>expl {p.explosionScore ?? '—'}</span>
              <span>base {p.localBasePct ?? '—'}%</span>
              {p.nearBase676 ? (
                <span className="text-nexus-green text-[9px]">PAD OK</span>
              ) : (
                <span className="text-nexus-yellow text-[9px]">chase?</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function IndexSessionMonitoringPanel({
  auto,
  deployment,
}: {
  auto: AutoTraderState;
  deployment: DeploymentStatus | null;
}) {
  const chop = (auto.chopGuards ?? {}) as ChopGuards & {
    indexSessionMonitoring?: {
      enabled?: boolean;
      updatedAtIst?: string;
      openCautionWindow?: boolean;
      symbols?: Record<string, IndexLegRow>;
      openSetupGuards?: Record<string, unknown>;
      slideCaptureLanePolicy?: { enabled?: boolean; windowIst?: string; minEliteScore?: number };
    };
  };
  const mon = chop.indexSessionMonitoring;
  const flags = deployment?.flags as Record<string, unknown> | undefined;
  const guards = flags?.openSetupGuards as Record<string, unknown> | undefined;
  const lane = flags?.indexSlideCaptureLane as { enabled?: boolean; windowIst?: string } | undefined;

  if (!mon?.enabled) {
    return (
      <div className="audit-panel">
        <h2 className="audit-panel-title">Index moment &amp; #676 book</h2>
        <p className="text-[11px] text-nexus-muted mt-2">
          Index narrative disabled or warming up — needs live NIFTY/SENSEX snapshots.
        </p>
      </div>
    );
  }

  const symbols = Object.entries(mon.symbols ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="audit-panel">
      <PanelTitle />
      <div className="flex flex-wrap gap-2 mt-2 mb-3">
        <MetaChip label="Updated IST" value={mon.updatedAtIst ?? '—'} />
        <MetaChip
          label="Open caution"
          value={mon.openCautionWindow ? '09:15–09:45' : 'off'}
          warn={Boolean(mon.openCautionWindow)}
        />
        <MetaChip
          label="Side align"
          value={String(guards?.sideAlignUntilIst ?? '09:30')}
        />
        <MetaChip
          label="Slide lane"
          value={lane?.enabled ? lane.windowIst ?? 'on' : 'off'}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {symbols.map(([sym, row]) => (
          <IndexCard key={sym} symbol={sym} row={row} />
        ))}
      </div>
      <p className="text-[9px] text-nexus-muted mt-3 leading-relaxed">
        Flow: index leg → bullish CE/PE side → #676 pad band on aligned explosions only. Counter-side needs flip
        confirm.
      </p>
    </div>
  );
}

function PanelTitle() {
  return <h2 className="audit-panel-title">Index moment &amp; #676-aligned book</h2>;
}

function MetaChip({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <span
      className={`text-[9px] px-2 py-0.5 rounded border font-mono ${
        warn
          ? 'border-nexus-yellow/40 text-nexus-yellow bg-nexus-yellow/5'
          : 'border-nexus-border/50 text-gray-400 bg-black/20'
      }`}
    >
      {label}: {value}
    </span>
  );
}
