import { useEffect, useRef, useState } from 'react';
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
} from './hooks/useMarketStream';
import { WaitingState } from './components/Panel';
import { OnboardingBanner } from './components/OnboardingBanner';
import { deriveMarketSession } from './lib/marketSession';
import type { MultiSnapshot, SymbolSnapshot } from './types';
import { AuditShell, type AuditPage } from './components/audit/AuditShell';
import { ProfitsLossPage } from './pages/ProfitsLossPage';
import { AnalysisPage } from './pages/AnalysisPage';

const SYMBOLS = ['NIFTY', 'SENSEX'] as const;

function pickSnap(data: MultiSnapshot | null, activeSymbol: string): SymbolSnapshot | undefined {
  return (
    data?.snapshots?.[activeSymbol] ??
    SYMBOLS.map((s) => data?.snapshots?.[s]).find((s) => s?.dataAvailable)
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
  const [page, setPage] = useState<AuditPage>('pnl');

  const lastGoodSnapRef = useRef<SymbolSnapshot | undefined>(undefined);
  const dashboardUnlockedRef = useRef(false);
  const liveSnap = pickSnap(data, activeSymbol);
  if (liveSnap?.dataAvailable) {
    lastGoodSnapRef.current = liveSnap;
  }
  const snap = liveSnap ?? lastGoodSnapRef.current;
  const auto = data?.autoTrader;

  if (data && auto && snap) {
    dashboardUnlockedRef.current = true;
  }
  const canShowDashboard = dashboardUnlockedRef.current && Boolean(data && auto && snap);

  const needsUpstox = deployment && !deployment.upstox.validToday;
  const session = deriveMarketSession(data);
  const showReconnect = Boolean(error && data);
  const showHardError = Boolean(error && !data);
  const showBootWait = Boolean(loading && !data);
  const showDataWait = Boolean(data && !canShowDashboard);

  const flags = deployment?.flags as Record<string, unknown> | undefined;
  const enableLive = Boolean(flags?.enableLiveTrading ?? auto?.liveTradingEnabled);
  const execLabel = enableLive ? 'LIVE' : 'PAPER';

  useEffect(() => {
    document.documentElement.style.overflowAnchor = 'none';
  }, []);

  const footerExtra = data?.timestamp
    ? `Last update ${new Date(data.timestamp).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })} IST`
    : undefined;

  return (
    <AuditShell
      page={page}
      onPageChange={setPage}
      activeSymbol={activeSymbol}
      onSymbolChange={setActiveSymbol}
      deployment={deployment}
      metrics={metrics}
      session={session}
      dataReady={Boolean(data?.dataReady)}
      executionLabel={execLabel}
      footerExtra={footerExtra}
    >
      {!auto ? (
        <div className="space-y-4">
          <OnboardingBanner
            deployment={deployment}
            dataReady={Boolean(data?.dataReady)}
            waitingReason={data?.waitingReason}
          />
          {showBootWait ? <WaitingState reason="Connecting to server..." showConnect={false} /> : null}
          {showHardError ? (
            <div className="text-center py-16 rounded-xl border border-nexus-red/30 bg-nexus-red/5">
              <p className="text-nexus-red font-bold">Cannot reach server</p>
              <p className="text-nexus-muted text-sm mt-2">{error}</p>
              <button type="button" onClick={() => refetch()} className="mt-4 px-4 py-2 bg-nexus-accent text-black font-bold rounded-lg text-sm">
                Try again
              </button>
            </div>
          ) : null}
        </div>
      ) : page === 'pnl' ? (
        <ProfitsLossPage
          auto={auto}
          snap={snap}
          deployment={deployment}
          activeSymbol={activeSymbol}
          dataReady={Boolean(data?.dataReady)}
        />
      ) : (
        <AnalysisPage
          data={data}
          auto={auto}
          snap={snap}
          deployment={deployment}
          readiness={readiness}
          milestone={milestone}
          weeklyDashboard={weeklyDashboard}
          tradeHistory={tradeHistory}
          tradeLog={tradeLog}
          activeSymbol={activeSymbol}
          canShowDashboard={canShowDashboard}
          needsUpstox={Boolean(needsUpstox)}
          marketPhase={(snap?.marketPhase ?? 'CLOSED').replace(/_/g, ' ')}
          showBootWait={showBootWait}
          showHardError={showHardError}
          showDataWait={showDataWait}
          showReconnect={showReconnect}
          error={error}
          refetch={refetch}
        />
      )}

      <div className="mt-6 flex flex-wrap gap-2 border-t border-nexus-border/50 pt-4">
        <button
          type="button"
          onClick={() => stopTrading()}
          className="px-2.5 py-1 text-[10px] bg-nexus-red/15 text-nexus-red border border-nexus-red/25 rounded-lg hover:bg-nexus-red/25"
        >
          Pause
        </button>
        <button
          type="button"
          onClick={() => resumeTrading()}
          className="px-2.5 py-1 text-[10px] bg-nexus-green/15 text-nexus-green border border-nexus-green/25 rounded-lg hover:bg-nexus-green/25"
        >
          Resume
        </button>
        <button
          type="button"
          onClick={() => resetSession()}
          className="px-2.5 py-1 text-[10px] bg-black/30 text-gray-400 border border-nexus-border rounded-lg hover:text-white"
        >
          Reset session
        </button>
      </div>
    </AuditShell>
  );
}
