import { Panel } from './Panel';
import type { DeploymentStatus } from '../types';

export function LiveTradingGate({ status }: { status: DeploymentStatus | null }) {
  if (!status) return <Panel title="Live Trading Gate"><p className="text-xs text-nexus-muted">Loading...</p></Panel>;

  const checks = [
    { label: 'Upstox Token', ok: status.upstox.hasToken },
    { label: 'Valid Today', ok: status.upstox.validToday },
    { label: 'Paper Trading', ok: status.flags.paperTrading as boolean },
    { label: 'Live Trading', ok: status.flags.enableLiveTrading as boolean },
    { label: 'Enhanced Mode', ok: status.flags.enhancedMode as boolean },
    { label: 'Background Monitor', ok: status.flags.backgroundMonitor as boolean },
    { label: 'Simple Profit', ok: status.flags.simpleProfitMode as boolean },
  ];

  return (
    <Panel title="Live Trading Gate">
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
      <div className="mt-2 p-2 bg-nexus-red/10 border border-nexus-red/30 rounded text-[10px] text-nexus-red">
        Live trading is OFF by default. Set ENABLE_LIVE_TRADING=true only after readiness checks pass.
      </div>
    </Panel>
  );
}

export function MorningChecklist() {
  const steps = [
    'Authenticate Upstox once per IST trading day via /api/upstox/login',
    'Verify /health returns status: ok',
    'Confirm snapshots show real LTP (not waiting state)',
    'Check TQS > 68 and breadth alignment',
    'Set capital via POST /api/capital',
    'Enable background monitor for unattended paper trades',
    'Review calibration blocks before session',
  ];

  return (
    <Panel title="Morning Checklist">
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-2 text-[11px]">
            <span className="text-nexus-accent font-bold">{i + 1}.</span>
            <span className="text-gray-300">{s}</span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
