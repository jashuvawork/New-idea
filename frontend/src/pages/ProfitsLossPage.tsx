import type {
  AutoTraderState,
  DeploymentStatus,
  PaperTrade,
  PostExitLtpMonitor,
  SymbolSnapshot,
} from '../types';

function readPostExitMonitor(trade: PaperTrade): PostExitLtpMonitor | null {
  const top = trade.postExitLtpMonitor;
  if (top && typeof top === 'object') return top;
  const nested = trade.entryContext?.postExitLtpMonitor;
  if (nested && typeof nested === 'object') return nested as PostExitLtpMonitor;
  return null;
}

function peakWhileOpen(trade: PaperTrade): number | null {
  const v = trade.maxLtp;
  return v != null && Number.isFinite(v) && v > 0 ? v : null;
}

function postExitPeak(trade: PaperTrade): number | null {
  const mon = readPostExitMonitor(trade);
  const v = mon?.postExitPeakLtp;
  return v != null && Number.isFinite(v) && v > 0 ? v : null;
}

function formatInr(n: number, decimals = 2): string {
  const sign = n >= 0 ? '+' : '';
  return `${sign}₹${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

function holdMinutes(trade: PaperTrade): number | null {
  if (!trade.openedAt || !trade.closedAt) return null;
  const ms = new Date(trade.closedAt).getTime() - new Date(trade.openedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms / 60_000;
}

function exitPremium(trade: PaperTrade): number {
  return trade.entryPremium + (trade.pnlPoints ?? 0);
}

function PageHero({ title, subtitle, badge }: { title: string; subtitle: string; badge: string }) {
  return (
    <header className="mb-1">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-nexus-muted font-semibold">{title}</p>
          <h1 className="text-xl sm:text-2xl font-bold text-white mt-1 tracking-tight">{subtitle}</h1>
        </div>
        <span className="audit-badge audit-badge-outline text-[10px]">{badge}</span>
      </div>
    </header>
  );
}

function PremiumDistanceChart({ trades }: { trades: PaperTrade[] }) {
  const rows = trades
    .map((t) => {
      const exitPx = exitPremium(t);
      const openPeak = peakWhileOpen(t);
      const afterPeak = postExitPeak(t);
      const openDist = openPeak != null ? Math.max(0, openPeak - exitPx) : 0;
      const postDist = afterPeak != null ? Math.max(0, afterPeak - exitPx) : 0;
      return {
        id: t.id,
        label: `${t.strike} ${t.side}`,
        openDist,
        postDist,
        hasOpen: openPeak != null,
        hasPost: afterPeak != null,
      };
    })
    .filter((r) => r.hasOpen || r.hasPost)
    .slice(0, 8);

  if (rows.length === 0) {
    return <p className="text-[11px] text-nexus-muted py-8 text-center">No closed trades — premium distance appears after exits.</p>;
  }

  const peak = Math.max(...rows.flatMap((r) => [r.openDist, r.postDist]), 1);

  return (
    <div className="space-y-3 py-2">
      {rows.map((r) => (
        <div key={r.id} className="space-y-1">
          {r.hasOpen ? (
            <div className="grid grid-cols-[5.5rem_1fr_3rem] gap-2 items-center text-[11px]">
              <span className="font-mono text-nexus-muted">{r.label}</span>
              <div className="h-4 rounded bg-black/40 border border-nexus-border/50 overflow-hidden">
                <div
                  className="h-full rounded-sm bg-gradient-to-r from-amber-500/60 to-amber-400/50"
                  style={{ width: `${Math.min(100, (r.openDist / peak) * 100)}%` }}
                />
              </div>
              <span className="font-mono text-right text-amber-200/90" title="Peak while position was open">
                {r.openDist.toFixed(1)}
              </span>
            </div>
          ) : null}
          {r.hasPost ? (
            <div className="grid grid-cols-[5.5rem_1fr_3rem] gap-2 items-center text-[11px]">
              <span className="font-mono text-nexus-muted text-[9px]">post-exit</span>
              <div className="h-4 rounded bg-black/40 border border-nexus-border/50 overflow-hidden">
                <div
                  className="h-full rounded-sm bg-gradient-to-r from-nexus-accent/80 to-emerald-500/70"
                  style={{ width: `${Math.min(100, (r.postDist / peak) * 100)}%` }}
                />
              </div>
              <span className="font-mono text-right text-white">{r.postDist.toFixed(1)}</span>
            </div>
          ) : null}
        </div>
      ))}
      <p className="text-[10px] text-nexus-muted leading-relaxed">
        Amber: exit vs{' '}
        <span className="text-amber-200/80">peak while open</span> (in-trade high — not after exit). Green: exit vs{' '}
        <span className="text-nexus-accent">post-exit tape peak</span> when monitor finalized.
      </p>
    </div>
  );
}

function RealizedProgressionChart({ trades }: { trades: PaperTrade[] }) {
  const ordered = [...trades].sort((a, b) => {
    const ta = a.closedAt ? new Date(a.closedAt).getTime() : 0;
    const tb = b.closedAt ? new Date(b.closedAt).getTime() : 0;
    return ta - tb;
  });

  if (ordered.length === 0) {
    return <p className="text-[11px] text-nexus-muted py-8 text-center">Realized curve builds as trades close.</p>;
  }

  let cum = 0;
  const points = ordered.map((t, i) => {
    cum += t.pnlInr ?? 0;
    return { x: i + 1, y: cum, label: `EXIT ${String(i + 1).padStart(2, '0')}` };
  });
  const minY = Math.min(0, ...points.map((p) => p.y));
  const maxY = Math.max(1, ...points.map((p) => p.y));
  const range = maxY - minY || 1;
  const w = 360;
  const h = 120;
  const pad = 12;

  const path = points
    .map((p, i) => {
      const x = pad + ((p.x - 1) / Math.max(1, points.length - 1)) * (w - pad * 2);
      const y = h - pad - ((p.y - minY) / range) * (h - pad * 2);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    })
    .join(' ');

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-h-36" aria-label="Realized PnL progression">
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#374151" strokeWidth="1" />
        <path d={path} fill="none" stroke="#06b6d4" strokeWidth="2" />
        {points.map((p, i) => {
          const x = pad + ((p.x - 1) / Math.max(1, points.length - 1)) * (w - pad * 2);
          const y = h - pad - ((p.y - minY) / range) * (h - pad * 2);
          return <circle key={i} cx={x} cy={y} r="3" fill="#10b981" />;
        })}
      </svg>
      <div className="flex justify-between text-[9px] font-mono text-nexus-muted mt-1 px-1">
        <span>START</span>
        {points.map((p) => (
          <span key={p.label}>{p.label}</span>
        ))}
      </div>
    </div>
  );
}

function ClosedTradeTable({ trades }: { trades: PaperTrade[] }) {
  const rows = [...trades].sort((a, b) => {
    const ta = a.closedAt ? new Date(a.closedAt).getTime() : 0;
    const tb = b.closedAt ? new Date(b.closedAt).getTime() : 0;
    return tb - ta;
  });

  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-nexus-muted text-center py-10 border border-dashed border-nexus-border rounded-lg">
        Closed trade journal — no exits yet this session.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-nexus-border/80">
      <table className="w-full text-left text-[11px] audit-table">
        <thead>
          <tr className="text-nexus-muted uppercase tracking-wide text-[10px]">
            <th className="py-2.5 px-3 font-medium">Contract / size</th>
            <th className="py-2.5 px-3 font-medium">Entry → exit</th>
            <th className="py-2.5 px-3 font-medium text-right">Booked P&L</th>
            <th className="py-2.5 px-3 font-medium text-right">Peak while open</th>
            <th className="py-2.5 px-3 font-medium text-right">Exit → open peak</th>
            <th className="py-2.5 px-3 font-medium text-right">Post-exit peak</th>
            <th className="py-2.5 px-3 font-medium text-right">Exit → post-exit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => {
            const exitPx = exitPremium(t);
            const openPeak = peakWhileOpen(t);
            const openLeft = openPeak != null ? openPeak - exitPx : null;
            const afterPeak = postExitPeak(t);
            const postLeft = afterPeak != null ? afterPeak - exitPx : null;
            const hold = holdMinutes(t);
            const pnlPos = (t.pnlInr ?? 0) >= 0;
            return (
              <tr key={t.id} className="border-t border-nexus-border/50 hover:bg-white/[0.02]">
                <td className="py-3 px-3">
                  <div className="font-semibold text-white">
                    {t.symbol} {t.strike} {t.side}
                  </div>
                  <div className="text-nexus-muted font-mono mt-0.5">
                    {t.lots} lot{t.lots !== 1 ? 's' : ''}
                  </div>
                </td>
                <td className="py-3 px-3 font-mono text-gray-300">
                  <div>
                    {t.entryPremium.toFixed(1)} → {exitPx.toFixed(1)}
                  </div>
                  {hold != null ? (
                    <div className="text-nexus-muted text-[10px] mt-0.5">{hold.toFixed(1)} min held</div>
                  ) : null}
                </td>
                <td className={`py-3 px-3 text-right font-mono font-semibold ${pnlPos ? 'text-nexus-accent' : 'text-nexus-red'}`}>
                  {formatInr(t.pnlInr ?? 0)}
                </td>
                <td className="py-3 px-3 text-right font-mono text-amber-100/90">
                  {openPeak != null ? openPeak.toFixed(1) : '—'}
                </td>
                <td className="py-3 px-3 text-right font-mono text-nexus-muted">
                  {openLeft != null && openLeft > 0.05 ? `+${openLeft.toFixed(1)}` : '—'}
                </td>
                <td className="py-3 px-3 text-right font-mono text-white">
                  {afterPeak != null ? afterPeak.toFixed(1) : '—'}
                </td>
                <td className="py-3 px-3 text-right font-mono text-nexus-muted">
                  {postLeft != null && Math.abs(postLeft) > 0.05
                    ? `${postLeft >= 0 ? '+' : ''}${postLeft.toFixed(1)}`
                    : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  tone = 'neutral',
  large,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'accent' | 'bad' | 'neutral';
  large?: boolean;
}) {
  const valueClass =
    tone === 'accent' ? 'text-nexus-accent' : tone === 'bad' ? 'text-nexus-red' : 'text-white';
  return (
    <div className="audit-kpi">
      <span className="text-[10px] uppercase tracking-wide text-nexus-muted font-medium">{label}</span>
      <span className={`font-mono font-semibold ${large ? 'text-2xl sm:text-3xl mt-2' : 'text-lg mt-1.5'} ${valueClass}`}>
        {value}
      </span>
      {sub ? <span className="text-[10px] text-nexus-muted mt-1 block">{sub}</span> : null}
    </div>
  );
}

export function ProfitsLossPage({
  auto,
  deployment,
  activeSymbol,
  dataReady,
}: {
  auto: AutoTraderState;
  snap?: SymbolSnapshot;
  deployment: DeploymentStatus | null;
  activeSymbol: string;
  dataReady: boolean;
}) {
  const closed = auto.closedPaperTrades ?? [];
  const open = auto.openPaperTrades ?? [];
  const report = auto.dailyReport;
  const net = report?.netPnlInr ?? closed.reduce((s, t) => s + (t.pnlInr ?? 0), 0);
  const wins = report?.wins ?? closed.filter((t) => (t.pnlInr ?? 0) > 0).length;
  const losses = report?.losses ?? closed.filter((t) => (t.pnlInr ?? 0) < 0).length;

  const flags = deployment?.flags as Record<string, unknown> | undefined;
  const fallbackCap = Number(flags?.fallbackCapitalInr ?? 0);
  const maxSizingCap = Number(flags?.maxSizingCapitalInr ?? fallbackCap);
  const envBook = Math.max(fallbackCap, maxSizingCap);
  const runtimeBook = auto.capitalAllocation?.availableMarginInr;
  const perTrade = auto.capitalAllocation?.perTradeCapitalInr;
  const execMode = auto.liveTradingEnabled ? 'LIVE' : 'PAPER';

  return (
    <div className="space-y-5">
      <PageHero
        title="POST-SESSION / EXECUTION AUDIT"
        subtitle={`${activeSymbol} · exit analytics`}
        badge={dataReady ? 'LIVE DATA' : 'READ ONLY — OFFLINE'}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <KpiCard label={`Realized ${execMode} P&L`} value={formatInr(net)} tone={net >= 0 ? 'accent' : 'bad'} large />
        <KpiCard label="Closed outcomes" value={`${wins} W / ${losses} L`} sub={`${closed.length} round-trips`} />
        <KpiCard
          label="Position status"
          value={open.length === 0 ? 'Flat' : `${open.length} open`}
          sub={open.length === 0 ? '0 open' : open.map((t) => `${t.strike} ${t.side}`).join(', ')}
        />
        <KpiCard
          label="API sizing capital"
          value={
            runtimeBook != null && runtimeBook > 0
              ? `₹${runtimeBook.toLocaleString('en-IN')}`
              : fallbackCap > 0
                ? `₹${fallbackCap.toLocaleString('en-IN')}`
                : '—'
          }
          sub={
            runtimeBook != null && envBook > 0 && Math.abs(runtimeBook - envBook) > 1
              ? `env book ₹${envBook.toLocaleString('en-IN')} · per-trade ₹${(perTrade ?? 0).toLocaleString('en-IN')}`
              : perTrade != null
                ? `per-trade sleeve ₹${perTrade.toLocaleString('en-IN')}`
                : 'book + runtime aligned'
          }
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="audit-panel">
          <h2 className="audit-panel-title">Exit — open peak vs post-exit tape</h2>
          <p className="audit-panel-sub">In-trade high vs premium seen on tape after exit (when monitor ran).</p>
          <PremiumDistanceChart trades={closed} />
        </section>
        <section className="audit-panel">
          <h2 className="audit-panel-title">Realized progression</h2>
          <p className="audit-panel-sub">Cumulative booked P&L across closes this session.</p>
          <RealizedProgressionChart trades={closed} />
        </section>
      </div>

      <section className="audit-panel">
        <h2 className="audit-panel-title">Closed trade journal</h2>
        <p className="audit-panel-sub">
          Booked fills vs in-trade peak (max LTP) and post-exit monitor peak — not the same clock.
        </p>
        <ClosedTradeTable trades={closed} />
      </section>
    </div>
  );
}
