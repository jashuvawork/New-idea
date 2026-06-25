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
    <div className={`bg-nexus-panel border border-nexus-border rounded-lg overflow-hidden ${className}`}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-nexus-border bg-black/20">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">{title}</h3>
        {badge && (
          <span className={`text-[10px] px-2 py-0.5 rounded-full ${badgeColor} text-black font-bold`}>
            {badge}
          </span>
        )}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

export function Metric({ label, value, color = 'text-white' }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-nexus-muted uppercase">{label}</span>
      <span className={`text-lg font-mono font-bold ${color}`}>{value}</span>
    </div>
  );
}

export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  const color = pct >= 75 ? 'bg-nexus-green' : pct >= 50 ? 'bg-nexus-yellow' : 'bg-nexus-red';
  return (
    <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
      <div className={`h-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function BiasBadge({ bias }: { bias: string }) {
  const colors: Record<string, string> = {
    BULLISH: 'text-nexus-green border-nexus-green',
    BEARISH: 'text-nexus-red border-nexus-red',
    NEUTRAL: 'text-nexus-muted border-nexus-muted',
  };
  return (
    <span className={`text-xs font-bold border px-2 py-0.5 rounded ${colors[bias] || colors.NEUTRAL}`}>
      {bias}
    </span>
  );
}

export function WaitingState({ reason, showConnect = true }: { reason?: string; showConnect?: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center h-56 text-center rounded-lg border border-nexus-border bg-nexus-panel/50">
      <div className="w-10 h-10 border-2 border-nexus-accent border-t-transparent rounded-full animate-spin mb-4" />
      <p className="text-white font-semibold text-base">Waiting for live market data</p>
      <p className="text-nexus-muted text-sm mt-2 max-w-md px-4">
        {reason || 'Connect Upstox once per day to load real prices'}
      </p>
      {showConnect && (
        <a
          href="/api/upstox/login"
          className="mt-4 px-5 py-2.5 bg-nexus-accent text-black font-bold rounded text-sm hover:opacity-90"
        >
          Connect Upstox
        </a>
      )}
    </div>
  );
}
