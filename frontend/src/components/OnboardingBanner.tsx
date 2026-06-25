import type { DeploymentStatus } from '../types';
import { getLoginUrl } from '../hooks/useMarketStream';

export function OnboardingBanner({
  deployment,
  dataReady,
  waitingReason,
}: {
  deployment: DeploymentStatus | null;
  dataReady: boolean;
  waitingReason?: string;
}) {
  if (dataReady) return null;

  const upstoxOk = deployment?.upstox.validToday;
  const backendOk = Boolean(deployment);

  const steps = [
    {
      label: 'Server connected',
      done: backendOk,
      hint: 'Backend API is reachable',
    },
    {
      label: 'Upstox login (once per day)',
      done: upstoxOk,
      hint: deployment?.upstox.message || 'Connect your broker account',
      action: !upstoxOk ? getLoginUrl() : undefined,
      actionLabel: 'Connect Upstox',
    },
    {
      label: 'Live market data',
      done: dataReady,
      hint: waitingReason || 'Waiting for market hours and real prices',
    },
  ];

  return (
    <div className="mb-4 rounded-lg border border-nexus-accent/30 bg-gradient-to-r from-nexus-accent/5 to-transparent p-4">
      <h2 className="text-sm font-bold text-white mb-1">Get started in 3 steps</h2>
      <p className="text-xs text-nexus-muted mb-4">
        NexusQuant uses real Upstox prices only — no dummy data.
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        {steps.map((step, i) => (
          <div
            key={step.label}
            className={`rounded-lg border p-3 ${
              step.done
                ? 'border-nexus-green/40 bg-nexus-green/5'
                : 'border-nexus-border bg-black/20'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                  step.done ? 'bg-nexus-green text-black' : 'bg-gray-700 text-gray-300'
                }`}
              >
                {step.done ? '✓' : i + 1}
              </span>
              <span className="text-xs font-semibold text-gray-200">{step.label}</span>
            </div>
            <p className="text-[10px] text-nexus-muted leading-relaxed">{step.hint}</p>
            {step.action && (
              <a
                href={step.action}
                className="mt-2 inline-block rounded bg-nexus-accent px-3 py-1.5 text-[11px] font-bold text-black hover:opacity-90"
              >
                {step.actionLabel}
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
