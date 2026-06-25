import { useEffect, useState } from 'react';
import { Panel } from './Panel';
import type { ConstituentHeatmap } from '../types';

const API_BASE = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '');

function tileColor(pct: number): string {
  if (pct >= 2) return 'bg-emerald-600';
  if (pct >= 0.5) return 'bg-emerald-700/90';
  if (pct > 0.05) return 'bg-emerald-900/80';
  if (pct <= -2) return 'bg-red-600';
  if (pct <= -0.5) return 'bg-red-700/90';
  if (pct < -0.05) return 'bg-red-900/80';
  return 'bg-gray-700';
}

export function MarketHeatmap({
  symbol,
  embedded,
}: {
  symbol: string;
  embedded?: ConstituentHeatmap | null;
}) {
  const [data, setData] = useState<ConstituentHeatmap | null>(embedded ?? null);
  const [hover, setHover] = useState<ConstituentHeatmap['tiles'][0] | null>(null);

  useEffect(() => {
    if (embedded) {
      setData(embedded);
      return;
    }
    const load = () => {
      fetch(`${API_BASE}/api/market/constituents/${symbol}`)
        .then((r) => r.json())
        .then(setData)
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 45_000);
    return () => clearInterval(id);
  }, [symbol, embedded]);

  if (!data) {
    return (
      <Panel title="Market Heatmap">
        <p className="text-xs text-nexus-muted text-center py-6">Loading constituents…</p>
      </Panel>
    );
  }

  if (!data.dataAvailable) {
    return (
      <Panel title="Market Heatmap" badge={data.indexLabel || symbol}>
        <p className="text-xs text-nexus-muted text-center py-4">{data.error || 'No data'}</p>
      </Panel>
    );
  }

  const maxWeight = Math.max(...data.tiles.map((t) => t.weight), 1);

  return (
    <Panel title="Market Heatmap" badge={data.indexLabel}>
      <div className="grid grid-cols-4 gap-2 mb-3">
        <div className="text-center">
          <div className="text-[10px] text-nexus-muted">Stocks</div>
          <div className="text-sm font-bold font-mono">{data.stockCount}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-nexus-muted">Advancing</div>
          <div className="text-sm font-bold font-mono text-nexus-green">{data.advancing}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-nexus-muted">Declining</div>
          <div className="text-sm font-bold font-mono text-nexus-red">{data.declining}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] text-nexus-muted">Breadth</div>
          <div
            className={`text-sm font-bold font-mono ${
              data.breadthPct >= 55 ? 'text-nexus-green' : data.breadthPct <= 45 ? 'text-nexus-red' : 'text-nexus-yellow'
            }`}
          >
            {data.breadthPct}%
          </div>
        </div>
      </div>

      {hover && (
        <div className="mb-2 p-2 rounded border border-nexus-accent/40 bg-black/40 text-[10px]">
          <div className="font-bold text-white">{hover.symbol} · {hover.name}</div>
          <div className="grid grid-cols-3 gap-2 mt-1 font-mono text-gray-300">
            <span>LTP ₹{hover.ltp.toFixed(2)}</span>
            <span className={hover.changePct >= 0 ? 'text-nexus-green' : 'text-nexus-red'}>
              {hover.changePct >= 0 ? '+' : ''}{hover.changePct}%
            </span>
            <span>VWAP ₹{hover.vwap.toFixed(2)}</span>
            <span>H ₹{hover.high.toFixed(2)}</span>
            <span>L ₹{hover.low.toFixed(2)}</span>
            <span>Vol {(hover.volume / 1000).toFixed(0)}k</span>
          </div>
        </div>
      )}

      <div
        className="flex flex-wrap gap-1 max-h-52 overflow-y-auto content-start"
        style={{ minHeight: '140px' }}
      >
        {data.tiles.map((t) => {
          const flexGrow = Math.max(1, Math.round((t.weight / maxWeight) * 8));
          return (
            <div
              key={t.symbol}
              className={`${tileColor(t.changePct)} rounded px-1.5 py-1 text-white cursor-default transition-opacity hover:opacity-90`}
              style={{ flex: `${flexGrow} 1 80px`, minWidth: '72px', maxWidth: '140px' }}
              onMouseEnter={() => setHover(t)}
              onMouseLeave={() => setHover(null)}
              title={`${t.name} · ${t.weight}% weight`}
            >
              <div className="text-[10px] font-bold truncate">{t.symbol}</div>
              <div className="text-[11px] font-mono font-bold">
                {t.changePct >= 0 ? '+' : ''}{t.changePct}%
              </div>
            </div>
          );
        })}
      </div>

      {data.analysis && (
        <p className="mt-2 pt-2 border-t border-nexus-border text-[10px] text-gray-400 leading-relaxed">
          {data.analysis}
        </p>
      )}

      <p className="mt-1 text-[9px] text-nexus-muted">
        Real constituents via Upstox · tile size = index weight · hover for quote detail
      </p>
    </Panel>
  );
}
