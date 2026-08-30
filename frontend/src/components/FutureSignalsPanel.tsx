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
  gateFixHint?: string;
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

interface FtvSideEstimate {
  probabilities: Record<string, number>;
  sampleCounts: Record<string, number>;
  probabilitySources?: Record<string, string>;
  earliestLikelyMinutes: number;
  radarSupport: number;
  optionFeatures?: {
    strike?: number;
    spreadPct?: number | null;
    iv?: number | null;
    ivExpansion?: number | null;
    oi?: number;
    oiChangePct?: number | null;
    velocity3s?: number;
    volumeSurge?: number;
    liquidityScore?: number;
  };
}

interface FtvSymbolEstimate {
  status: string;
  historyReady?: boolean;
  premiumHistoryReady?: boolean;
  error?: string;
  profile?: {
    sessionCount?: number;
    baseSamples?: number;
    fromDate?: string;
    toDate?: string;
    timeOfDayLeaders?: Record<string, Array<{
      time: string;
      probabilityPct: number;
      samples: number;
    }>>;
  };
  live?: {
    status: string;
    liveReady?: boolean;
    dominantSide?: string;
    confidence?: string;
    estimatedWindow?: string | null;
    baseRangePct?: number;
    localBaseReady?: boolean;
    sides?: Record<string, FtvSideEstimate>;
    modelQuality?: {
      premiumSampleCount?: number;
      walkForwardBrierScore?: number | null;
      meanCalibrationErrorPct?: number | null;
      driftStatus?: string;
    };
    reason?: string;
  };
}

interface FtvFocusAlert {
  id: string;
  symbol: string;
  side: string;
  status: 'ACTIVE' | 'COOLDOWN';
  confidence: string;
  message: string;
  detail?: string;
  localBaseReady?: boolean;
  chartAligned?: boolean;
  radarTradeable?: boolean;
  peakProbabilityPct?: number;
  estimatedWindow?: string | null;
  radarStrike?: number;
  radarTier?: string;
  radarScore?: number;
  cooldownSecRemaining?: number;
}

interface FtvProbabilityPayload {
  enabled: boolean;
  status: string;
  generatedAt?: string;
  symbols: Record<string, FtvSymbolEstimate>;
  focusAlerts?: {
    enabled?: boolean;
    status?: string;
    active?: FtvFocusAlert[];
    guardrail?: string;
  };
  calibration?: {
    status?: string;
    observationCount?: number;
    sourceDates?: string[];
    walkForward?: {
      status?: string;
      brierScore?: number | null;
      meanCalibrationErrorPct?: number | null;
      validationSamples?: number;
    };
    drift?: {
      status?: string;
      maxDeltaPctPoints?: number;
    };
  };
  scheduledEvents?: {
    riskLevel?: string;
    activeOrUpcoming?: Array<{
      id: string;
      title: string;
      status: string;
      impact: string;
      startsAt: string;
      minutesTo?: number;
    }>;
  };
  guardrail?: string;
  limitations?: string;
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

function missedTradeKey(symbol: string, side?: string, strike?: number) {
  return `${symbol.toUpperCase()}:${String(side ?? '').toUpperCase()}:${Number(strike ?? 0)}`;
}

interface MissedTradeBrief {
  symbol: string;
  side: string;
  strike: number;
  primaryBlocker?: string;
  blockers?: string[];
  fix?: string;
  wouldPass?: boolean;
}

interface MissedTradeReportBrief {
  missed?: MissedTradeBrief[];
  wouldPass?: MissedTradeBrief[];
}

function enrichSignalsWithMissedExplainer(
  signals: ForwardSignal[],
  report: MissedTradeReportBrief | null,
): ForwardSignal[] {
  if (!report) return signals;
  const lookup = new Map<string, MissedTradeBrief>();
  for (const row of [...(report.wouldPass ?? []), ...(report.missed ?? [])]) {
    lookup.set(missedTradeKey(row.symbol, row.side, row.strike), row);
  }
  return signals.map((signal) => {
    const match = lookup.get(missedTradeKey(signal.symbol, signal.side, signal.strike));
    if (!match) return signal;
    return {
      ...signal,
      primaryBlocker: signal.primaryBlocker ?? match.primaryBlocker ?? match.blockers?.[0] ?? null,
      blockers: signal.blockers?.length ? signal.blockers : match.blockers,
      gateFixHint: match.fix,
    };
  });
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

function FtvFocusAlertBanner({
  alerts,
}: {
  alerts: FtvFocusAlert[];
}) {
  if (!alerts.length) return null;
  return (
    <div className="mb-2 space-y-1">
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className={`rounded-lg border px-2.5 py-2 ${
            alert.status === 'ACTIVE'
              ? 'border-nexus-green/50 bg-nexus-green/10'
              : 'border-nexus-yellow/40 bg-nexus-yellow/5'
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-[10px] font-bold uppercase tracking-wide text-white">
              {alert.status === 'ACTIVE' ? 'FTV focus clock' : 'FTV focus cooling'}
            </div>
            <span className={`text-[9px] font-bold uppercase ${
              alert.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'
            }`}>
              {alert.symbol} {alert.side}
            </span>
          </div>
          <div className="mt-1 text-[10px] text-white">{alert.message}</div>
          <div className="mt-1 flex flex-wrap gap-1 text-[8px] text-nexus-muted">
            <span className="rounded border border-nexus-border/60 px-1 py-0.5">
              {alert.confidence} confidence
            </span>
            {alert.peakProbabilityPct != null ? (
              <span className="rounded border border-nexus-border/60 px-1 py-0.5">
                peak {alert.peakProbabilityPct.toFixed(1)}%
              </span>
            ) : null}
            {alert.estimatedWindow ? (
              <span className="rounded border border-nexus-border/60 px-1 py-0.5">
                window {alert.estimatedWindow}
              </span>
            ) : null}
            {alert.radarStrike != null ? (
              <span className="rounded border border-nexus-border/60 px-1 py-0.5">
                radar {alert.radarStrike} · {alert.radarTier ?? 'TRADEABLE'}
              </span>
            ) : null}
            {alert.cooldownSecRemaining ? (
              <span className="rounded border border-nexus-yellow/40 px-1 py-0.5 text-nexus-yellow">
                {alert.cooldownSecRemaining}s cooldown
              </span>
            ) : null}
          </div>
          {alert.detail ? (
            <div className="mt-1 text-[8px] text-nexus-muted">{alert.detail}</div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function FtvProbabilityBoard({
  data,
  error,
}: {
  data: FtvProbabilityPayload | null;
  error: string | null;
}) {
  if (!data && !error) {
    return <div className="mb-3 text-[10px] text-nexus-muted">Loading Upstox historical FTV profile…</div>;
  }
  return (
    <div className="mb-3 rounded-lg border border-purple-500/30 bg-purple-950/10 p-2.5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-purple-300">
            Historical FTV timing · Upstox V3
          </div>
          <div className="text-[9px] text-nexus-muted">
            Empirical CE/PE breakout probability after a compressed 5-minute base
          </div>
        </div>
        <span className="rounded border border-purple-500/30 px-1.5 py-0.5 text-[9px] text-purple-200">
          {data?.status?.replace('_', ' ') ?? 'UNAVAILABLE'}
        </span>
      </div>

      {error ? <div className="mb-2 text-[9px] text-nexus-yellow">{error}</div> : null}
      <FtvFocusAlertBanner alerts={data?.focusAlerts?.active ?? []} />
      {data?.calibration ? (
        <div className="mb-2 flex flex-wrap gap-1 text-[8px]">
          <span className="rounded border border-nexus-border/70 bg-black/25 px-1.5 py-0.5 text-nexus-muted">
            Premium tape {data.calibration.observationCount ?? 0} bases
          </span>
          <span className="rounded border border-nexus-border/70 bg-black/25 px-1.5 py-0.5 text-nexus-muted">
            Walk-forward {data.calibration.walkForward?.status ?? 'LEARNING'}
            {data.calibration.walkForward?.brierScore != null
              ? ` · Brier ${data.calibration.walkForward.brierScore.toFixed(3)}`
              : ''}
          </span>
          <span className={`rounded border px-1.5 py-0.5 ${
            data.calibration.drift?.status === 'DRIFT'
              ? 'border-nexus-red/50 text-nexus-red'
              : data.calibration.drift?.status === 'WATCH'
                ? 'border-nexus-yellow/50 text-nexus-yellow'
                : 'border-nexus-green/40 text-nexus-green'
          }`}>
            Drift {data.calibration.drift?.status ?? 'LEARNING'}
          </span>
          {data.scheduledEvents?.riskLevel && data.scheduledEvents.riskLevel !== 'NORMAL' ? (
            <span className="rounded border border-orange-500/50 px-1.5 py-0.5 text-orange-300">
              Event risk {data.scheduledEvents.riskLevel}
            </span>
          ) : null}
        </div>
      ) : null}
      {(data?.scheduledEvents?.activeOrUpcoming ?? []).map((event) => (
        <div key={event.id} className="mb-2 rounded border border-orange-500/30 bg-orange-950/10 px-2 py-1 text-[8px] text-orange-200">
          {event.status} · {event.impact} · {event.title}
          {event.status === 'UPCOMING' ? ` · ${event.minutesTo ?? 0}m` : ''}
        </div>
      ))}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
        {Object.entries(data?.symbols ?? {}).map(([symbol, row]) => {
          const live = row.live;
          const leaders = row.profile?.timeOfDayLeaders ?? {};
          return (
            <div key={symbol} className="rounded border border-nexus-border/60 bg-black/20 p-2">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] font-bold text-white">{symbol}</span>
                <span className={`text-[9px] font-bold ${
                  live?.dominantSide === 'CALL'
                    ? 'text-nexus-green'
                    : live?.dominantSide === 'PUT'
                      ? 'text-nexus-red'
                      : 'text-nexus-muted'
                }`}>
                  {live?.liveReady
                    ? `${live.dominantSide ?? 'NEUTRAL'} · ${live.confidence ?? 'LOW'}${live.estimatedWindow ? ` · ${live.estimatedWindow}` : ''}`
                    : row.historyReady ? 'HISTORY READY · WAITING LIVE' : row.status}
                </span>
              </div>

              {live?.liveReady && live.sides ? (
                <div className="space-y-1.5">
                  {(['CALL', 'PUT'] as const).map((side) => (
                    <div key={side} className="grid grid-cols-[3rem_repeat(4,minmax(0,1fr))] items-center gap-1 text-[9px]">
                      <span className={side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>{side}</span>
                      {['1', '3', '5', '15'].map((horizon) => (
                        <div key={horizon} className="rounded bg-black/30 px-1 py-1 text-center">
                          <div className="text-[8px] text-nexus-muted">{horizon}m</div>
                          <div className="font-mono text-white">
                            {(live.sides?.[side]?.probabilities?.[horizon] ?? 0).toFixed(1)}%
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                  <div className="text-[8px] text-nexus-muted">
                    Base range {(live.baseRangePct ?? 0).toFixed(3)}% · local base {live.localBaseReady ? 'READY' : 'forming'}
                  </div>
                  <div className="grid grid-cols-2 gap-1 text-[8px] text-nexus-muted">
                    {(['CALL', 'PUT'] as const).map((side) => {
                      const option = live.sides?.[side]?.optionFeatures;
                      return (
                        <div key={`${side}-quality`} className="rounded bg-black/20 px-1.5 py-1">
                          {side} premium · spread {option?.spreadPct != null ? `${option.spreadPct.toFixed(2)}%` : 'n/a'}
                          {' · '}IV {option?.iv != null ? option.iv.toFixed(1) : 'n/a'}
                          {option?.ivExpansion != null ? ` (${option.ivExpansion.toFixed(2)}×)` : ''}
                          {option?.oiChangePct != null ? ` · OI ${option.oiChangePct >= 0 ? '+' : ''}${option.oiChangePct.toFixed(1)}%` : ''}
                          {' · '}v3 {(option?.velocity3s ?? 0).toFixed(2)}%
                        </div>
                      );
                    })}
                  </div>
                  <div className="text-[8px] text-nexus-muted">
                    Model {live.modelQuality?.driftStatus ?? 'LEARNING'} · premium samples {live.modelQuality?.premiumSampleCount ?? 0}
                    {live.modelQuality?.walkForwardBrierScore != null
                      ? ` · Brier ${live.modelQuality.walkForwardBrierScore.toFixed(3)}`
                      : ''}
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2 text-[9px]">
                  {(['CALL', 'PUT'] as const).map((side) => {
                    const top = leaders[side]?.[0];
                    return (
                      <div key={side} className="rounded bg-black/25 p-1.5">
                        <span className={side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>{side}</span>
                        <span className="text-nexus-muted"> recurring window </span>
                        <span className="font-mono text-white">{top?.time ?? '—'}</span>
                        {top ? <span className="text-nexus-muted"> · {top.probabilityPct.toFixed(1)}%</span> : null}
                      </div>
                    );
                  })}
                  <div className="col-span-2 text-[8px] text-nexus-muted">
                    {live?.reason ?? `${row.profile?.baseSamples ?? 0} compressed-base samples across ${row.profile?.sessionCount ?? 0} sessions`}
                  </div>
                </div>
              )}
              {row.error ? <div className="mt-1 text-[8px] text-nexus-red">{row.error}</div> : null}
            </div>
          );
        })}
      </div>
      <div className="mt-2 text-[8px] leading-relaxed text-nexus-muted">
        {data?.guardrail ?? 'Advisory only — live premium and orderflow confirmation remain mandatory.'}
      </div>
    </div>
  );
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
  const [ftvData, setFtvData] = useState<FtvProbabilityPayload | null>(null);
  const [ftvError, setFtvError] = useState<string | null>(null);
  const [missedReport, setMissedReport] = useState<MissedTradeReportBrief | null>(null);

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

  const loadFtv = useCallback(async () => {
    try {
      const res = await fetch('/api/signals/ftv-probability');
      if (!res.ok) throw new Error(`Historical probability API ${res.status}`);
      setFtvData((await res.json()) as FtvProbabilityPayload);
      setFtvError(null);
    } catch (e) {
      setFtvError(e instanceof Error ? e.message : 'Historical probability unavailable');
    }
  }, []);

  const loadMissed = useCallback(async () => {
    try {
      const res = await fetch('/api/ai/missed-trades');
      if (!res.ok) return;
      setMissedReport((await res.json()) as MissedTradeReportBrief);
    } catch {
      /* optional enrichment */
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);

  useEffect(() => {
    void loadFtv();
    const id = setInterval(() => void loadFtv(), 60_000);
    return () => clearInterval(id);
  }, [loadFtv]);

  useEffect(() => {
    void loadMissed();
    const id = setInterval(() => void loadMissed(), 15_000);
    return () => clearInterval(id);
  }, [loadMissed]);

  const moments = (data?.moments?.length ? data.moments : localMoments()) as ForwardMoment[];
  const mergedExplosions = enrichSignalsWithMissedExplainer(
    mergeLiveExplosions(data, snapshots),
    missedReport,
  );
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

      <FtvProbabilityBoard data={ftvData} error={ftvError} />

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
                    Blocked: {s.primaryBlocker ?? s.blockers?.slice(0, 2).join(' · ')}
                  </div>
                ) : null}
                {s.gateFixHint && !s.tradeable ? (
                  <div className="text-[8px] text-nexus-yellow mt-0.5">{s.gateFixHint}</div>
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
        onClick={() => {
          void load();
          void loadFtv();
          void loadMissed();
        }}
        className="w-full mt-2 text-[10px] py-1.5 rounded border border-nexus-border text-nexus-muted hover:text-white"
      >
        Refresh forward scan
      </button>
    </Panel>
  );
}
