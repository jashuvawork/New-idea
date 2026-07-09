import { useCallback, useEffect, useState } from 'react';
import { Panel } from './Panel';
import type { AutoTraderState, SymbolSnapshot } from '../types';
import {
  allDayExplosionWindowActive,
  formatIstTime,
  morningCaptureWindowActive,
  momentumRallyWindowActive,
} from '../lib/playbookSession';

type Horizon = 'MOMENT' | 'OPEN' | 'SESSION' | 'EXPLOSION' | 'SWING' | 'SCALP' | 'STRATEGY' | 'RISK' | 'ADVISORY';

interface ForwardMoment {
  id: string;
  label: string;
  status: 'LIVE' | 'UPCOMING' | 'ENDED';
  hint?: string;
  window?: string;
  startsInMin?: number | null;
  endsInMin?: number | null;
  active?: boolean;
}

interface ForwardSignal {
  id: string;
  horizon: Horizon;
  symbol: string;
  side?: string;
  strike?: number;
  premium?: number;
  confidence: number;
  tradeable: boolean;
  radarTradeable?: boolean;
  summary: string;
  detail?: string;
  tier?: string;
  dailyMovePct?: number;
  peakMovePct?: number;
  blockers?: string[];
  primaryBlocker?: string | null;
  tradeBias?: string;
  targets?: Record<string, number | undefined>;
}

interface ForwardPayload {
  at?: string;
  summary?: string;
  sessionBias?: string;
  moments?: ForwardMoment[];
  signals?: ForwardSignal[];
  tradeableCount?: number;
  counts?: Record<string, number>;
  entriesAllowed?: boolean;
  composer?: ForwardSignal;
}

const HORIZON_TONE: Record<string, string> = {
  MOMENT: 'border-purple-500/40 text-purple-300',
  OPEN: 'border-blue-500/40 text-blue-300',
  EXPLOSION: 'border-nexus-red/40 text-nexus-red',
  SWING: 'border-cyan-500/40 text-cyan-300',
  SCALP: 'border-nexus-green/40 text-nexus-green',
  STRATEGY: 'border-yellow-500/40 text-nexus-yellow',
  RISK: 'border-orange-500/40 text-orange-300',
  ADVISORY: 'border-purple-400/40 text-purple-200',
};

const TABS: { key: Horizon | 'ALL'; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'MOMENT', label: 'Moments' },
  { key: 'EXPLOSION', label: 'Explosions' },
  { key: 'SWING', label: 'Swing' },
  { key: 'SCALP', label: 'Scalp' },
  { key: 'RISK', label: 'Risk' },
  { key: 'ADVISORY', label: 'AI' },
];

function explosionVisible(alert: { tier?: string; allDayExplosion?: boolean; volumeAwaken?: boolean; peakMovePct?: number; dailyMovePct?: number; openPremiumMove?: number; velocity3s?: number; velocity9s?: number }) {
  const tier = String(alert.tier ?? 'WATCH');
  if (tier !== 'WATCH') return true;
  if (alert.allDayExplosion) return true;
  if (alert.volumeAwaken) return true;
  const peak = Number(alert.peakMovePct ?? 0);
  const daily = Number(alert.dailyMovePct ?? alert.openPremiumMove ?? 0);
  const v3 = Number(alert.velocity3s ?? 0);
  const v9 = Number(alert.velocity9s ?? 0);
  return peak >= 15 || daily >= 12 || v3 >= 2.5 || v9 >= 3.5;
}

function buildLocalForwardPayload(
  snapshots: Record<string, SymbolSnapshot>,
  auto: AutoTraderState,
): ForwardPayload {
  const signals: ForwardSignal[] = [];
  for (const [sym, snap] of Object.entries(snapshots)) {
    if (!snap.dataAvailable) continue;
    for (const alert of snap.explosionAlerts ?? []) {
      const tier = String(alert.tier ?? 'WATCH');
      if (!explosionVisible(alert)) continue;
      const score = Number(alert.explosionScore ?? 0);
      const daily = Number(alert.dailyMovePct ?? alert.openPremiumMove ?? 0);
      const peak = Number(alert.peakMovePct ?? daily);
      signals.push({
        id: `explosion:${sym}:${alert.side}:${alert.strike}`,
        horizon: 'EXPLOSION',
        symbol: sym,
        side: alert.side,
        strike: alert.strike,
        premium: alert.premium,
        confidence: score,
        tradeable: Boolean(alert.tradeable),
        radarTradeable: Boolean(alert.tradeable),
        summary: `${sym} ${alert.side} ${alert.strike} · ${tier} · score ${score.toFixed(0)}`,
        detail: alert.reason,
        tier,
        dailyMovePct: daily,
        peakMovePct: peak,
        blockers: alert.tradeable ? undefined : ['tier_or_velocity'],
      });
    }
    for (const alert of snap.swingAlerts ?? []) {
      signals.push({
        id: `swing:${sym}:${alert.side}:${alert.strike}`,
        horizon: 'SWING',
        symbol: sym,
        side: alert.side,
        strike: alert.strike,
        premium: alert.premium,
        confidence: Number(alert.confidence ?? 0),
        tradeable: Boolean(alert.tradeable),
        summary: `${sym} ${alert.side} ${alert.strike} · ${alert.swingType ?? 'swing'}`,
        detail: alert.reason,
        blockers: alert.tradeable ? undefined : ['swing_gate'],
      });
    }
    for (const t of snap.suggestedTrades ?? []) {
      const conf = Number(t.confidence ?? 0);
      signals.push({
        id: `scalp:${sym}:${t.side}:${t.strike}:${t.id}`,
        horizon: 'SCALP',
        symbol: sym,
        side: t.side,
        strike: t.strike,
        premium: t.lastPremium,
        confidence: conf,
        tradeable: conf >= 50,
        summary: `${sym} ${t.side} ${t.strike} · TQS ${t.tqs?.toFixed(0) ?? '—'}`,
        blockers: conf >= 50 ? undefined : ['low_confidence'],
      });
    }
  }
  signals.sort((a, b) => (b.tradeable ? 1 : 0) - (a.tradeable ? 1 : 0) || b.confidence - a.confidence);
  const moments = localMoments();
  const live = moments.filter((m) => m.status === 'LIVE');
  const tradeable = signals.filter((s) => s.tradeable);
  const counts: Record<string, number> = {};
  for (const s of signals) {
    counts[s.horizon] = (counts[s.horizon] ?? 0) + 1;
  }
  return {
    at: new Date().toISOString(),
    summary: live.length
      ? `Local scan · Live: ${live[0].label} · ${tradeable.length} tradeable`
      : 'Local scan — deploy /api/signals/forward for full forward engine',
    moments,
    signals: signals.slice(0, 40),
    tradeableCount: tradeable.length,
    counts,
    entriesAllowed: auto.dailyProfitGate?.newEntriesAllowed !== false,
  };
}

function localMoments(): ForwardMoment[] {
  const now = new Date();
  const items: ForwardMoment[] = [
    {
      id: 'morning_capture',
      label: 'Morning capture',
      status: morningCaptureWindowActive(now) ? 'LIVE' : 'ENDED',
      hint: 'Open premium expansion',
      window: '09:15–11:45',
      active: morningCaptureWindowActive(now),
    },
    {
      id: 'all_day',
      label: 'All-day explosion',
      status: allDayExplosionWindowActive(now) ? 'LIVE' : 'ENDED',
      hint: '14:00 flat-then-vertical rips',
      window: '09:20–15:25',
      active: allDayExplosionWindowActive(now),
    },
    {
      id: 'momentum',
      label: 'Momentum rally',
      status: momentumRallyWindowActive(now) ? 'LIVE' : 'ENDED',
      hint: 'Afternoon breakouts',
      window: '10:00–15:25',
      active: momentumRallyWindowActive(now),
    },
  ];
  return items.filter((m) => m.status === 'LIVE').length
    ? items
    : items.map((m) => ({ ...m, status: m.active ? 'LIVE' : 'ENDED' as const }));
}

function mergeLiveExplosions(api: ForwardPayload | null, snapshots: Record<string, SymbolSnapshot>): ForwardSignal[] {
  const local = buildLocalForwardPayload(snapshots, { dailyProfitGate: { newEntriesAllowed: true } } as AutoTraderState);
  const localExplosions = (local.signals ?? []).filter((s) => s.horizon === 'EXPLOSION');
  const apiSignals = api?.signals ?? [];
  const merged = new Map<string, ForwardSignal>();
  for (const s of apiSignals) {
    merged.set(s.id, s);
  }
  for (const s of localExplosions) {
    const existing = merged.get(s.id);
    if (!existing || (s.confidence > existing.confidence)) {
      merged.set(s.id, { ...existing, ...s, tradeable: existing?.tradeable ?? s.tradeable });
    }
  }
  const out = Array.from(merged.values());
  out.sort(
    (a, b) =>
      (b.tradeable ? 1 : 0) - (a.tradeable ? 1 : 0) ||
      (b.radarTradeable ? 1 : 0) - (a.radarTradeable ? 1 : 0) ||
      b.confidence - a.confidence,
  );
  return out;
}

export function FutureSignalsPanel({
  snapshots,
  auto,
  pollMs = 3_000,
}: {
  snapshots: Record<string, SymbolSnapshot>;
  auto: AutoTraderState;
  pollMs?: number;
}) {
  const [data, setData] = useState<ForwardPayload | null>(null);
  const [tab, setTab] = useState<Horizon | 'ALL'>('ALL');
  const [error, setError] = useState<string | null>(null);
  const [apiMissing, setApiMissing] = useState(false);
  const [apiDegraded, setApiDegraded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/signals/forward');
      if (res.status === 404) {
        setApiMissing(true);
        setApiDegraded(false);
        setData(buildLocalForwardPayload(snapshots, auto));
        setError(null);
        return;
      }
      if (!res.ok) {
        setApiMissing(false);
        setApiDegraded(true);
        setData(buildLocalForwardPayload(snapshots, auto));
        setError(`Forward API error ${res.status} — showing live snapshot scan`);
        return;
      }
      const payload = (await res.json()) as ForwardPayload;
      setApiMissing(false);
      setApiDegraded(false);
      setData(payload);
      setError(null);
    } catch (e) {
      setApiMissing(false);
      setApiDegraded(true);
      setData(buildLocalForwardPayload(snapshots, auto));
      setError(e instanceof Error ? e.message : 'fetch failed');
    }
  }, [snapshots, auto]);

  useEffect(() => {
    load();
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);

  const moments = (data?.moments?.length ? data.moments : localMoments()) as ForwardMoment[];
  const mergedExplosions = mergeLiveExplosions(data, snapshots);
  const signals =
    tab === 'EXPLOSION'
      ? mergedExplosions
      : tab === 'ALL'
        ? [
            ...mergedExplosions,
            ...(data?.signals ?? []).filter((s) => s.horizon !== 'EXPLOSION'),
          ]
        : (data?.signals ?? []).filter((s) => s.horizon === tab);
  const filtered = tab === 'MOMENT' ? [] : signals;
  const liveMoments = moments.filter((m) => m.status === 'LIVE');
  const upcomingMoments = moments.filter((m) => m.status === 'UPCOMING');
  const entriesOk = data?.entriesAllowed !== false && auto.dailyProfitGate?.newEntriesAllowed !== false;
  const radarCount = mergedExplosions.filter((s) => s.radarTradeable ?? s.tier !== 'WATCH').length;
  const goCount = mergedExplosions.filter((s) => s.tradeable).length;

  return (
    <Panel
      title="Future Signals"
      badge={
        apiMissing || apiDegraded
          ? 'LOCAL'
          : entriesOk
            ? goCount > 0
              ? `${goCount} GO · ${radarCount} RADAR`
              : radarCount > 0
                ? `${radarCount} RADAR`
                : `${data?.tradeableCount ?? 0} READY`
            : 'GATED'
      }
      badgeColor={
        apiMissing || apiDegraded
          ? 'bg-nexus-yellow/90 text-black'
          : entriesOk
            ? 'bg-nexus-accent/90 text-black'
            : 'bg-nexus-red/90'
      }
    >
      <p className="text-[10px] text-nexus-muted mb-2 leading-relaxed">
        Predicted session moments + forward trade setups — explosions, swings, scalps, risk.
      </p>

      <div className="text-[10px] text-white mb-2 p-2 rounded bg-black/30 min-h-[2rem]">
        {data?.summary ?? 'Loading forward scan…'}
        {data?.sessionBias && data.sessionBias !== 'NEUTRAL' ? (
          <span className="text-nexus-muted"> · Session bias {data.sessionBias}</span>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-1 mb-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`text-[9px] px-1.5 py-0.5 rounded border ${
              tab === t.key ? 'border-nexus-accent text-nexus-accent bg-nexus-accent/10' : 'border-gray-700 text-gray-500'
            }`}
          >
            {t.label}
            {t.key !== 'ALL' && t.key !== 'MOMENT' && data?.counts?.[t.key] != null
              ? ` (${data.counts[t.key]})`
              : ''}
          </button>
        ))}
      </div>

      {(tab === 'ALL' || tab === 'MOMENT') && (
        <div className="mb-3">
          <div className="text-[9px] text-nexus-muted uppercase mb-1">Session moments · {formatIstTime()}</div>
          <div className="space-y-1">
            {liveMoments.map((m) => (
              <div key={m.id} className="p-1.5 rounded border border-nexus-green/40 bg-nexus-green/5 text-[10px]">
                <span className="text-nexus-green font-bold uppercase mr-2">LIVE</span>
                <span className="text-white font-semibold">{m.label}</span>
                <span className="text-nexus-muted ml-1">{m.window}</span>
                {m.endsInMin != null ? (
                  <span className="text-nexus-muted ml-1">· {m.endsInMin}m left</span>
                ) : null}
                {m.hint ? <div className="text-[9px] text-gray-400 mt-0.5">{m.hint}</div> : null}
              </div>
            ))}
            {upcomingMoments.slice(0, 3).map((m) => (
              <div key={m.id} className="p-1.5 rounded border border-purple-500/30 bg-purple-900/10 text-[10px]">
                <span className="text-purple-300 font-bold uppercase mr-2">SOON</span>
                <span className="text-white">{m.label}</span>
                <span className="text-nexus-muted ml-1">in {m.startsInMin}m · {m.window}</span>
                {m.hint ? <div className="text-[9px] text-gray-400 mt-0.5">{m.hint}</div> : null}
              </div>
            ))}
            {!liveMoments.length && !upcomingMoments.length ? (
              <div className="text-[10px] text-gray-600">Power hour 14:00–15:25 — watch deep OTM gamma rips</div>
            ) : null}
          </div>
        </div>
      )}

      {(tab === 'ALL' || tab !== 'MOMENT') && (
        <div className="max-h-48 overflow-y-auto space-y-1">
          {filtered.length === 0 ? (
            <p className="text-[10px] text-nexus-muted py-2">No {tab === 'ALL' ? '' : tab.toLowerCase()} signals yet</p>
          ) : (
            filtered.slice(0, 12).map((s) => (
              <div
                key={s.id}
                className={`p-1.5 rounded border text-[10px] ${HORIZON_TONE[s.horizon] ?? 'border-gray-700'}`}
              >
                <div className="flex justify-between gap-2">
                  <span className="text-white font-mono truncate">{s.summary}</span>
                  <span className={`shrink-0 text-[8px] font-bold uppercase ${s.tradeable ? 'text-nexus-green' : s.radarTradeable || (s.tier && s.tier !== 'WATCH') ? 'text-nexus-accent' : 'text-gray-500'}`}>
                    {s.tradeable ? 'GO' : s.radarTradeable || (s.tier && s.tier !== 'WATCH') ? 'RADAR' : 'WATCH'}
                  </span>
                </div>
                {s.detail ? <div className="text-[9px] text-gray-400 truncate mt-0.5">{s.detail}</div> : null}
                {(s.peakMovePct != null && s.peakMovePct > 0) || (s.dailyMovePct != null && s.dailyMovePct > 0) ? (
                  <div className="text-[9px] text-nexus-accent mt-0.5">
                    {s.peakMovePct != null && s.peakMovePct > (s.dailyMovePct ?? 0)
                      ? `Peak +${s.peakMovePct.toFixed(0)}%`
                      : null}
                    {s.peakMovePct != null && s.peakMovePct > (s.dailyMovePct ?? 0) && s.dailyMovePct != null && s.dailyMovePct > 0
                      ? ' · '
                      : null}
                    {s.dailyMovePct != null && s.dailyMovePct > 0 ? `Now +${s.dailyMovePct.toFixed(0)}%` : null}
                  </div>
                ) : null}
                {s.blockers?.length || s.primaryBlocker ? (
                  <div className="text-[8px] text-nexus-red font-mono mt-0.5">
                    {s.primaryBlocker ?? s.blockers?.slice(0, 2).join(' · ')}
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      )}

      {data?.composer ? (
        <div className="mt-2 p-2 rounded bg-purple-900/20 border border-purple-500/30 text-[10px]">
          <div className="text-purple-300 font-semibold mb-0.5">Composer bias: {data.composer.tradeBias ?? '—'}</div>
          <div className="text-white">{data.composer.summary}</div>
        </div>
      ) : null}

      {apiMissing ? (
        <div className="text-[10px] text-nexus-yellow mt-2">
          Forward API not deployed — showing live snapshot scan. Redeploy EC2 backend after merge.
        </div>
      ) : null}
      {apiDegraded && !apiMissing ? (
        <div className="text-[10px] text-nexus-yellow mt-2">
          Forward API unavailable — showing live snapshot scan until backend recovers.
        </div>
      ) : null}
      {error ? <div className="text-[10px] text-nexus-red mt-2">{error}</div> : null}

      <button
        type="button"
        onClick={load}
        className="w-full mt-2 text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white"
      >
        Refresh forward scan
      </button>
    </Panel>
  );
}
