import type { PaperTrade } from '../types';

const LOT_SIZE: Record<string, number> = {
  NIFTY: 65,
  BANKNIFTY: 30,
  SENSEX: 20,
};

export function tradeQuantity(trade: PaperTrade): number {
  if (trade.quantity && trade.quantity > 0) return trade.quantity;
  const ctx = trade.entryContext || trade.context || {};
  if (typeof ctx.quantity === 'number' && ctx.quantity > 0) return ctx.quantity;
  if (typeof ctx.brokerQuantity === 'number' && ctx.brokerQuantity > 0) return ctx.brokerQuantity;
  const lotSize = typeof ctx.lotSize === 'number' ? ctx.lotSize : LOT_SIZE[trade.symbol] ?? 65;
  return trade.lots * lotSize;
}

export function tradeBuyLtp(trade: PaperTrade): number {
  return trade.entryPremium;
}

export function tradeSoldLtp(trade: PaperTrade, open = false): number | null {
  if (open) {
    return trade.currentPremium ?? null;
  }
  if (trade.exitPremium != null) return trade.exitPremium;
  const ctx = trade.entryContext || trade.context || {};
  if (typeof ctx.exitPremium === 'number') return ctx.exitPremium;
  return trade.currentPremium ?? null;
}

export function formatTradeTime(iso?: string): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  });
}

export function formatTradeDateTime(iso?: string): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  });
}

export function formatLtp(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(2);
}
