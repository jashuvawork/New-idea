import type { Sep917LiveChecklistSummary } from '../types';

function Flag({
  label,
  active,
  tone,
}: {
  label: string;
  active: boolean;
  tone: 'good' | 'bad' | 'warn' | 'neutral';
}) {
  const cls =
    tone === 'good'
      ? 'bg-nexus-green/15 text-nexus-green border-nexus-green/30'
      : tone === 'bad'
        ? 'bg-nexus-red/15 text-nexus-red border-nexus-red/30'
        : tone === 'warn'
          ? 'bg-nexus-yellow/15 text-nexus-yellow border-nexus-yellow/30'
          : 'bg-black/30 text-nexus-muted border-nexus-border';
  return (
    <span
      className={`text-[9px] px-1.5 py-0.5 rounded border ${cls} ${active ? '' : 'opacity-50'}`}
    >
      {label}
    </span>
  );
}

export function Sep917LiveChecklistSection({
  checklist,
}: {
  checklist?: Sep917LiveChecklistSummary | null;
}) {
  if (!checklist?.enabled) {
    return null;
  }

  return (
    <div className="mb-2 p-2 rounded border border-nexus-border/60 bg-black/20 text-[10px]">
      <div className="text-nexus-muted uppercase mb-1">Sep 9–17 live checklist</div>
      <div className="text-[9px] text-nexus-muted mb-2 leading-relaxed">
        {(checklist.stepsGuide ?? []).map((s) => (
          <div key={`cl-${s.id}`}>
            {s.id}. {s.title}: {s.question}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-1 mb-2">
        <Flag label="Symmetric capture" active={Boolean(checklist.symmetricBestTradeCapture)} tone="good" />
        <Flag label="Call rally unlock" active={Boolean(checklist.callRallyUnlockEnabled)} tone="neutral" />
        <Flag label="Put slide unlock" active={Boolean(checklist.putSlideUnlockEnabled)} tone="neutral" />
        <Flag label="Building rip helper" active={Boolean(checklist.buildingRipHelperEnabled)} tone="neutral" />
        <Flag label="Post-win chop FOMO" active={Boolean(checklist.postWinChopFomo)} tone="bad" />
      </div>
      {Object.entries(checklist.symbols ?? {}).map(([sym, meta]) => (
        <div key={`cl-sym-${sym}`} className="font-mono text-[9px] text-nexus-muted mb-0.5">
          {sym}: CE rally {meta.call?.indexRallyUnlock ? 'armed' : '—'} · PE slide{' '}
          {meta.put?.indexSlideUnlock ? 'armed' : '—'}
        </div>
      ))}
      {checklist.topCandidate ? (
        <div className="mt-2 pt-2 border-t border-nexus-border/40">
          <div className="text-nexus-muted uppercase text-[9px] mb-1">Building board top</div>
          <div className="font-mono text-white text-[10px]">
            {checklist.topCandidate.symbol} {checklist.topCandidate.side}{' '}
            {checklist.topCandidate.strike ?? ''} · lane {checklist.topCandidate.lane ?? '—'}{' '}
            {checklist.topCandidate.ready ? (
              <span className="text-nexus-green">READY</span>
            ) : (
              <span className="text-nexus-yellow">NOT READY</span>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
