import { Panel } from './Panel';
import type { DeploymentReadiness, DeploymentStatus } from '../types';

export function LiveTradingGate({
  status,
  readiness,
}: {
  status: DeploymentStatus | null;
  readiness?: DeploymentReadiness | null;
}) {
  if (!status) return <Panel title="Live Trading Gate"><p className="text-xs text-nexus-muted">Loading...</p></Panel>;

  const log = status.tradeLog;
  const checks = [
    { label: 'Broker connected today', ok: status.upstox.validToday },
    { label: 'Token stored', ok: status.upstox.hasToken },
    { label: 'Trade log writable', ok: log?.writable ?? false },
    { label: 'Auto trading', ok: status.flags.autoTradingEnabled as boolean },
    { label: 'Paper mode', ok: status.flags.paperTrading as boolean },
    { label: 'Live trading', ok: status.flags.enableLiveTrading as boolean },
    { label: 'Risk engine', ok: readiness?.checks.riskEngineOk ?? true },
    { label: 'Paper ready', ok: readiness?.readyForPaper ?? false },
    { label: '50-trade milestone', ok: readiness?.milestone?.readyForLiveMilestone ?? readiness?.checks.milestonePassed ?? false },
    { label: 'Live ready', ok: readiness?.readyForLive ?? false },
  ];

  return (
    <Panel title="System Status" badge={readiness?.executionMode ?? 'PAPER'}>
      <div className="space-y-1.5">
        {checks.map((c) => (
          <div key={c.label} className="flex justify-between text-[11px]">
            <span className="text-nexus-muted">{c.label}</span>
            <span className={c.ok ? 'text-nexus-green' : 'text-nexus-red'}>
              {c.ok ? '✓' : '✗'}
            </span>
          </div>
        ))}
      </div>

      {log && (
        <div className="mt-3 p-2 bg-gray-900/50 border border-nexus-border rounded text-[10px]">
          <div className="text-nexus-muted mb-1">Trade log (paper + live)</div>
          <div className="text-gray-300 font-mono truncate" title={log.logFile}>
            {log.logFile.split('/').slice(-2).join('/')}
          </div>
          <div className="text-nexus-muted mt-1">
            Today: {log.todayClosed} closed · {log.todayOpen} open · {(log.logSizeBytes / 1024).toFixed(1)} KB
          </div>
        </div>
      )}

      <div className="mt-3 p-2 bg-gray-900/50 border border-nexus-border rounded text-[10px]">
        <div className="text-nexus-muted mb-1">Daily token (one login per IST day)</div>
        <div className={status.upstox.validToday ? 'text-nexus-green' : 'text-nexus-yellow'}>
          {status.upstox.message || (status.upstox.canLogin ? 'Login required' : 'Active')}
        </div>
        {status.upstox.generatedAt && (
          <div className="text-nexus-muted mt-1">
            Generated: {new Date(status.upstox.generatedAt).toLocaleString('en-IN')}
          </div>
        )}
      </div>

      {readiness && readiness.armLiveSteps.length > 0 && !readiness.readyForLive && (
        <div className="mt-2 p-2 bg-nexus-yellow/10 border border-nexus-yellow/30 rounded text-[10px]">
          <div className="text-nexus-yellow font-bold mb-1">To arm live trading:</div>
          <ul className="list-disc list-inside text-gray-300 space-y-0.5">
            {readiness.armLiveSteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </div>
      )}

      {readiness?.readyForLive ? (
        <div className="mt-2 p-2 bg-nexus-green/10 border border-nexus-green/30 rounded text-[10px] text-nexus-green">
          Live deployment checklist passed. Trades will log to the same audit file with executionMode=LIVE.
        </div>
      ) : (
        <div className="mt-2 p-2 bg-nexus-red/10 border border-nexus-red/30 rounded text-[10px] text-nexus-red">
          Live trading is OFF by default. Paper trades are logged to trades.log for review before going live.
        </div>
      )}
    </Panel>
  );
}

export function MorningChecklist({
  deployment,
  dataReady,
}: {
  deployment?: import('../types').DeploymentStatus | null;
  dataReady?: boolean;
}) {
  const steps = [
    { label: 'Connect Upstox (once per IST day)', done: deployment?.upstox.validToday },
    { label: 'Server online', done: Boolean(deployment) },
    { label: 'Live prices loading', done: Boolean(dataReady) },
    { label: 'Trade log writable', done: deployment?.tradeLog?.writable },
    { label: 'Paper trading active', done: deployment?.flags.paperTrading as boolean },
    { label: 'Background monitor on', done: deployment?.flags.backgroundMonitor as boolean },
  ];

  return (
    <Panel title="Quick Start">
      <ul className="space-y-2">
        {steps.map((s) => (
          <li key={s.label} className="flex items-center gap-2 text-[11px]">
            <span
              className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] font-bold ${
                s.done ? 'bg-nexus-green text-black' : 'bg-gray-700 text-gray-400'
              }`}
            >
              {s.done ? '✓' : '·'}
            </span>
            <span className={s.done ? 'text-gray-300' : 'text-nexus-muted'}>{s.label}</span>
          </li>
        ))}
      </ul>
      {deployment && !deployment.upstox.validToday && (
        <a
          href="/api/upstox/login"
          className="mt-3 block text-center rounded bg-nexus-accent/90 px-2 py-1.5 text-[10px] font-bold text-black hover:opacity-90"
        >
          Login to Upstox
        </a>
      )}
    </Panel>
  );
}
