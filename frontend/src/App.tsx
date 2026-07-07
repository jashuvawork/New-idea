import { useState } from 'react';
import {
  useMarketStream,
  useDeploymentStatus,
  useDeploymentReadiness,
  useTradeHistory,
  useTradeLog,
  usePerformanceMilestone,
  useWeeklyDashboard,
  stopTrading,
  resumeTrading,
  resetSession,
  getLoginUrl,
} from './hooks/useMarketStream';
import { WaitingState } from './components/Panel';
import { ConnectionStatus, LatencyFooter } from './components/ConnectionStatus';
import { OnboardingBanner } from './components/OnboardingBanner';
import { DashboardSection } from './components/DashboardSection';
import { ExecutionHUD } from './components/ExecutionHUD';
import { ExplosiveRunner } from './components/ExplosiveRunner';
import { OptionHeatmap } from './components/OptionHeatmap';
import { OrderflowAnalytics } from './components/OrderflowAnalytics';
import { AIMatrix } from './components/AIMatrix';
import { GreeksIV } from './components/GreeksIV';
import { StrategyRouter } from './components/StrategyRouter';
import { AutoTradingPanel } from './components/AutoTradingPanel';
import { TomorrowPlaybookPanel } from './components/TomorrowPlaybookPanel';
import { DayModePanel } from './components/DayModePanel';
import { ComposerMonitorPanel } from './components/ComposerMonitorPanel';
import { RiskEngine } from './components/RiskEngine';
import { MarketProfilePanel } from './components/MarketProfile';
import { LiveTradingGate, MorningChecklist } from './components/LiveTradingGate';
import { TradeJournal, NewsPanel } from './components/TradeJournal';
import { StrategyMatrix } from './components/StrategyMatrix';
import { ExplosionRadar } from './components/ExplosionRadar';
import { MarketHeatmap } from './components/MarketHeatmap';
import { PsychologyPanel } from './components/PsychologyPanel';
import { PremarketPanel } from './components/PremarketPanel';
import { SwingTrading } from './components/SwingTrading';
import { PerformanceMilestone } from './components/PerformanceMilestone';
import { WeeklyDashboardPanel } from './components/WeeklyDashboardPanel';
import { deriveMarketSession } from './lib/marketSession';

const SYMBOLS = ['NIFTY', 'SENSEX'] as const;

function QuickStat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'good' | 'bad' | 'accent';
}) {
  const toneClass =
    tone === 'good'
      ? 'text-nexus-green'
      : tone === 'bad'
        ? 'text-nexus-red'
        : tone === 'accent'
          ? 'text-nexus-accent'
          : 'text-white';

  return (
    <div className="stat-pill">
      <span className="text-nexus-muted">{label}</span>
      <span className={`font-mono font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

export default function App() {
  const { data, error, loading, metrics, refetch } = useMarketStream();
  const deployment = useDeploymentStatus();
  const readiness = useDeploymentReadiness();
  const tradeHistory = useTradeHistory(14);
  const tradeLog = useTradeLog(20);
  const milestone = usePerformanceMilestone();
  const weeklyDashboard = useWeeklyDashboard(7);
  const [activeSymbol, setActiveSymbol] = useState<string>('NIFTY');

  const auto = data?.autoTrader;
  const snap =
    data?.snapshots?.[activeSymbol] ??
    SYMBOLS.map((s) => data?.snapshots?.[s]).find((s) => s?.dataAvailable);
  const needsUpstox = deployment && !deployment.upstox.validToday;
  const canShowDashboard = Boolean(data && auto && snap);

  const report = auto?.dailyReport;
  const netPnl = report?.netPnlInr ?? 0;
  const pf = report?.profitFactor ?? 0;

  const upstoxBadge = deployment
    ? deployment.upstox.validToday
      ? { className: 'bg-nexus-green/15 text-nexus-green border-nexus-green/30', label: 'Broker connected' }
      : deployment.upstox.expired
        ? { className: 'bg-nexus-red/15 text-nexus-red border-nexus-red/30', label: 'Token expired — relogin' }
        : deployment.upstox.hasToken
          ? { className: 'bg-nexus-yellow/15 text-nexus-yellow border-nexus-yellow/30', label: 'Relogin needed' }
          : { className: 'bg-nexus-red/15 text-nexus-red border-nexus-red/30', label: 'Not connected' }
    : null;

  const session = deriveMarketSession(data);

  return (
    <div className="min-h-screen text-gray-100">
      <header className="border-b border-nexus-border/80 bg-nexus-panel sticky top-0 z-50 shadow-panel">
        <div className="max-w-[1920px] mx-auto px-4 sm:px-5 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4 min-w-0">
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-nexus-accent to-emerald-500 flex items-center justify-center shadow-glow-accent">
                <span className="text-xs font-black text-black">NQ</span>
              </div>
              <div>
                <h1 className="text-base font-bold leading-tight">
                  <span className="text-nexus-accent">Nexus</span>Quant
                </h1>
                <p className="text-[10px] text-nexus-muted tracking-wide">Indian index options · Paper</p>
              </div>
            </div>

            <div className="hidden sm:flex items-center gap-1 p-1 rounded-xl bg-black/25 border border-nexus-border">
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setActiveSymbol(s)}
                  className={`symbol-tab ${activeSymbol === s ? 'symbol-tab-active' : 'symbol-tab-idle'}`}
                >
                  {s}
                  {data?.snapshots?.[s]?.spot != null ? (
                    <span className="ml-1 font-mono text-[10px] opacity-90">
                      {data.snapshots[s].spot!.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ConnectionStatus metrics={metrics} session={session} dataReady={Boolean(data?.dataReady)} />

            {upstoxBadge ? (
              <span
                className={`text-[10px] px-2 py-1 rounded-lg border ${upstoxBadge.className}`}
                title={deployment?.upstox.message}
              >
                {upstoxBadge.label}
              </span>
            ) : null}

            {needsUpstox ? (
              <a
                href={getLoginUrl()}
                className="px-3 py-1.5 text-[11px] bg-nexus-accent text-black font-bold rounded-lg hover:opacity-90 shadow-glow-accent"
              >
                Connect Upstox
              </a>
            ) : null}

            {data?.dataReady && snap ? (
              <span className="stat-pill hidden md:inline-flex">
                <span className="text-nexus-muted">{(snap.marketPhase ?? 'MARKET').replace(/_/g, ' ')}</span>
                <span className="font-mono text-nexus-accent">TQS {(snap.tradeQualityScore ?? 0).toFixed(0)}</span>
              </span>
            ) : null}

            <div className="flex gap-1 border-l border-nexus-border pl-2">
              <button
                type="button"
                onClick={() => stopTrading()}
                className="px-2.5 py-1 text-[10px] bg-nexus-red/15 text-nexus-red border border-nexus-red/25 rounded-lg hover:bg-nexus-red/25"
                title="Pause new paper trades"
              >
                Pause
              </button>
              <button
                type="button"
                onClick={() => resumeTrading()}
                className="px-2.5 py-1 text-[10px] bg-nexus-green/15 text-nexus-green border border-nexus-green/25 rounded-lg hover:bg-nexus-green/25"
                title="Resume paper trading"
              >
                Resume
              </button>
              <button
                type="button"
                onClick={() => resetSession()}
                className="px-2.5 py-1 text-[10px] bg-black/30 text-gray-400 border border-nexus-border rounded-lg hover:text-white"
                title="Clear today's paper session"
              >
                Reset
              </button>
            </div>
          </div>
        </div>

        <div className="sm:hidden max-w-[1920px] mx-auto px-4 pb-3 flex gap-1 overflow-x-auto">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setActiveSymbol(s)}
              className={`symbol-tab shrink-0 ${activeSymbol === s ? 'symbol-tab-active' : 'symbol-tab-idle'}`}
            >
              {s}
            </button>
          ))}
        </div>
      </header>

      <main className="max-w-[1920px] mx-auto px-4 sm:px-5 py-4 sm:py-5 space-y-5">
        <OnboardingBanner
          deployment={deployment}
          dataReady={Boolean(data?.dataReady)}
          waitingReason={data?.waitingReason}
        />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-w-5xl">
          <PerformanceMilestone stats={milestone} />
          <WeeklyDashboardPanel data={weeklyDashboard} />
        </div>

        {canShowDashboard && snap && auto && report ? (
          <div className="flex flex-wrap items-center gap-2">
            <QuickStat label="Net PnL" value={`₹${netPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`} tone={netPnl >= 0 ? 'good' : 'bad'} />
            <QuickStat label="PF" value={pf.toFixed(2)} tone={pf >= 1.2 ? 'good' : pf < 1 ? 'bad' : 'neutral'} />
            <QuickStat label="Open" value={String(auto.openPaperTrades.length)} tone="accent" />
            <QuickStat label="Regime" value={(snap.regime ?? '—').replace(/_/g, ' ')} />
            <QuickStat label="Bias" value={snap.breadth?.bias ?? 'NEUTRAL'} tone={snap.breadth?.bias === 'BULLISH' ? 'good' : snap.breadth?.bias === 'BEARISH' ? 'bad' : 'neutral'} />
          </div>
        ) : null}

        {loading && !data ? <WaitingState reason="Connecting to server..." showConnect={false} /> : null}

        {error && !data ? (
          <div className="text-center py-16 rounded-xl border border-nexus-red/30 bg-nexus-red/5 shadow-panel">
            <p className="text-nexus-red font-bold text-lg">Cannot reach server</p>
            <p className="text-nexus-muted text-sm mt-2 max-w-md mx-auto leading-relaxed">{error}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-4 px-4 py-2 bg-nexus-accent text-black font-bold rounded-lg text-sm hover:opacity-90"
            >
              Try again
            </button>
          </div>
        ) : null}

        {data && !data.dataReady && !canShowDashboard ? (
          <WaitingState reason={data.waitingReason} showConnect={Boolean(needsUpstox)} />
        ) : null}

        {data && auto && !snap ? (
          <WaitingState reason={data.waitingReason || 'Loading symbol snapshots…'} showConnect={Boolean(needsUpstox)} />
        ) : null}

        {canShowDashboard && snap && auto ? (
          <div className="space-y-6">
            <DashboardSection title="Execution" subtitle="Live context for the active symbol">
              <div className="col-span-12 lg:col-span-3"><ExecutionHUD snap={snap} auto={auto} /></div>
              <div className="col-span-12 lg:col-span-3"><PremarketPanel snap={snap} /></div>
              <div className="col-span-12 lg:col-span-3"><ExplosiveRunner snap={snap} /></div>
              <div className="col-span-12 lg:col-span-3"><ExplosionRadar snap={snap} /></div>
            </DashboardSection>

            <DashboardSection title="Signals & Trades" subtitle="Day mode, router, auto-trader, heatmap, swing lane">
              <div className="col-span-12">
                <TomorrowPlaybookPanel auto={auto} snapshots={data.snapshots} deployment={deployment} />
              </div>
              <div className="col-span-12 lg:col-span-3">
                <ComposerMonitorPanel />
              </div>
              <div className="col-span-12 lg:col-span-3">
                <DayModePanel
                  auto={auto}
                  snapshots={data.snapshots}
                  symbols={SYMBOLS}
                  chopEnabled={Boolean(deployment?.flags?.chopDayGuardsEnabled)}
                />
              </div>
              <div className="col-span-12 lg:col-span-3"><StrategyRouter snap={snap} /></div>
              <div className="col-span-12 lg:col-span-3"><AutoTradingPanel auto={auto} /></div>
              <div className="col-span-12 lg:col-span-3"><MarketHeatmap symbol={activeSymbol} embedded={snap.constituentHeatmap} /></div>
              <div className="col-span-12 lg:col-span-3"><SwingTrading snap={snap} auto={auto} /></div>
            </DashboardSection>

            <DashboardSection title="Analytics" subtitle="Orderflow, AI matrix, greeks, profile, risk">
              <div className="col-span-12 md:col-span-6 xl:col-span-3"><OrderflowAnalytics snap={snap} /></div>
              <div className="col-span-12 md:col-span-6 xl:col-span-3"><AIMatrix snap={snap} /></div>
              <div className="col-span-12 sm:col-span-6 xl:col-span-2"><GreeksIV snap={snap} /></div>
              <div className="col-span-12 sm:col-span-6 xl:col-span-2"><MarketProfilePanel snap={snap} /></div>
              <div className="col-span-12 xl:col-span-2"><RiskEngine auto={auto} /></div>
            </DashboardSection>

            <DashboardSection title="Depth & System" subtitle="Chain heatmap, strategies, journal, deployment gates">
              <div className="col-span-12 lg:col-span-3"><OptionHeatmap snap={snap} /></div>
              <div className="col-span-12 lg:col-span-3"><StrategyMatrix snap={snap} /></div>
              <div className="col-span-12 md:col-span-6 xl:col-span-2"><TradeJournal data={data} history={tradeHistory} tradeLog={tradeLog} /></div>
              <div className="col-span-12 md:col-span-6 xl:col-span-2"><PsychologyPanel snap={snap} /></div>
              <div className="col-span-12 md:col-span-6 xl:col-span-1"><NewsPanel news={data.news ?? []} /></div>
              <div className="col-span-12 md:col-span-6 xl:col-span-1"><LiveTradingGate status={deployment} readiness={readiness} /></div>
              <div className="col-span-12 md:col-span-6 xl:col-span-1"><MorningChecklist deployment={deployment} dataReady={data.dataReady} /></div>
            </DashboardSection>
          </div>
        ) : null}

        <footer className="pt-4 border-t border-nexus-border/70 flex flex-wrap justify-between gap-3">
          <LatencyFooter metrics={metrics} />
          <span className="text-[10px] text-nexus-muted leading-relaxed">
            Explosion scalp + swing (2–5d) · Paper only
            {data?.timestamp ? ` · Last update ${new Date(data.timestamp).toLocaleTimeString('en-IN')}` : ''}
            {deployment ? ` · ${deployment.environment} · ${deployment.commit}` : ''}
          </span>
        </footer>
      </main>
    </div>
  );
}
