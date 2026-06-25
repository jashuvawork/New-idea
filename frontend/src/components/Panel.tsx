import { ReactNode } from 'react';

interface PanelProps {
  title: string;
  children: ReactNode;
  className?: string;
  badge?: string;
  badgeColor?: string;
}

export function Panel({ title, children, className = '', badge, badgeColor = 'bg-nexus-accent' }: PanelProps) {
  return (
    <div className={`panel-card h-full flex flex-col ${className}`}>
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5 border-b border-nexus-border bg-gradient-to-r from-black/30 to-transparent">
        <div className="flex items-center gap-2 min-w-0">
          <span className="h-3.5 w-0.5 shrink-0 rounded-full bg-nexus-accent/80" aria-hidden />
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-300 truncate">
            {title}
          </h3>
        </div>
        {badge ? (
          <span className={`shrink-0 text-[10px] px-2 py-0.5 rounded-md ${badgeColor} text-black font-bold`}>
            {badge}
          </span>
        ) : null}
      </div>
      <div className="p-3.5 flex-1">{children}</div>
    </div>
  );
}

export function Metric({ label, value, color = 'text-white' }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] text-nexus-muted uppercase tracking-wide">{label}</span>
      <span className={`text-xl font-mono font-bold leading-tight ${color}`}>{value}</span>
    </div>
  );
}

export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  const color = pct >= 75 ? 'bg-nexus-green' : pct >= 50 ? 'bg-nexus-yellow' : 'bg-nexus-red';
  return (
    <div className="w-full h-2 bg-gray-800/80 rounded-full overflow-hidden">
      <div
        className={`h-full ${color} transition-all duration-500 rounded-full`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function BiasBadge({ bias }: { bias: string }) {
  const colors: Record<string, string> = {
    BULLISH: 'text-nexus-green border-nexus-green/50 bg-nexus-green/10',
    BEARISH: 'text-nexus-red border-nexus-red/50 bg-nexus-red/10',
    NEUTRAL: 'text-nexus-muted border-nexus-border bg-black/20',
  };
  return (
    <span className={`text-[11px] font-bold border px-2 py-0.5 rounded-md ${colors[bias] || colors.NEUTRAL}`}>
      {bias}
    </span>
  );
}

export function WaitingState({ reason, showConnect = true }: { reason?: string; showConnect?: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[14rem] text-center rounded-xl border border-nexus-border bg-nexus-panel/60 shadow-panel">
      <div className="w-10 h-10 border-2 border-nexus-accent border-t-transparent rounded-full animate-spin mb-4" />
      <p className="text-white font-semibold text-base">Waiting for live market data</p>
      <p className="text-nexus-muted text-sm mt-2 max-w-md px-4 leading-relaxed">
        {reason || 'Connect Upstox once per day to load real prices'}
      </p>
      {showConnect ? (
        <a
          href="/api/upstox/login"
          className="mt-5 px-5 py-2.5 bg-nexus-accent text-black font-bold rounded-lg text-sm hover:opacity-90 shadow-glow-accent"
        >
          Connect Upstox
        </a>
      ) : null}
    </div>
  );
}
