import type {
  AutoTraderState,
  DeploymentReadiness,
  DeploymentStatus,
  MultiSnapshot,
  PerformanceMilestone,
  SymbolSnapshot,
  TradeHistoryResponse,
  TradeLogResponse,
  WeeklyDashboard,
} from '../types';
import { DashboardSection } from '../components/DashboardSection';
import { OnboardingBanner } from '../components/OnboardingBanner';
import { WaitingState } from '../components/Panel';
import { AutoTradingPanel } from '../components/AutoTradingPanel';
import { PerformanceMilestone as PerformanceMilestonePanel } from '../components/PerformanceMilestone';
import { WeeklyDashboardPanel } from '../components/WeeklyDashboardPanel';
import { UpstoxTradeManagerPanel } from '../components/UpstoxTradeManagerPanel';
import { RadarIntelligencePanel } from '../components/RadarIntelligencePanel';
import { ExecutionHUD } from '../components/ExecutionHUD';
import { PremarketPanel } from '../components/PremarketPanel';
import { ExplosiveRunner } from '../components/ExplosiveRunner';
import { ExplosionRadar } from '../components/ExplosionRadar';
import { BuildingWatchPanel } from '../components/BuildingWatchPanel';
import { TomorrowPlaybookPanel } from '../components/TomorrowPlaybookPanel';
import { StrikeWatchlistPanel } from '../components/StrikeWatchlistPanel';
import { EodTomorrowPlaybookPanel } from '../components/EodTomorrowPlaybookPanel';
import { ComposerMonitorPanel } from '../components/ComposerMonitorPanel';
import { SnapshotLagPanel } from '../components/SnapshotLagPanel';
import { MissedTradeExplainerPanel } from '../components/MissedTradeExplainerPanel';
import { AnalysisReportsPanel } from '../components/AnalysisReportsPanel';
import { DayModePanel } from '../components/DayModePanel';
import { StrategyRouter } from '../components/StrategyRouter';
import { MarketHeatmap } from '../components/MarketHeatmap';
import { SwingTrading } from '../components/SwingTrading';
import { OrderflowAnalytics } from '../components/OrderflowAnalytics';
import { AIMatrix } from '../components/AIMatrix';
import { GreeksIV } from '../components/GreeksIV';
import { MarketProfilePanel } from '../components/MarketProfile';
import { RiskEngine } from '../components/RiskEngine';
import { OptionHeatmap } from '../components/OptionHeatmap';
import { StrategyMatrix } from '../components/StrategyMatrix';
import { TradeJournal, NewsPanel } from '../components/TradeJournal';
import { PsychologyPanel } from '../components/PsychologyPanel';
import { LiveTradingGate, MorningChecklist } from '../components/LiveTradingGate';
import { FutureSignalsPanel } from '../components/FutureSignalsPanel';

const SYMBOLS = ['NIFTY', 'SENSEX'] as const;

function SystemSnapshot({
  auto,
  deployment,
  readiness,
  marketPhase,
}: {
  auto: AutoTraderState;
  deployment: DeploymentStatus | null;
  readiness: DeploymentReadiness | null;
  marketPhase: string;
}) {
  const flags = deployment?.flags as Record<string, unknown> | undefined;
  const parity = flags?.livePaperParity as { settingsAligned?: boolean } | undefined;
  const fallback = Number(flags?.fallbackCapitalInr ?? 0);
  const enableLive = Boolean(flags?.enableLiveTrading ?? auto.liveTradingEnabled);
  const paper = Boolean(flags?.paperTrading ?? auto.paperTrading);

  const rows: { label: string; value: string; warn?: boolean }[] = [
    { label: 'Market', value: marketPhase },
    { label: 'Execution', value: enableLive && !paper ? 'LIVE broker' : 'PAPER only' },
    { label: 'Open positions', value: `${auto.openPaperTrades?.length ?? 0} / flat` },
    {
      label: 'Paper / live parity',
      value: parity?.settingsAligned ? 'On' : 'Check drift',
      warn: parity?.settingsAligned === false,
    },
    { label: 'Capital alignment', value: fallback > 0 ? `₹${fallback.toLocaleString('en-IN')}` : '—' },
    {
      label: 'Live readiness',
      value: readiness?.readyForLive ? 'Established' : 'Not established',
      warn: enableLive && !readiness?.readyForLive,
    },
  ];

  return (
    <div className="audit-panel h-full">
      <h2 className="audit-panel-title">System snapshot</h2>
      <table className="w-full text-[11px] mt-3">
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t border-nexus-border/40 first:border-0">
              <td className="py-2 pr-3 text-nexus-muted w-36">{r.label}</td>
              <td className={`py-2 font-mono ${r.warn ? 'text-nexus-yellow' : 'text-white'}`}>{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RejectionReview({ auto }: { auto: AutoTraderState }) {
  const skipped = auto.skipped ?? [];
  return (
    <div className="audit-panel h-full">
      <h2 className="audit-panel-title">Rejection review</h2>
      {skipped.length === 0 ? (
        <p className="text-[11px] text-nexus-muted mt-2">No funnel rejections logged this session.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-[11px] text-gray-300 list-disc pl-4 max-h-48 overflow-y-auto">
          {skipped.slice(0, 12).map((s, i) => (
            <li key={`${s.symbol}-${i}`}>
              <span className="font-mono text-white">
                {s.symbol} {s.trade ?? ''}
              </span>
              {s.reason ? <span className="text-nexus-muted"> — {s.reason}</span> : null}
              {s.message ? <div className="text-nexus-muted text-[10px] mt-0.5">{s.message}</div> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CapitalAlignmentCallout({
  deployment,
  auto,
}: {
  deployment: DeploymentStatus | null;
  auto: AutoTraderState;
}) {
  const flags = deployment?.flags as Record<string, unknown> | undefined;
  const fallback = Number(flags?.fallbackCapitalInr ?? 0);
  const max = Number(flags?.maxSizingCapitalInr ?? fallback);
  const runtime = auto.capitalAllocation?.perTradeCapitalInr;
  const mismatch =
    runtime != null && fallback > 0 && (Math.abs(runtime - fallback) > 1 || Math.abs(max - fallback) > 1);
  if (!mismatch) return null;
  return (
    <div className="audit-callout">
      <h3 className="text-[12px] font-semibold text-nexus-yellow">Capital alignment required</h3>
      <p className="text-[11px] text-gray-300 mt-2 leading-relaxed">
        API capital is ₹{fallback.toLocaleString('en-IN')}
        {runtime != null ? ` but runtime sizing shows ₹${runtime.toLocaleString('en-IN')}` : ''}. Align env capital
        with POST <span className="font-mono text-nexus-accent">/api/auto-trader/capital</span> before trusting lot
        sizes.
      </p>
    </div>
  );
}

export function AnalysisPage(props: {
  data: MultiSnapshot | null;
  auto: AutoTraderState;
  snap: SymbolSnapshot | undefined;
  deployment: DeploymentStatus | null;
  readiness: DeploymentReadiness | null;
  milestone: PerformanceMilestone | null;
  weeklyDashboard: WeeklyDashboard | null;
  tradeHistory: TradeHistoryResponse | null;
  tradeLog: TradeLogResponse | null;
  activeSymbol: string;
  canShowDashboard: boolean;
  needsUpstox: boolean;
  marketPhase: string;
  showBootWait: boolean;
  showHardError: boolean;
  showDataWait: boolean;
  showReconnect: boolean;
  error: string | null;
  refetch: () => void;
}) {
  const {
    data,
    auto,
    snap,
    deployment,
    readiness,
    milestone,
    weeklyDashboard,
    tradeHistory,
    tradeLog,
    activeSymbol,
    canShowDashboard,
    needsUpstox,
    marketPhase,
    showBootWait,
    showHardError,
    showDataWait,
    showReconnect,
    error,
    refetch,
  } = props;

  const chopEnabled = Boolean((deployment?.flags as Record<string, unknown> | undefined)?.chopDayGuardsEnabled);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-[10px] uppercase tracking-[0.2em] text-nexus-muted font-semibold">SYSTEM REVIEW / ANALYSIS</p>
        <h1 className="text-xl sm:text-2xl font-bold text-white mt-1 tracking-tight">Execution, gates & session intelligence</h1>
      </header>

      <div className="space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SystemSnapshot auto={auto} deployment={deployment} readiness={readiness} marketPhase={marketPhase} />
          <RejectionReview auto={auto} />
        </div>
        <CapitalAlignmentCallout deployment={deployment} auto={auto} />
      </div>

      {!canShowDashboard ? (
        <OnboardingBanner
          deployment={deployment}
          dataReady={Boolean(data?.dataReady)}
          waitingReason={data?.waitingReason}
        />
      ) : null}

      <section aria-label="Auto trader overview" className="max-w-5xl">
        <AutoTradingPanel auto={auto} />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-w-5xl">
        <PerformanceMilestonePanel stats={milestone} />
        <WeeklyDashboardPanel data={weeklyDashboard} />
      </div>

      <UpstoxTradeManagerPanel deployment={deployment} readiness={readiness} />
      <RadarIntelligencePanel />

      <div
        className={`layout-status-slot ${showReconnect ? 'rounded-lg border border-nexus-yellow/30 bg-nexus-yellow/5 px-3 py-2 text-[11px] text-nexus-yellow' : 'hidden'}`}
      >
        {showReconnect ? 'Server reconnecting — showing last cached data.' : null}
      </div>

      {showBootWait ? <WaitingState reason="Connecting to server..." showConnect={false} /> : null}

      {showHardError ? (
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

      {showDataWait ? (
        <WaitingState reason={data?.waitingReason || 'Loading symbol snapshots…'} showConnect={Boolean(needsUpstox)} />
      ) : null}

      {data && auto && canShowDashboard && snap ? (
        <div className="space-y-6">
          <DashboardSection title="News Intelligence" subtitle="Verified India and global cues for the current and next session">
            <div className="col-span-12">
              <NewsPanel news={data.news ?? []} />
            </div>
          </DashboardSection>

          <DashboardSection title="Historical Timing" subtitle="Upstox-backed flat-to-vertical probabilities and recurring session windows">
            <div className="col-span-12">
              <FutureSignalsPanel snapshots={data.snapshots} auto={auto} />
            </div>
          </DashboardSection>

          <DashboardSection title="Execution" subtitle="Live context for the active symbol">
            <div className="col-span-12 lg:col-span-3">
              <ExecutionHUD snap={snap} auto={auto} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <PremarketPanel snap={snap} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <ExplosiveRunner snap={snap} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <ExplosionRadar snap={snap} />
            </div>
            <div className="col-span-12">
              <BuildingWatchPanel data={data} auto={auto} />
            </div>
          </DashboardSection>

          <DashboardSection title="Signals & Trades" subtitle="Day mode, router, heatmap, swing lane">
            <div className="col-span-12">
              <TomorrowPlaybookPanel auto={auto} snapshots={data.snapshots} deployment={deployment} />
            </div>
            <div className="col-span-12">
              <StrikeWatchlistPanel snapshots={data.snapshots} />
            </div>
            <div className="col-span-12 lg:col-span-6">
              <EodTomorrowPlaybookPanel />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <ComposerMonitorPanel />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <SnapshotLagPanel />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <MissedTradeExplainerPanel />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <AnalysisReportsPanel />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <DayModePanel auto={auto} snapshots={data.snapshots} symbols={SYMBOLS} chopEnabled={chopEnabled} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <StrategyRouter snap={snap} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <MarketHeatmap symbol={activeSymbol} embedded={snap.constituentHeatmap} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <SwingTrading snap={snap} auto={auto} />
            </div>
          </DashboardSection>

          <DashboardSection title="Analytics" subtitle="Orderflow, AI matrix, greeks, profile, risk">
            <div className="col-span-12 md:col-span-6 xl:col-span-3">
              <OrderflowAnalytics snap={snap} />
            </div>
            <div className="col-span-12 md:col-span-6 xl:col-span-3">
              <AIMatrix snap={snap} />
            </div>
            <div className="col-span-12 sm:col-span-6 xl:col-span-2">
              <GreeksIV snap={snap} />
            </div>
            <div className="col-span-12 sm:col-span-6 xl:col-span-2">
              <MarketProfilePanel snap={snap} />
            </div>
            <div className="col-span-12 xl:col-span-2">
              <RiskEngine auto={auto} />
            </div>
          </DashboardSection>

          <DashboardSection title="Depth & System" subtitle="Chain heatmap, strategies, journal, deployment gates">
            <div className="col-span-12 lg:col-span-3">
              <OptionHeatmap snap={snap} />
            </div>
            <div className="col-span-12 lg:col-span-3">
              <StrategyMatrix snap={snap} />
            </div>
            <div className="col-span-12 md:col-span-6 xl:col-span-2">
              <TradeJournal data={data} history={tradeHistory} tradeLog={tradeLog} />
            </div>
            <div className="col-span-12 md:col-span-6 xl:col-span-2">
              <PsychologyPanel snap={snap} />
            </div>
            <div className="col-span-12 md:col-span-6 xl:col-span-1">
              <LiveTradingGate status={deployment} readiness={readiness} />
            </div>
            <div className="col-span-12 md:col-span-6 xl:col-span-1">
              <MorningChecklist deployment={deployment} dataReady={data.dataReady} />
            </div>
          </DashboardSection>
        </div>
      ) : null}
    </div>
  );
}
