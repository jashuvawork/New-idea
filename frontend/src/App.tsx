import { useState } from 'react';
import {
  useMarketStream,
  useDeploymentStatus,
  useTradeHistory,
  stopTrading,
  resumeTrading,
  resetSession,
  getLoginUrl,
} from './hooks/useMarketStream';
import { WaitingState } from './components/Panel';
import { ConnectionStatus, LatencyFooter } from './components/ConnectionStatus';
import { OnboardingBanner } from './components/OnboardingBanner';
import { ExecutionHUD } from './components/ExecutionHUD';
import { ExplosiveRunner } from './components/ExplosiveRunner';
import { OptionHeatmap } from './components/OptionHeatmap';
import { OrderflowAnalytics } from './components/OrderflowAnalytics';
import { AIMatrix } from './components/AIMatrix';
import { GreeksIV } from './components/GreeksIV';
import { StrategyRouter } from './components/StrategyRouter';
import { PaperTrading } from './components/PaperTrading';
import { RiskEngine } from './components/RiskEngine';
import { MarketProfilePanel } from './components/MarketProfile';
import { LiveTradingGate, MorningChecklist } from './components/LiveTradingGate';
import { TradeJournal, NewsPanel } from './components/TradeJournal';
import { StrategyMatrix } from './components/StrategyMatrix';
import { ExplosionRadar } from './components/ExplosionRadar';

const SYMBOLS = ['NIFTY', 'SENSEX', 'BANKNIFTY'] as const;

export default function App() {
  const { data, error, loading, metrics, refetch } = useMarketStream();
  const deployment = useDeploymentStatus();
  const tradeHistory = useTradeHistory(14);
  const [activeSymbol, setActiveSymbol] = useState<string>('NIFTY');

  const snap = data?.snapshots?.[activeSymbol];
  const auto = data?.autoTrader;
  const needsUpstox = deployment && !deployment.upstox.validToday;

  return (
    <div className="min-h-screen bg-nexus-bg">
      <header className="border-b border-nexus-border bg-nexus-panel/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-[1920px] mx-auto px-4 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold">
              <span className="text-nexus-accent">Nexus</span>Quant
              <span className="text-[10px] ml-2 text-nexus-muted font-normal">Paper Trading</span>
            </h1>
            <div className="flex gap-1">
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  onClick={() => setActiveSymbol(s)}
                  className={`px-3 py-1.5 text-xs font-bold rounded transition-colors ${
                    activeSymbol === s
                      ? 'bg-nexus-accent text-black'
                      : 'bg-gray-800 text-gray-400 hover:text-white'
                  }`}
                >
                  {s}
                  {data?.snapshots?.[s]?.spot ? (
                    <span className="ml-1 font-mono opacity-80">
                      {data.snapshots[s].spot!.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ConnectionStatus metrics={metrics} />

            {deployment && (
              <span
                className={`text-[10px] px-2 py-1 rounded ${
                  deployment.upstox.validToday
                    ? 'bg-nexus-green/20 text-nexus-green'
                    : 'bg-nexus-red/20 text-nexus-red'
                }`}
              >
                {deployment.upstox.validToday ? 'Broker connected' : 'Broker not connected'}
              </span>
            )}

            {needsUpstox && (
              <a
                href={getLoginUrl()}
                className="px-3 py-1.5 text-[11px] bg-nexus-accent text-black font-bold rounded hover:opacity-90"
              >
                Connect Upstox
              </a>
            )}

            {data?.dataReady && snap && (
              <span className="text-[10px] px-2 py-1 rounded bg-gray-800 text-gray-300">
                {snap.marketPhase.replace('_', ' ')} · TQS {snap.tradeQualityScore.toFixed(0)}
              </span>
            )}

            <div className="flex gap-1 border-l border-nexus-border pl-2">
              <button
                onClick={() => stopTrading()}
                className="px-2 py-1 text-[10px] bg-nexus-red/20 text-nexus-red rounded hover:bg-nexus-red/30"
                title="Pause new paper trades"
              >
                Pause
              </button>
              <button
                onClick={() => resumeTrading()}
                className="px-2 py-1 text-[10px] bg-nexus-green/20 text-nexus-green rounded hover:bg-nexus-green/30"
                title="Resume paper trading"
              >
                Resume
              </button>
              <button
                onClick={() => resetSession()}
                className="px-2 py-1 text-[10px] bg-gray-800 text-gray-400 rounded hover:text-white"
                title="Clear today's paper session"
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1920px] mx-auto p-4">
        <OnboardingBanner
          deployment={deployment}
          dataReady={Boolean(data?.dataReady)}
          waitingReason={data?.waitingReason}
        />

        {loading && !data && (
          <WaitingState reason="Connecting to server..." />
        )}

        {error && !data && (
          <div className="text-center py-16 rounded-lg border border-nexus-red/30 bg-nexus-red/5">
            <p className="text-nexus-red font-bold text-lg">Cannot reach server</p>
            <p className="text-nexus-muted text-sm mt-2 max-w-md mx-auto">{error}</p>
            <button
              onClick={() => refetch()}
              className="mt-4 px-4 py-2 bg-nexus-accent text-black font-bold rounded text-sm hover:opacity-90"
            >
              Try again
            </button>
          </div>
        )}

        {data && !data.dataReady && (
          <WaitingState reason={data.waitingReason} showConnect={Boolean(needsUpstox)} />
        )}

        {data && snap && auto && (
          <div className="grid grid-cols-12 gap-3">
            <div className="col-span-3"><ExecutionHUD snap={snap} auto={auto} /></div>
            <div className="col-span-3"><ExplosiveRunner snap={snap} /></div>
            <div className="col-span-3"><ExplosionRadar snap={snap} /></div>
            <div className="col-span-3"><StrategyRouter snap={snap} /></div>
            <div className="col-span-3"><PaperTrading auto={auto} /></div>

            <div className="col-span-3"><OrderflowAnalytics snap={snap} /></div>
            <div className="col-span-3"><AIMatrix snap={snap} /></div>
            <div className="col-span-2"><GreeksIV snap={snap} /></div>
            <div className="col-span-2"><MarketProfilePanel snap={snap} /></div>
            <div className="col-span-2"><RiskEngine auto={auto} /></div>

            <div className="col-span-3"><OptionHeatmap snap={snap} /></div>
            <div className="col-span-3"><StrategyMatrix snap={snap} /></div>
            <div className="col-span-2"><TradeJournal data={data} history={tradeHistory} /></div>
            <div className="col-span-2"><NewsPanel news={data.news} /></div>
            <div className="col-span-1"><LiveTradingGate status={deployment} /></div>
            <div className="col-span-1"><MorningChecklist deployment={deployment} dataReady={data.dataReady} /></div>
          </div>
        )}

        <footer className="mt-4 pt-3 border-t border-nexus-border flex flex-wrap justify-between gap-2">
          <LatencyFooter metrics={metrics} />
          <span className="text-[10px] text-nexus-muted">
            Explosion capture · 12–25pt targets · Paper only
            {deployment ? ` · ${deployment.environment}` : ''}
          </span>
        </footer>
      </main>
    </div>
  );
}
