import { Panel, BiasBadge } from './Panel';
import type { AutoTraderState, ChopGuards, SpotChart, SymbolSnapshot } from '../types';

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

function chartRecommendedSide(chart: SpotChart): string {
  if (chart.direction === 'BULLISH') return 'CALL';
  if (chart.direction === 'BEARISH') return 'PUT';
  if (chart.momentum5Pct > 0.02) return 'CALL';
  if (chart.momentum5Pct < -0.02) return 'PUT';
  return 'WAIT';
}

function SymbolChartRow({ symbol, chart }: { symbol: string; chart: SpotChart }) {
  const rec = chartRecommendedSide(chart);
  const momTone =
    chart.momentum5Pct > 0.04 ? 'text-nexus-green' : chart.momentum5Pct < -0.04 ? 'text-nexus-red' : 'text-nexus-yellow';

  return (
    <div className="flex items-center justify-between gap-2 py-1.5 border-b border-nexus-border/50 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[11px] font-bold text-white w-14 shrink-0">{symbol}</span>
        <BiasBadge bias={chart.direction} />
        <span
          className={`text-[9px] font-semibold uppercase ${
            rec === 'CALL' ? 'text-nexus-green' : rec === 'PUT' ? 'text-nexus-red' : 'text-nexus-muted'
          }`}
        >
          {rec}
        </span>
      </div>
      <div className="text-right shrink-0 font-mono text-[9px]">
        <div className={momTone}>
          5m {chart.momentum5Pct > 0 ? '+' : ''}
          {chart.momentum5Pct.toFixed(2)}% · 15m {chart.momentum15Pct > 0 ? '+' : ''}
          {chart.momentum15Pct.toFixed(2)}%
        </div>
        <div className="text-nexus-muted">
          str {chart.trendStrength.toFixed(0)} · {chart.orPosition} OR · EMA {chart.emaBias}
        </div>
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
        <Flag label="Last-5 pause" active={Boolean(g.lastNTradesPaused)} tone="bad" />
        <Flag label="Whipsaw pause" active={Boolean(g.whipsawGuards?.whipsawPaused)} tone="bad" />
        <Flag label="Bear/side" active={Boolean(g.whipsawGuards?.bearishSideways)} tone="warn" />
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
              className={`h-full rounded-full ${
                capPct >= 100 ? 'bg-nexus-red' : capPct >= 75 ? 'bg-nexus-yellow' : 'bg-nexus-accent'
              }`}
              style={{ width: `${capPct}%` }}
            />
          </div>
        </div>
      )}

      {g.whipsawGuards && (g.whipsawGuards.flipFlops ?? 0) > 0 && (
        <div className="mb-3 text-[10px] text-nexus-yellow font-mono">
          CE↔PE flips (last {g.whipsawGuards.flipFlopLookback ?? 6}): {g.whipsawGuards.flipFlops}
          {g.whipsawGuards.whipsawPaused && g.whipsawGuards.whipsawPauseReason
            ? ` · ${g.whipsawGuards.whipsawPauseReason.replace(/_/g, ' ')}`
            : ''}
        </div>
      )}

      {g.lossStreak != null && g.lossStreak > 0 && (
        <div className="mb-3 text-[10px] text-nexus-yellow font-mono">
          Loss streak: {g.lossStreak}
          {g.pauseReason ? ` · ${g.pauseReason}` : ''}
        </div>
      )}

      {g.lastNTrades && (g.lastNTrades.count ?? 0) > 0 && (
        <div className="mb-3 p-2 rounded bg-black/30 text-[10px]">
          <div className="text-nexus-muted uppercase mb-1">
            Last {g.lastNTrades.lookback ?? 5} trades — best-trades gate
          </div>
          <div className="font-mono text-white mb-1">
            {g.lastNTrades.wins ?? 0}W / {g.lastNTrades.losses ?? 0}L · net ₹
            {(g.lastNTrades.netPnlInr ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            {g.lastNTrades.profitFactor != null ? ` · PF ${g.lastNTrades.profitFactor.toFixed(2)}` : ''}
          </div>
          {g.lastNTradesPaused && (
            <div className="text-nexus-red font-semibold mb-1">
              PAUSED — {g.lastNTradesPauseReason?.replace(/_/g, ' ')}
            </div>
          )}
          <div className="space-y-0.5 max-h-20 overflow-y-auto">
            {(g.lastNTrades.trades ?? []).map((t, i) => (
              <div key={`ln-${i}`} className="font-mono text-[9px] text-nexus-muted">
                {t.symbol} {t.side} {t.strike}{' '}
                <span className={t.pnlInr >= 0 ? 'text-nexus-green' : 'text-nexus-red'}>
                  ₹{t.pnlInr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                </span>
              </div>
            ))}
          </div>
          {g.controlledDailyCap != null && g.controlledDailyCap < 99 && (
            <div className="text-[9px] text-nexus-muted mt-1">
              Daily cap: {closed}/{g.controlledDailyCap} best trades only
            </div>
          )}
        </div>
      )}

      <div className="text-[10px] text-nexus-muted uppercase mb-1">NSE / BSE index moments</div>
      <div className="rounded bg-black/20 px-2 mb-3">
        {symbols.map((sym) => {
          const im = g.indexMoments?.[sym];
          if (!im) {
            return (
              <div key={`im-${sym}`} className="py-1.5 text-[10px] text-nexus-muted border-b border-nexus-border/50 last:border-0">
                {sym}: no index data
              </div>
            );
          }
          return (
            <div key={`im-${sym}`} className="py-1.5 border-b border-nexus-border/50 last:border-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-bold text-white">
                  {sym} <span className="text-nexus-muted font-normal">({im.exchange})</span>
                </span>
                {im.momentActive ? (
                  <span className="text-[9px] font-bold text-nexus-accent uppercase">MOMENT</span>
                ) : null}
              </div>
              <div className="text-[9px] text-nexus-muted font-mono mt-0.5">
                Gap {im.gapDirection?.replace('_', ' ') ?? '—'} {im.gapPct != null ? `${im.gapPct > 0 ? '+' : ''}${im.gapPct}%` : ''} ({im.gapSize ?? '—'})
              </div>
              <div className="text-[9px] text-nexus-muted font-mono">
                Stocks {im.constituentAdvancing ?? '—'}↑ / {im.constituentDeclining ?? '—'}↓ · breadth {im.constituentBreadthPct ?? '—'}% ({im.constituentBias ?? '—'})
              </div>
            </div>
          );
        })}
      </div>

      <div className="text-[10px] text-nexus-muted uppercase mb-1 mt-3">Index chart CE/PE alignment</div>
      <div className="rounded bg-black/20 px-2 mb-3">
        {symbols.map((sym) => {
          const chart = snapshots[sym]?.spotChart;
          if (!chart || !snapshots[sym]?.dataAvailable) {
            return (
              <div key={`chart-${sym}`} className="py-1.5 text-[10px] text-nexus-muted border-b border-nexus-border/50 last:border-0">
                {sym}: no chart data
              </div>
            );
          }
          return <SymbolChartRow key={`chart-${sym}`} symbol={sym} chart={chart} />;
        })}
      </div>

      <div className="text-[10px] text-nexus-muted uppercase mb-1">Blended breadth by symbol</div>
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
