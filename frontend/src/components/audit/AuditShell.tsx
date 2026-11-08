import type { ReactNode } from 'react';
import type { DeploymentStatus } from '../../types';
import type { MarketSessionInfo } from '../../lib/marketSession';
import { ConnectionStatus, LatencyFooter } from '../ConnectionStatus';
import { getLoginUrl } from '../../hooks/useMarketStream';
import type { StreamMetrics } from '../../types';

export type AuditPage = 'pnl' | 'analysis';

const SYMBOLS = ['NIFTY', 'SENSEX'] as const;

export function AuditShell({
  page,
  onPageChange,
  activeSymbol,
  onSymbolChange,
  deployment,
  metrics,
  session,
  dataReady,
  executionLabel,
  children,
  footerExtra,
}: {
  page: AuditPage;
  onPageChange: (p: AuditPage) => void;
  activeSymbol: string;
  onSymbolChange: (s: string) => void;
  deployment: DeploymentStatus | null;
  metrics: StreamMetrics;
  session: MarketSessionInfo;
  dataReady: boolean;
  executionLabel: string;
  children: ReactNode;
  footerExtra?: string;
}) {
  const needsUpstox = deployment && !deployment.upstox.validToday;
  const marketPhase = (session.phase ?? 'CLOSED').replace(/_/g, ' ');

  const navLink = (id: AuditPage, label: string) => (
    <button
      type="button"
      onClick={() => onPageChange(id)}
      className={`audit-nav-link ${page === id ? 'audit-nav-link-active' : ''}`}
    >
      {label}
    </button>
  );

  return (
    <div className="min-h-screen text-gray-100 audit-shell overflow-anchor-none">
      <header className="audit-header border-b border-nexus-border/80 sticky top-0 z-50">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-6 min-w-0">
            <div className="flex items-center gap-2.5 shrink-0">
              <div className="h-9 w-9 rounded-md bg-gradient-to-br from-nexus-accent/90 to-emerald-600 flex items-center justify-center">
                <span className="text-[11px] font-black text-black">NQ</span>
              </div>
              <span className="text-lg font-semibold tracking-tight text-white">NexusQuant</span>
            </div>
            <nav className="hidden sm:flex items-center gap-1 text-[13px]">
              {navLink('pnl', 'Profits & loss')}
              {navLink('analysis', 'Analysis')}
            </nav>
          </div>

          <div className="flex items-center gap-2 flex-wrap justify-end">
            <ConnectionStatus metrics={metrics} session={session} dataReady={dataReady} />
            <span className="audit-badge audit-badge-muted">{executionLabel}</span>
            <span className="audit-badge audit-badge-muted">{marketPhase}</span>
            {needsUpstox ? (
              <a href={getLoginUrl()} className="audit-btn-primary text-[11px]">
                Connect Upstox
              </a>
            ) : null}
          </div>
        </div>

        <div className="sm:hidden max-w-[1600px] mx-auto px-4 pb-3 flex gap-2">
          {navLink('pnl', 'P&L')}
          {navLink('analysis', 'Analysis')}
        </div>

        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 pb-2 flex gap-1">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onSymbolChange(s)}
              className={`symbol-tab text-[11px] py-1 ${activeSymbol === s ? 'symbol-tab-active' : 'symbol-tab-idle'}`}
            >
              {s}
            </button>
          ))}
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto px-4 sm:px-6 py-5 sm:py-6">{children}</main>

      <footer className="border-t border-nexus-border/60 max-w-[1600px] mx-auto px-4 sm:px-6 py-4 flex flex-wrap justify-between gap-3">
        <LatencyFooter metrics={metrics} />
        <span className="text-[10px] text-nexus-muted leading-relaxed">
          NexusQuant terminal
          {footerExtra ? ` · ${footerExtra}` : ''}
          {deployment ? ` · ${deployment.environment} · ${deployment.commit}` : ''}
        </span>
      </footer>
    </div>
  );
}
