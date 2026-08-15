import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  FtvAllocationRow,
  UpstoxBrokerOrder,
  UpstoxBrokerPosition,
  UpstoxManagerTrade,
  UpstoxTradeOverview,
} from '../types';

const API_BASE = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '');
type Tab = 'positions' | 'trades' | 'orders';

function money(value: number | undefined): string {
  return `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

function pnlTone(value: number): string {
  return value >= 0 ? 'text-nexus-green' : 'text-nexus-red';
}

function CapitalCard({
  label,
  value,
  detail,
  tone = 'text-white',
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-nexus-border bg-black/25 p-3 min-w-0">
      <div className="text-[9px] uppercase tracking-wider text-nexus-muted">{label}</div>
      <div className={`mt-1 font-mono text-lg font-bold truncate ${tone}`}>{value}</div>
      <div className="mt-1 text-[9px] text-nexus-muted truncate">{detail}</div>
    </div>
  );
}

function AllocationRow({ row }: { row: FtvAllocationRow }) {
  const statusTone =
    row.status === 'OPENED'
      ? 'text-nexus-green'
      : row.status === 'REJECTED' || row.status === 'SKIPPED'
        ? 'text-nexus-red'
        : 'text-nexus-accent';
  return (
    <div className="grid grid-cols-[2rem_minmax(8rem,1fr)_5rem_6rem] items-center gap-2 rounded-lg border border-nexus-border/70 bg-black/20 px-2.5 py-2 text-[10px]">
      <span className="font-mono text-nexus-accent">#{row.rank ?? '—'}</span>
      <div className="min-w-0">
        <div className="truncate font-semibold">
          {row.symbol} {row.side} {row.strike}
          {row.lots ? ` ×${row.lots}` : ''}
        </div>
        <div className="truncate text-[9px] text-nexus-muted">
          {[row.tier, row.score != null ? `score ${row.score.toFixed(0)}` : null, row.reason]
            .filter(Boolean)
            .join(' · ') || 'FTV allocation sleeve'}
        </div>
      </div>
      <span className={`truncate text-right text-[9px] font-semibold ${statusTone}`}>
        {row.status || 'ACTIVE'}
      </span>
      <span className="text-right font-mono">
        {money(row.committedInr ?? row.budgetInr)}
      </span>
    </div>
  );
}

function BrokerPositionRow({ row }: { row: UpstoxBrokerPosition }) {
  return (
    <div className="grid grid-cols-[minmax(9rem,1fr)_4rem_6rem_6rem] gap-2 border-b border-nexus-border/60 px-2 py-2 text-[10px] last:border-0">
      <div className="min-w-0">
        <div className="truncate font-semibold">{row.tradingSymbol || row.instrumentKey || 'Position'}</div>
        <div className="text-[9px] text-nexus-muted">{row.exchange} · {row.product}</div>
      </div>
      <span className="text-right font-mono">{row.quantity}</span>
      <span className="text-right font-mono">{money(row.lastPrice)}</span>
      <span className={`text-right font-mono font-bold ${pnlTone(row.pnlInr)}`}>
        {money(row.pnlInr)}
      </span>
    </div>
  );
}

function StrategyTradeRow({ row }: { row: UpstoxManagerTrade }) {
  return (
    <div className="grid grid-cols-[minmax(9rem,1fr)_4rem_6rem_6rem] gap-2 border-b border-nexus-border/60 px-2 py-2 text-[10px] last:border-0">
      <div className="min-w-0">
        <div className="truncate font-semibold">
          {row.symbol} {row.side} {row.strike}
        </div>
        <div className="truncate text-[9px] text-nexus-muted">
          {row.tier || row.status}
          {row.allocationRank ? ` · allocation #${row.allocationRank}` : ''}
          {row.exitReason ? ` · ${row.exitReason}` : ''}
        </div>
      </div>
      <span className="text-right font-mono">×{row.lots}</span>
      <span className="text-right font-mono">{money(row.allocatedCostInr ?? row.entryPremium * row.lots)}</span>
      <span className={`text-right font-mono font-bold ${pnlTone(row.pnlInr)}`}>
        {money(row.pnlInr)}
      </span>
    </div>
  );
}

function OrderRow({ row }: { row: UpstoxBrokerOrder }) {
  const ok = ['complete', 'completed', 'filled'].includes(String(row.status || '').toLowerCase());
  return (
    <div className="grid grid-cols-[minmax(9rem,1fr)_4rem_6rem_6rem] gap-2 border-b border-nexus-border/60 px-2 py-2 text-[10px] last:border-0">
      <div className="min-w-0">
        <div className="truncate font-semibold">{row.tradingSymbol || row.orderId || 'Order'}</div>
        <div className="truncate text-[9px] text-nexus-muted">
          {row.transactionType} · {row.orderType} · {row.product}
        </div>
      </div>
      <span className="text-right font-mono">{row.filledQuantity}/{row.quantity}</span>
      <span className="text-right font-mono">{money(row.averagePrice || row.price)}</span>
      <span className={`truncate text-right text-[9px] font-semibold ${ok ? 'text-nexus-green' : 'text-nexus-yellow'}`}>
        {row.status || 'UNKNOWN'}
      </span>
    </div>
  );
}

export function UpstoxTradeManagerPanel() {
  const [overview, setOverview] = useState<UpstoxTradeOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('positions');
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const response = await fetch(`${API_BASE}/api/upstox-trading/overview`);
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? 'Deploy the matching Upstox trade-manager backend.'
            : `Trade manager request failed (${response.status})`,
        );
      }
      const payload = (await response.json()) as UpstoxTradeOverview;
      if (id !== requestId.current) return;
      setOverview(payload);
      setError(null);
    } catch (reason) {
      if (id !== requestId.current) return;
      setError(reason instanceof Error ? reason.message : 'Trade manager unavailable');
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(interval);
  }, [load]);

  const allocation = overview?.allocation;
  const capital = overview?.capital;
  const committed = allocation?.committedInr ?? 0;
  const remaining = allocation?.remainingInr ?? 0;
  const reserve = allocation?.cashReserveInr ?? 0;
  const capitalBase = allocation?.capitalBaseInr ?? capital?.totalEquityInr ?? 0;
  const strategyMode = overview?.executionMode !== 'LIVE';
  const netPnl = strategyMode ? overview?.pnl.strategyNetInr ?? 0 : overview?.pnl.brokerNetInr ?? 0;
  const realized = strategyMode ? overview?.pnl.strategyRealizedInr ?? 0 : overview?.pnl.brokerRealizedInr ?? 0;
  const unrealized = strategyMode ? overview?.pnl.strategyUnrealizedInr ?? 0 : overview?.pnl.brokerUnrealizedInr ?? 0;
  const allocationRows = [
    ...(allocation?.activeAllocations || []).map((row) => ({ ...row, status: 'OPENED' })),
    ...(allocation?.plannedAllocations || []).filter((row) => row.status !== 'OPENED'),
  ].sort((a, b) => Number(a.rank || 99) - Number(b.rank || 99));

  return (
    <section className="rounded-xl border border-nexus-border bg-nexus-panel shadow-panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-nexus-border px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold">Upstox Trade Manager</h2>
            <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold ${
              overview?.executionMode === 'LIVE'
                ? 'border-nexus-red/40 bg-nexus-red/10 text-nexus-red'
                : 'border-nexus-accent/40 bg-nexus-accent/10 text-nexus-accent'
            }`}>
              {overview?.executionMode || 'LOADING'}
            </span>
            <span className={`rounded border px-1.5 py-0.5 text-[9px] ${
              overview?.broker.connected
                ? 'border-nexus-green/30 text-nexus-green'
                : 'border-nexus-yellow/30 text-nexus-yellow'
            }`}>
              {overview?.broker.connected ? 'UPSTOX CONNECTED' : 'BROKER OFFLINE'}
            </span>
          </div>
          <p className="mt-1 text-[10px] text-nexus-muted">
            Ranked flat-to-vertical allocation: strongest approved setup first, then remaining capital to the next.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="min-h-10 rounded-lg border border-nexus-border bg-black/20 px-3 text-[10px] text-nexus-muted hover:text-white"
        >
          Refresh
        </button>
      </div>

      {error ? (
        <div role="alert" className="m-4 rounded-lg border border-nexus-yellow/30 bg-nexus-yellow/5 px-3 py-2 text-[10px] text-nexus-yellow">
          {error}
        </div>
      ) : null}
      {overview && !overview.broker.complete ? (
        <div role="status" className="mx-4 mt-4 rounded-lg border border-nexus-yellow/20 bg-nexus-yellow/5 px-3 py-2 text-[10px] text-nexus-yellow">
          Broker data is partial. Strategy trades and paper P&amp;L remain available; reconnect Upstox for live funds, positions, and orders.
        </div>
      ) : null}

      <div className="p-4">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <CapitalCard label="Capital X" value={money(capitalBase)} detail={`${capital?.source || 'fallback'} sizing book`} tone="text-nexus-accent" />
          <CapitalCard label="Allocated Y" value={money(committed)} detail={`${allocation?.utilizationPct ?? 0}% deployed`} />
          <CapitalCard label="Left Z = X − Y − reserve" value={money(remaining)} detail={`${money(reserve)} protected cash`} tone="text-nexus-green" />
          <CapitalCard label="Session P&L" value={money(netPnl)} detail={`${money(realized)} realized · ${money(unrealized)} live`} tone={pnlTone(netPnl)} />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1.85fr)]">
          <div className="rounded-lg border border-nexus-border bg-black/15 p-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h3 className="text-[11px] font-bold">Capital allocation queue</h3>
                <p className="text-[9px] text-nexus-muted">
                  {(allocation?.weights || []).map((weight) => `${Math.round(weight * 100)}%`).join(' → ') || '60% → 25% → 10%'} · {money(reserve)} reserve
                </p>
              </div>
              <span className="text-[9px] text-nexus-muted">
                max {allocation?.maxPositions ?? 3} positions
              </span>
            </div>
            <div className="mt-2 space-y-1.5 max-h-56 overflow-y-auto">
              {allocationRows.length ? (
                allocationRows.map((row, index) => (
                  <AllocationRow key={`${row.tradeId || row.key || index}-${row.status}`} row={row} />
                ))
              ) : (
                <div className="rounded-lg border border-dashed border-nexus-border px-3 py-6 text-center text-[10px] text-nexus-muted">
                  Waiting for approved FTV candidates. No capital is reserved for an unapproved signal.
                </div>
              )}
            </div>
            <div className="mt-2 rounded bg-nexus-accent/5 px-2 py-1.5 text-[9px] text-nexus-muted">
              Lot size, premium, stop risk, margin, duplicate-leg, same-side, and session-loss gates still apply. Returns are not guaranteed.
            </div>
          </div>

          <div className="rounded-lg border border-nexus-border bg-black/15 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-nexus-border px-3 py-2">
              <div className="flex gap-1" role="tablist" aria-label="Upstox trade manager views">
                {([
                  ['positions', `Positions ${overview?.brokerPositions.length ?? 0}`],
                  ['trades', `Strategy trades ${(overview?.strategyTrades.open.length ?? 0) + (overview?.strategyTrades.closed.length ?? 0)}`],
                  ['orders', `Orders ${overview?.brokerOrders.length ?? 0}`],
                ] as Array<[Tab, string]>).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={tab === key}
                    onClick={() => setTab(key)}
                    className={`min-h-9 rounded px-2.5 text-[9px] font-semibold ${
                      tab === key ? 'bg-nexus-accent/15 text-nexus-accent' : 'text-nexus-muted hover:text-white'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="flex gap-3 text-[9px]">
                <span className="text-nexus-green">W {overview?.pnl.wins ?? 0}</span>
                <span className="text-nexus-red">L {overview?.pnl.losses ?? 0}</span>
                <span className="text-nexus-muted">PF {(overview?.pnl.profitFactor ?? 0).toFixed(2)}</span>
              </div>
            </div>

            <div className="grid grid-cols-[minmax(9rem,1fr)_4rem_6rem_6rem] gap-2 bg-black/25 px-2 py-1.5 text-[8px] uppercase tracking-wider text-nexus-muted">
              <span>{tab === 'orders' ? 'Order' : tab === 'positions' ? 'Broker position' : 'Strategy trade'}</span>
              <span className="text-right">{tab === 'orders' ? 'Fill' : tab === 'positions' ? 'Qty' : 'Lots'}</span>
              <span className="text-right">{tab === 'orders' ? 'Price' : tab === 'positions' ? 'LTP' : 'Capital'}</span>
              <span className="text-right">{tab === 'orders' ? 'Status' : 'P&L'}</span>
            </div>
            <div className="max-h-72 overflow-auto" role="tabpanel">
              {loading && !overview ? (
                <div className="p-6 text-center text-[10px] text-nexus-muted">Loading Upstox account…</div>
              ) : tab === 'positions' ? (
                overview?.brokerPositions.length ? overview.brokerPositions.map((row, index) => (
                  <BrokerPositionRow key={row.instrumentKey || `${row.tradingSymbol}-${index}`} row={row} />
                )) : <div className="p-6 text-center text-[10px] text-nexus-muted">No live broker positions</div>
              ) : tab === 'trades' ? (
                [...(overview?.strategyTrades.open || []), ...(overview?.strategyTrades.closed || [])].length
                  ? [...(overview?.strategyTrades.open || []), ...(overview?.strategyTrades.closed || [])].map((row) => (
                    <StrategyTradeRow key={`${row.status}-${row.id}`} row={row} />
                  ))
                  : <div className="p-6 text-center text-[10px] text-nexus-muted">No strategy trades today</div>
              ) : overview?.brokerOrders.length ? overview.brokerOrders.map((row, index) => (
                <OrderRow key={row.orderId || index} row={row} />
              )) : <div className="p-6 text-center text-[10px] text-nexus-muted">No broker orders available</div>}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
