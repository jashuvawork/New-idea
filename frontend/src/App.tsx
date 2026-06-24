import { useState } from 'react';
import { useMarketStream, useDeploymentStatus, stopTrading, resumeTrading, resetSession } from './hooks/useMarketStream';
import { WaitingState } from './components/Panel';
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

const SYMBOLS = ['NIFTY', 'SENSEX', 'BANKNIFTY'] as const;

export default function App() {
  const { data, error, loading } = useMarketStream();
  const deployment = useDeploymentStatus();
  const [activeSymbol, setActiveSymbol] = useState<string>('NIFTY');

  const snap = data?.snapshots?.[activeSymbol];
  const auto = data?.autoTrader;

  return (
    <div className="min-h-screen bg-nexus-bg">
      {/* Header */}
      <header className="border-b border-nexus-border bg-nexus-panel/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-[1920px] mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold">
              <span className="text-nexus-accent">Nexus</span>Quant
              <span className="text-[10px] ml-2 text-nexus-muted font-normal">v2.0 ENHANCED</span>
            </h1>
            <div className="flex gap-1">
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  onClick={() => setActiveSymbol(s)}
                  className={`px-3 py-1 text-xs font-bold rounded transition-colors ${
                    activeSymbol === s
                      ? 'bg-nexus-accent text-black'
                      : 'bg-gray-800 text-gray-400 hover:text-white'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {deployment && (
              <span className={`text-[10px] px-2 py-1 rounded ${
                deployment.upstox.hasToken ? 'bg-nexus-green/20 text-nexus-green' : 'bg-nexus-red/20 text-nexus-red'
              }`}>
                {deployment.upstox.hasToken ? 'UPSTOX ✓' : 'UPSTOX ✗'}
              </span>
            )}
            {data?.dataReady && (
              <span className="text-[10px] text-nexus-green animate-pulse">● LIVE DATA</span>
            )}
            <button
              onClick={() => stopTrading()}
              className="px-2 py-1 text-[10px] bg-nexus-red/20 text-nexus-red rounded hover:bg-nexus-red/30"
            >
              STOP
            </button>
            <button
              onClick={() => resumeTrading()}
              className="px-2 py-1 text-[10px] bg-nexus-green/20 text-nexus-green rounded hover:bg-nexus-green/30"
            >
              RESUME
            </button>
            <button
              onClick={() => resetSession()}
              className="px-2 py-1 text-[10px] bg-gray-800 text-gray-400 rounded hover:text-white"
            >
              RESET
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1920px] mx-auto p-4">
        {loading && !data && (
          <WaitingState reason="Connecting to NexusQuant backend..." />
        )}

        {error && !data && (
          <div className="text-center py-20">
            <p className="text-nexus-red font-bold">Backend unreachable</p>
            <p className="text-nexus-muted text-sm mt-2">{error}</p>
          </div>
        )}

        {data && !data.dataReady && (
          <WaitingState reason={data.waitingReason} />
        )}

        {data && snap && auto && (
          <div className="grid grid-cols-12 gap-3">
            {/* Row 1 — Primary execution */}
            <div className="col-span-3"><ExecutionHUD snap={snap} auto={auto} /></div>
            <div className="col-span-3"><ExplosiveRunner snap={snap} /></div>
            <div className="col-span-3"><StrategyRouter snap={snap} /></div>
            <div className="col-span-3"><PaperTrading auto={auto} /></div>

            {/* Row 2 — Analytics */}
            <div className="col-span-3"><OrderflowAnalytics snap={snap} /></div>
            <div className="col-span-3"><AIMatrix snap={snap} /></div>
            <div className="col-span-2"><GreeksIV snap={snap} /></div>
            <div className="col-span-2"><MarketProfilePanel snap={snap} /></div>
            <div className="col-span-2"><RiskEngine auto={auto} /></div>

            {/* Row 3 — Depth */}
            <div className="col-span-4"><OptionHeatmap snap={snap} /></div>
            <div className="col-span-3"><TradeJournal data={data} /></div>
            <div className="col-span-2"><NewsPanel news={data.news} /></div>
            <div className="col-span-1.5"><LiveTradingGate status={deployment} /></div>
            <div className="col-span-1.5"><MorningChecklist /></div>
          </div>
        )}

        {/* Footer status bar */}
        <footer className="mt-4 pt-3 border-t border-nexus-border flex justify-between text-[10px] text-nexus-muted">
          <span>
            Poll: 3s · Mode: Enhanced Simple Profit · Micro lock: 2.5pt · TQS entry: 68 · Vel: 1.8%
          </span>
          <span>
            {data?.timestamp ? `Last update: ${new Date(data.timestamp).toLocaleTimeString('en-IN')}` : ''}
            {deployment ? ` · ${deployment.environment} · ${deployment.commit}` : ''}
          </span>
        </footer>
      </main>
    </div>
  );
}
