import { Panel, BiasBadge } from './Panel';
import type { AutoTraderState, ChopGuards, SymbolSnapshot } from '../types';

const TONE_BADGE: Record<string, string> = {
  rally: 'bg-nexus-accent/90 text-black',
  chop: 'bg-nexus-yellow/80 text-black',
  bullish: 'bg-nexus-green/80 text-white',
  bearish: 'bg-nexus-red/80 text-white',
  mixed: 'bg-purple-500/80 text-white',
  normal: 'bg-gray-600/80 text-white',
};

function Flag({
  label,
  active,
  tone = 'neutral',
}: {
  label: string;
  active: boolean;
  tone?: 'good' | 'bad' | 'warn' | 'neutral';
}) {
  const activeClass =
    tone === 'good'
      ? 'border-nexus-green/50 bg-nexus-green/10 text-nexus-green'
      : tone === 'bad'
        ? 'border-nexus-red/50 bg-nexus-red/10 text-nexus-red'
        : tone === 'warn'
          ? 'border-nexus-yellow/50 bg-nexus-yellow/10 text-nexus-yellow'
          : 'border-nexus-border bg-black/20 text-nexus-muted';

  return (
    <span
      className={`text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border ${
        active ? activeClass : 'border-nexus-border/40 text-gray-600 bg-black/10'
      }`}
    >
      {label}
    </span>
  );
}

function SymbolBreadthRow({
  symbol,
  info,
}: {
  symbol: string;
  info: { bias: string; score: number; aligned: boolean; regime: string };
}) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-nexus-border/50 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[11px] font-bold text-white w-14 shrink-0">{symbol}</span>
        <BiasBadge bias={info.bias} />
        {info.aligned ? (
          <span className="text-[9px] text-nexus-accent font-semibold">ALIGNED</span>
        ) : null}
      </div>
      <div className="text-right shrink-0">
        <div className="text-[10px] font-mono text-gray-300">{info.score.toFixed(0)} breadth</div>
        <div className="text-[9px] text-nexus-muted">{info.regime.replace('_', ' ')}</div>
      </div>
    </div>
  );
}

export function DayModePanel({
  auto,
  snapshots,
  symbols,
  chopEnabled,
}: {
  auto: AutoTraderState;
  snapshots: Record<string, SymbolSnapshot>;
  symbols: readonly string[];
  chopEnabled?: boolean;
}) {
  const g: ChopGuards = auto.chopGuards ?? {};
  const mode = g.dayMode ?? 'NORMAL';
  const tone = g.dayModeTone ?? 'normal';
  const badgeClass = TONE_BADGE[tone] ?? TONE_BADGE.normal;

  const breadth = g.symbolBreadth ?? {};
  const cap = g.dailyTradeCap ?? 999;
  const closed = g.closedTrades ?? auto.closedPaperTrades?.length ?? 0;
  const capPct = cap > 0 && cap < 999 ? Math.min(100, (closed / cap) * 100) : 0;

  return (
    <Panel title="Day Mode" badge={mode} badgeColor={badgeClass}>
      <p className="text-[10px] text-nexus-muted leading-relaxed mb-3">
        {g.dayModeHint ?? 'Live session classification from breadth, regime, and time windows.'}
      </p>

      <div className="flex flex-wrap gap-1 mb-3">
        <Flag label="Chop" active={Boolean(g.chopSession)} tone="warn" />
        <Flag label="Rally 11–13:45" active={Boolean(g.momentumRallyWindow)} tone="good" />
        <Flag label="Pre-10" active={Boolean(g.beforePrimaryWindow)} tone="warn" />
        <Flag label="Open caution" active={Boolean(g.openCautionWindow)} tone="warn" />
        <Flag label="Midday chop" active={Boolean(g.middayChopWindow)} tone="warn" />
        <Flag label="Loss pause" active={Boolean(g.sessionPaused)} tone="bad" />
        <Flag label="Cap hit" active={Boolean(g.tradeCapReached)} tone="bad" />
        <Flag label="Guards on" active={chopEnabled !== false && g.guardsEnabled !== false} tone="neutral" />
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3 text-[10px]">
        <div className="p-2 rounded bg-black/30">
          <div className="text-nexus-muted uppercase mb-0.5">Session</div>
          <div className="font-mono text-white">{g.sessionLabel ?? '—'}</div>
          <div className="text-nexus-muted">
            {g.sessionTargetPoints != null ? `${g.sessionTargetPoints}pt target` : ''}
          </div>
        </div>
        <div className="p-2 rounded bg-black/30">
          <div className="text-nexus-muted uppercase mb-0.5">Trade cap</div>
          <div className="font-mono text-white">
            {closed}/{cap >= 999 ? '∞' : cap}
          </div>
          <div className="text-nexus-muted">{g.dailyTradeCapLabel ?? 'normal'}</div>
        </div>
      </div>

      {cap < 999 && (
        <div className="mb-3">
          <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                capPct >= 100 ? 'bg-nexus-red' : capPct >= 75 ? 'bg-nexus-yellow' : 'bg-nexus-accent'
              }`}
              style={{ width: `${capPct}%` }}
            />
          </div>
        </div>
      )}

      {g.lossStreak != null && g.lossStreak > 0 && (
        <div className="mb-3 text-[10px] text-nexus-yellow font-mono">
          Loss streak: {g.lossStreak}
          {g.pauseReason ? ` · ${g.pauseReason}` : ''}
        </div>
      )}

      <div className="text-[10px] text-nexus-muted uppercase mb-1">Breadth by symbol</div>
      <div className="rounded bg-black/20 px-2">
        {symbols.map((sym) => {
          const info = breadth[sym] ?? (snapshots[sym]?.dataAvailable
            ? {
                bias: snapshots[sym].breadth?.bias ?? 'NEUTRAL',
                score: snapshots[sym].breadth?.score ?? 50,
                aligned: snapshots[sym].breadth?.aligned ?? false,
                regime: snapshots[sym].regime ?? 'RANGE_BOUND',
              }
            : null);
          if (!info) {
            return (
              <div key={sym} className="py-1.5 text-[10px] text-nexus-muted">
                {sym}: no data
              </div>
            );
          }
          return <SymbolBreadthRow key={sym} symbol={sym} info={info} />;
        })}
      </div>
    </Panel>
  );
}
