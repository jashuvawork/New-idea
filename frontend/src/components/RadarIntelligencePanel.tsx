import { useCallback, useEffect, useMemo, useState } from 'react';

type Tab = 'scorecard' | 'moves' | 'funnel' | 'system';

interface RadarArchive {
  date: string;
  fileName: string;
  sizeBytes: number;
  count?: number;
  updatedAt?: string;
  downloadUrl: string;
  corrupt?: boolean;
}

interface HealthAlert {
  severity: 'critical' | 'warning' | 'info';
  code: string;
  message: string;
}

interface RadarHealth {
  healthy?: boolean;
  marketPhase?: string;
  alerts?: HealthAlert[];
  staleSources?: string[];
  sourceDivergence?: {
    active?: boolean;
    keys?: string[];
  };
  sources?: Record<string, {
    lastSeenAt?: string;
    ageSeconds?: number;
    stale?: boolean;
    archiveEntryCount?: number;
    dataAvailableCount?: number;
  }>;
  components?: Record<string, {
    healthy?: boolean;
    lastSuccessAt?: string;
    lastError?: string;
    date?: string;
    contractCount?: number;
  }>;
  backup?: {
    healthy?: boolean;
    destination?: string;
    fileName?: string;
    lastAttemptAt?: string;
    lastError?: string;
  };
  feed?: {
    connected?: boolean;
    streamStale?: boolean;
    hasRecentTicks?: boolean;
    lastMessageAgeMs?: number;
    subscribedInstruments?: number;
    lastError?: string;
  };
  cadence?: {
    entryScanIntervalMs?: number;
    lastFastCycleMs?: number;
    lastFullCycleMs?: number;
    fullRestRebuildRunning?: boolean;
  };
}

interface HindsightEvent {
  key: string;
  capture: 'EARLY' | 'LATE' | 'MISSED';
  basePremium?: number;
  verticalPremium?: number;
  peakMovePct?: number;
  baseStartAt?: string;
  verticalAt?: string;
  detectionAt?: string;
  leadSeconds?: number | null;
}

interface RadarScorecard {
  date?: string;
  truthCount?: number;
  earlyDetected?: number;
  lateDetected?: number;
  missed?: number;
  recallPct?: number;
  earlyRecallPct?: number;
  precisionPct?: number;
  falseAlertCount?: number;
  archivedRadarCount?: number;
  outcomes?: Record<string, number>;
  bySymbol?: Record<string, { truth?: number; early?: number; late?: number; missed?: number }>;
  bySide?: Record<string, { truth?: number; early?: number; late?: number; missed?: number }>;
  events?: HindsightEvent[];
}

interface FunnelRow {
  key: string;
  bestTier?: string;
  blocked?: boolean;
  selected?: boolean;
  orderRejected?: boolean;
  blockers?: string[];
  entered?: boolean;
  closed?: boolean;
  pnlInr?: number;
  tradeOutcome?: string | null;
  radarOutcome?: { status?: string; mfePct?: number; maePct?: number };
}

interface FunnelReport {
  date?: string;
  detected?: number;
  blocked?: number;
  selected?: number;
  orderRejected?: number;
  entered?: number;
  closedWins?: number;
  detectionToSelectionPct?: number;
  selectionToEntryPct?: number;
  detectionToEntryPct?: number;
  entryWinRatePct?: number;
  rows?: FunnelRow[];
  sessionBlocks?: { reason?: string; message?: string }[];
}

interface DetectorReplay {
  mode?: string;
  sampleBatches?: number;
  uniqueRadarKeys?: number;
  timeline?: unknown[];
}

const tabLabels: Record<Tab, string> = {
  scorecard: 'Scorecard',
  moves: 'Missed moves',
  funnel: 'Entry funnel',
  system: 'System health',
};

function istDate() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function compactNumber(value: number | undefined, suffix = '') {
  return value == null ? '—' : `${Math.round(value * 10) / 10}${suffix}`;
}

function formatTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function MetricCard({
  label,
  value,
  helper,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  helper?: string;
  tone?: 'good' | 'bad' | 'warn' | 'neutral';
}) {
  const toneClass = tone === 'good'
    ? 'text-nexus-green'
    : tone === 'bad'
      ? 'text-nexus-red'
      : tone === 'warn'
        ? 'text-nexus-yellow'
        : 'text-white';
  return (
    <div className="rounded-xl border border-nexus-border bg-black/20 px-3 py-2.5 min-w-0">
      <div className="text-[9px] uppercase tracking-[0.13em] text-nexus-muted">{label}</div>
      <div className={`mt-1 text-xl font-bold font-mono ${toneClass}`}>{value}</div>
      {helper ? <div className="mt-1 text-[9px] text-gray-500 truncate">{helper}</div> : null}
    </div>
  );
}

function EmptyState({ children }: { children: string }) {
  return (
    <div className="rounded-xl border border-dashed border-nexus-border p-7 text-center text-[11px] text-nexus-muted">
      {children}
    </div>
  );
}

export function RadarIntelligencePanel({ pollMs = 30_000 }: { pollMs?: number }) {
  const [archives, setArchives] = useState<RadarArchive[]>([]);
  const [health, setHealth] = useState<RadarHealth | null>(null);
  const [scorecard, setScorecard] = useState<RadarScorecard | null>(null);
  const [funnel, setFunnel] = useState<FunnelReport | null>(null);
  const [selectedDate, setSelectedDate] = useState(istDate());
  const [tab, setTab] = useState<Tab>('scorecard');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [detectorReplay, setDetectorReplay] = useState<DetectorReplay | null>(null);

  const loadOverview = useCallback(async () => {
    try {
      const [archivePayload, healthPayload] = await Promise.all([
        fetchJson<{ archives?: RadarArchive[] }>('/api/ai/radar-archives?limit=90'),
        fetchJson<RadarHealth>('/api/ai/radar-health'),
      ]);
      const rows = archivePayload.archives ?? [];
      setArchives(rows);
      setHealth(healthPayload);
      setSelectedDate((current) => (
        rows.some((row) => row.date === current) ? current : rows[0]?.date ?? current
      ));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to load radar intelligence');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDay = useCallback(async (date: string) => {
    try {
      const [score, funnelReport] = await Promise.all([
        fetchJson<RadarScorecard>(`/api/ai/radar-scorecard/${date}`),
        fetchJson<FunnelReport>(`/api/ai/radar-funnel/${date}`),
      ]);
      setScorecard(score);
      setFunnel(funnelReport);
      setError(null);
    } catch (e) {
      setScorecard(null);
      setFunnel(null);
      setError(e instanceof Error ? e.message : 'Unable to load daily review');
    }
  }, []);

  useEffect(() => {
    loadOverview();
    const id = window.setInterval(loadOverview, pollMs);
    return () => window.clearInterval(id);
  }, [loadOverview, pollMs]);

  useEffect(() => {
    loadDay(selectedDate);
  }, [loadDay, selectedDate]);

  const runAction = async (
    name: string,
    path: string,
    success: (payload: any) => string,
  ) => {
    setAction(name);
    setActionMessage(null);
    try {
      const payload = await fetchJson<any>(path, { method: 'POST' });
      if (name === 'detector-replay') setDetectorReplay(payload as DetectorReplay);
      setActionMessage(success(payload));
      await Promise.all([loadOverview(), loadDay(selectedDate)]);
    } catch (e) {
      setActionMessage(e instanceof Error ? e.message : 'Action failed');
    } finally {
      setAction(null);
    }
  };

  const selectedArchive = archives.find((row) => row.date === selectedDate);
  const alerts = health?.alerts ?? [];
  const events = scorecard?.events ?? [];
  const missedEvents = events.filter((event) => event.capture === 'MISSED');
  const funnelRows = funnel?.rows ?? [];
  const topBlockers = useMemo(() => {
    const counts = new Map<string, number>();
    funnelRows.forEach((row) => (row.blockers ?? []).forEach((blocker) => {
      counts.set(blocker, (counts.get(blocker) ?? 0) + 1);
    }));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [funnelRows]);

  const healthTone = health?.healthy ? 'good' : alerts.some((row) => row.severity === 'critical') ? 'bad' : 'warn';
  const healthLabel = health?.healthy ? 'Healthy' : loading ? 'Loading' : alerts.length ? `${alerts.length} alerts` : 'Needs review';

  return (
    <section className="panel-card">
      <div className="border-b border-nexus-border bg-gradient-to-r from-cyan-950/35 via-nexus-panel to-emerald-950/15 px-4 py-3.5">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className="mt-0.5 h-9 w-9 shrink-0 rounded-xl border border-nexus-accent/30 bg-nexus-accent/10 flex items-center justify-center text-nexus-accent font-black text-sm">
              RI
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold text-sm text-white">Radar Intelligence</h2>
                <span className={`text-[9px] font-bold uppercase rounded-md border px-2 py-0.5 ${
                  healthTone === 'good'
                    ? 'border-nexus-green/30 bg-nexus-green/10 text-nexus-green'
                    : healthTone === 'bad'
                      ? 'border-nexus-red/30 bg-nexus-red/10 text-nexus-red'
                      : 'border-nexus-yellow/30 bg-nexus-yellow/10 text-nexus-yellow'
                }`}>
                  {healthLabel}
                </span>
                <span className="text-[9px] rounded-md border border-nexus-border bg-black/20 px-2 py-0.5 text-nexus-muted">
                  {health?.marketPhase?.replace(/_/g, ' ') ?? 'SYSTEM'}
                </span>
              </div>
              <p className="mt-1 text-[10px] text-nexus-muted max-w-2xl leading-relaxed">
                Daily FTV recall, forward outcomes, gate conversion, detector replay and durable archive health.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="text-[9px] uppercase tracking-wide text-nexus-muted" htmlFor="radar-review-date">
              Session
            </label>
            <input
              id="radar-review-date"
              type="date"
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
              className="h-8 rounded-lg border border-nexus-border bg-black/30 px-2 text-[11px] font-mono text-white color-scheme-dark"
            />
            {selectedArchive ? (
              <a
                href={selectedArchive.downloadUrl}
                className="h-8 inline-flex items-center rounded-lg border border-nexus-accent/35 bg-nexus-accent/10 px-3 text-[10px] font-semibold text-nexus-accent hover:bg-nexus-accent/20"
              >
                Download ZIP
              </a>
            ) : null}
            <button
              type="button"
              onClick={() => Promise.all([loadOverview(), loadDay(selectedDate)])}
              className="h-8 rounded-lg border border-nexus-border px-3 text-[10px] text-nexus-muted hover:text-white hover:border-nexus-border-light"
            >
              Refresh
            </button>
          </div>
        </div>
      </div>

      {alerts.length > 0 ? (
        <div className="border-b border-nexus-border px-4 py-2 flex gap-2 overflow-x-auto">
          {alerts.map((alert) => (
            <div
              key={`${alert.code}-${alert.message}`}
              className={`shrink-0 max-w-md rounded-lg border px-2.5 py-1.5 text-[9px] ${
                alert.severity === 'critical'
                  ? 'border-nexus-red/35 bg-nexus-red/5 text-nexus-red'
                  : alert.severity === 'warning'
                    ? 'border-nexus-yellow/35 bg-nexus-yellow/5 text-nexus-yellow'
                    : 'border-nexus-accent/30 bg-nexus-accent/5 text-nexus-accent'
              }`}
            >
              <span className="font-bold">{alert.code.replace(/_/g, ' ')}</span>
              <span className="ml-1.5 opacity-80">{alert.message}</span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="px-4 pt-3 border-b border-nexus-border flex gap-1 overflow-x-auto">
        {(Object.keys(tabLabels) as Tab[]).map((key) => (
          <button
            type="button"
            key={key}
            onClick={() => setTab(key)}
            className={`shrink-0 px-3 py-2 text-[10px] font-semibold border-b-2 transition-colors ${
              tab === key
                ? 'border-nexus-accent text-nexus-accent'
                : 'border-transparent text-nexus-muted hover:text-white'
            }`}
          >
            {tabLabels[key]}
          </button>
        ))}
      </div>

      <div className="p-4">
        {error ? (
          <div className="mb-3 rounded-lg border border-nexus-red/30 bg-nexus-red/5 px-3 py-2 text-[10px] text-nexus-red">
            {error}
          </div>
        ) : null}

        {tab === 'scorecard' ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
              <MetricCard
                label="FTV recall"
                value={compactNumber(scorecard?.recallPct, '%')}
                helper={`${scorecard?.truthCount ?? 0} hindsight moves`}
                tone={(scorecard?.recallPct ?? 0) >= 80 ? 'good' : (scorecard?.recallPct ?? 0) >= 50 ? 'warn' : 'bad'}
              />
              <MetricCard
                label="Early recall"
                value={compactNumber(scorecard?.earlyRecallPct, '%')}
                helper={`${scorecard?.earlyDetected ?? 0} before vertical`}
                tone={(scorecard?.earlyRecallPct ?? 0) >= 70 ? 'good' : 'warn'}
              />
              <MetricCard
                label="Precision"
                value={compactNumber(scorecard?.precisionPct, '%')}
                helper={`${scorecard?.falseAlertCount ?? 0} unconfirmed`}
                tone={(scorecard?.precisionPct ?? 0) >= 60 ? 'good' : 'warn'}
              />
              <MetricCard
                label="Missed"
                value={String(scorecard?.missed ?? 0)}
                helper="actual FTV moves"
                tone={(scorecard?.missed ?? 0) > 0 ? 'bad' : 'good'}
              />
              <MetricCard
                label="Detected → entry"
                value={compactNumber(funnel?.detectionToEntryPct, '%')}
                helper={`${funnel?.entered ?? 0}/${funnel?.detected ?? 0} contracts`}
                tone="neutral"
              />
              <MetricCard
                label="Entry win rate"
                value={compactNumber(funnel?.entryWinRatePct, '%')}
                helper={`${funnel?.closedWins ?? 0} closed winners`}
                tone={(funnel?.entryWinRatePct ?? 0) >= 55 ? 'good' : 'neutral'}
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              <div className="lg:col-span-2 rounded-xl border border-nexus-border bg-black/15 p-3">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300">Capture quality</h3>
                  <span className="text-[9px] text-nexus-muted">{selectedDate}</span>
                </div>
                {(scorecard?.truthCount ?? 0) > 0 ? (
                  <>
                    <div className="h-3 flex overflow-hidden rounded-full bg-gray-900">
                      <div
                        className="bg-nexus-green"
                        style={{ width: `${((scorecard?.earlyDetected ?? 0) / (scorecard?.truthCount ?? 1)) * 100}%` }}
                        title="Early"
                      />
                      <div
                        className="bg-nexus-yellow"
                        style={{ width: `${((scorecard?.lateDetected ?? 0) / (scorecard?.truthCount ?? 1)) * 100}%` }}
                        title="Late"
                      />
                      <div
                        className="bg-nexus-red"
                        style={{ width: `${((scorecard?.missed ?? 0) / (scorecard?.truthCount ?? 1)) * 100}%` }}
                        title="Missed"
                      />
                    </div>
                    <div className="mt-2 flex flex-wrap gap-4 text-[9px]">
                      <span className="text-nexus-green">● Early {scorecard?.earlyDetected ?? 0}</span>
                      <span className="text-nexus-yellow">● Late {scorecard?.lateDetected ?? 0}</span>
                      <span className="text-nexus-red">● Missed {scorecard?.missed ?? 0}</span>
                    </div>
                  </>
                ) : (
                  <EmptyState>No hindsight moves are available for this session yet.</EmptyState>
                )}
              </div>

              <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
                <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300 mb-2">Outcome labels</h3>
                <div className="space-y-1.5">
                  {Object.entries(scorecard?.outcomes ?? {}).length ? Object.entries(scorecard?.outcomes ?? {}).map(([key, count]) => (
                    <div key={key} className="flex justify-between text-[10px]">
                      <span className="text-nexus-muted">{key.replace(/_/g, ' ')}</span>
                      <span className="font-mono text-white">{count}</span>
                    </div>
                  )) : <span className="text-[10px] text-nexus-muted">Outcomes fill automatically at 1m, 5m, 15m and 30m.</span>}
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {tab === 'moves' ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-[11px] font-semibold text-white">Hindsight flat-to-vertical moves</h3>
                <p className="text-[9px] text-nexus-muted mt-0.5">Ground truth from the stored CE/PE premium tape.</p>
              </div>
              <span className="text-[9px] text-nexus-red">{missedEvents.length} missed</span>
            </div>
            {events.length ? (
              <div className="overflow-x-auto rounded-xl border border-nexus-border">
                <table className="w-full min-w-[720px] text-left">
                  <thead className="bg-black/30 text-[9px] uppercase tracking-wide text-nexus-muted">
                    <tr>
                      <th className="px-3 py-2">Contract</th>
                      <th className="px-3 py-2">Capture</th>
                      <th className="px-3 py-2">Base</th>
                      <th className="px-3 py-2">Peak move</th>
                      <th className="px-3 py-2">Lead</th>
                      <th className="px-3 py-2">Vertical time</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-nexus-border">
                    {events.slice(0, 30).map((event, index) => (
                      <tr key={`${event.key}-${event.verticalAt}-${index}`} className="text-[10px] hover:bg-white/[0.02]">
                        <td className="px-3 py-2 font-mono text-white">{event.key.replaceAll(':', ' · ')}</td>
                        <td className="px-3 py-2">
                          <span className={`rounded-md border px-2 py-0.5 font-bold ${
                            event.capture === 'EARLY'
                              ? 'border-nexus-green/30 bg-nexus-green/10 text-nexus-green'
                              : event.capture === 'LATE'
                                ? 'border-nexus-yellow/30 bg-nexus-yellow/10 text-nexus-yellow'
                                : 'border-nexus-red/30 bg-nexus-red/10 text-nexus-red'
                          }`}>{event.capture}</span>
                        </td>
                        <td className="px-3 py-2 font-mono text-gray-300">₹{compactNumber(event.basePremium)}</td>
                        <td className="px-3 py-2 font-mono text-nexus-accent">+{compactNumber(event.peakMovePct, '%')}</td>
                        <td className="px-3 py-2 font-mono text-gray-300">
                          {event.leadSeconds == null ? '—' : `${Math.round(event.leadSeconds)}s`}
                        </td>
                        <td className="px-3 py-2 font-mono text-nexus-muted">{formatTime(event.verticalAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState>No premium-tape FTV events exist for this date. They appear after live samples are stored.</EmptyState>
            )}
          </div>
        ) : null}

        {tab === 'funnel' ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2">
              <MetricCard label="Detected" value={String(funnel?.detected ?? 0)} />
              <MetricCard label="Blocked" value={String(funnel?.blocked ?? 0)} tone={(funnel?.blocked ?? 0) ? 'warn' : 'neutral'} />
              <MetricCard label="Selected" value={String(funnel?.selected ?? 0)} />
              <MetricCard label="Rejected" value={String(funnel?.orderRejected ?? 0)} tone={(funnel?.orderRejected ?? 0) ? 'bad' : 'neutral'} />
              <MetricCard label="Entered" value={String(funnel?.entered ?? 0)} tone="good" />
              <MetricCard label="Select → entry" value={compactNumber(funnel?.selectionToEntryPct, '%')} />
              <MetricCard label="Wins" value={String(funnel?.closedWins ?? 0)} tone="good" />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-4 gap-3">
              <div className="xl:col-span-3 overflow-x-auto rounded-xl border border-nexus-border">
                {funnelRows.length ? (
                  <table className="w-full min-w-[760px] text-left">
                    <thead className="bg-black/30 text-[9px] uppercase tracking-wide text-nexus-muted">
                      <tr>
                        <th className="px-3 py-2">Contract</th>
                        <th className="px-3 py-2">Tier</th>
                        <th className="px-3 py-2">Progress</th>
                        <th className="px-3 py-2">Blocker</th>
                        <th className="px-3 py-2">Radar outcome</th>
                        <th className="px-3 py-2 text-right">Trade PnL</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-nexus-border">
                      {funnelRows.slice(0, 30).map((row) => (
                        <tr key={row.key} className="text-[10px] hover:bg-white/[0.02]">
                          <td className="px-3 py-2 font-mono text-white">{row.key.replaceAll(':', ' · ')}</td>
                          <td className="px-3 py-2 text-nexus-accent">{row.bestTier ?? '—'}</td>
                          <td className="px-3 py-2 text-gray-300">
                            {row.entered ? 'Entered' : row.orderRejected ? 'Rejected' : row.selected ? 'Selected' : row.blocked ? 'Blocked' : 'Detected'}
                          </td>
                          <td className="px-3 py-2 text-nexus-yellow max-w-[220px] truncate">{row.blockers?.[0] ?? '—'}</td>
                          <td className="px-3 py-2 font-mono text-gray-300">
                            {row.radarOutcome?.status ?? 'TRACKING'}
                            {row.radarOutcome?.mfePct != null ? ` · MFE ${row.radarOutcome.mfePct}%` : ''}
                          </td>
                          <td className={`px-3 py-2 text-right font-mono ${(row.pnlInr ?? 0) >= 0 ? 'text-nexus-green' : 'text-nexus-red'}`}>
                            {row.closed ? `₹${(row.pnlInr ?? 0).toLocaleString('en-IN')}` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <EmptyState>No exact funnel transitions were recorded for this date.</EmptyState>
                )}
              </div>

              <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
                <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300 mb-2">Top blockers</h3>
                <div className="space-y-2">
                  {topBlockers.length ? topBlockers.map(([name, count]) => (
                    <div key={name}>
                      <div className="flex justify-between gap-2 text-[9px]">
                        <span className="text-nexus-muted truncate">{name.replace(/_/g, ' ')}</span>
                        <span className="font-mono text-white">{count}</span>
                      </div>
                      <div className="mt-1 h-1 rounded-full bg-gray-800 overflow-hidden">
                        <div
                          className="h-full bg-nexus-yellow"
                          style={{ width: `${Math.min(100, count / (topBlockers[0]?.[1] || 1) * 100)}%` }}
                        />
                      </div>
                    </div>
                  )) : <span className="text-[10px] text-nexus-muted">No per-contract blockers recorded.</span>}
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {tab === 'system' ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
              <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
                <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300 mb-2">Live feed</h3>
                <div className="space-y-1.5 text-[10px]">
                  <div className="flex justify-between"><span className="text-nexus-muted">WebSocket</span><span className={health?.feed?.connected ? 'text-nexus-green' : 'text-gray-400'}>{health?.feed?.connected ? 'Connected' : 'Offline'}</span></div>
                  <div className="flex justify-between"><span className="text-nexus-muted">Recent ticks</span><span className="font-mono">{health?.feed?.hasRecentTicks ? 'YES' : 'NO'}</span></div>
                  <div className="flex justify-between"><span className="text-nexus-muted">Message age</span><span className="font-mono">{compactNumber(health?.feed?.lastMessageAgeMs, 'ms')}</span></div>
                  <div className="flex justify-between"><span className="text-nexus-muted">Subscriptions</span><span className="font-mono">{health?.feed?.subscribedInstruments ?? 0}</span></div>
                </div>
              </div>

              <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
                <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300 mb-2">Scan cadence</h3>
                <div className="space-y-1.5 text-[10px]">
                  <div className="flex justify-between"><span className="text-nexus-muted">Entry target</span><span className="font-mono">{compactNumber(health?.cadence?.entryScanIntervalMs, 'ms')}</span></div>
                  <div className="flex justify-between"><span className="text-nexus-muted">Fast cycle</span><span className="font-mono">{compactNumber(health?.cadence?.lastFastCycleMs, 'ms')}</span></div>
                  <div className="flex justify-between"><span className="text-nexus-muted">Full cycle</span><span className="font-mono">{compactNumber(health?.cadence?.lastFullCycleMs, 'ms')}</span></div>
                  <div className="flex justify-between"><span className="text-nexus-muted">REST rebuild</span><span>{health?.cadence?.fullRestRebuildRunning ? 'Running' : 'Idle'}</span></div>
                </div>
              </div>

              <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
                <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300 mb-2">Archive sources</h3>
                <div className="space-y-2">
                  {Object.entries(health?.sources ?? {}).length ? Object.entries(health?.sources ?? {}).map(([name, source]) => (
                    <div key={name} className="rounded-lg bg-black/25 p-2 text-[9px]">
                      <div className="flex justify-between gap-2">
                        <span className="text-white">{name.replace(/_/g, ' ')}</span>
                        <span className={source.stale ? 'text-nexus-red' : 'text-nexus-green'}>{source.stale ? 'STALE' : `${compactNumber(source.ageSeconds, 's')}`}</span>
                      </div>
                      <div className="mt-1 text-nexus-muted">{source.archiveEntryCount ?? 0} archived · {source.dataAvailableCount ?? 0} symbols</div>
                    </div>
                  )) : <span className="text-[10px] text-nexus-muted">Waiting for first detector scan.</span>}
                </div>
              </div>

              <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
                <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300 mb-2">Durable backup</h3>
                <div className="text-[10px] space-y-1.5">
                  <div className="flex justify-between"><span className="text-nexus-muted">Status</span><span className={health?.backup?.healthy === false ? 'text-nexus-red' : 'text-nexus-green'}>{health?.backup?.healthy === false ? 'Failed' : health?.backup?.lastAttemptAt ? 'Complete' : 'Not run'}</span></div>
                  <div className="text-[9px] text-nexus-muted break-all">{health?.backup?.destination ?? 'Configure mounted storage or S3.'}</div>
                  {health?.backup?.lastError ? <div className="text-[9px] text-nexus-red">{health.backup.lastError}</div> : null}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-nexus-border bg-black/15 p-3">
              <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
                <div>
                  <h3 className="text-[10px] uppercase tracking-[0.12em] text-gray-300">Review controls</h3>
                  <p className="text-[9px] text-nexus-muted mt-1">Replays are read-only. Production replay runs in an isolated process.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={action != null}
                    onClick={() => runAction('threshold-replay', `/api/ai/radar-replay/${selectedDate}`, (payload) => `Threshold replay: ${payload.truthCount ?? 0} FTV moves`)}
                    className="rounded-lg border border-purple-500/35 bg-purple-500/10 px-3 py-2 text-[10px] text-purple-300 hover:bg-purple-500/20 disabled:opacity-50"
                  >
                    {action === 'threshold-replay' ? 'Replaying…' : 'Threshold replay'}
                  </button>
                  <button
                    type="button"
                    disabled={action != null}
                    onClick={() => runAction('detector-replay', `/api/ai/radar-detector-replay/${selectedDate}`, (payload) => `Detector replay: ${payload.uniqueRadarKeys ?? 0} radar keys`)}
                    className="rounded-lg border border-nexus-accent/35 bg-nexus-accent/10 px-3 py-2 text-[10px] text-nexus-accent hover:bg-nexus-accent/20 disabled:opacity-50"
                  >
                    {action === 'detector-replay' ? 'Running detector…' : 'Production replay'}
                  </button>
                  <button
                    type="button"
                    disabled={action != null}
                    onClick={() => runAction('finalize', `/api/ai/radar-finalize/${selectedDate}`, (payload) => payload.backup?.configured ? 'ZIP finalized and backed up' : 'ZIP finalized locally')}
                    className="rounded-lg border border-nexus-green/35 bg-nexus-green/10 px-3 py-2 text-[10px] text-nexus-green hover:bg-nexus-green/20 disabled:opacity-50"
                  >
                    {action === 'finalize' ? 'Finalizing…' : 'Finalize & backup'}
                  </button>
                </div>
              </div>
              {actionMessage ? <div className="mt-2 text-[9px] text-nexus-accent">{actionMessage}</div> : null}
              {detectorReplay ? (
                <div className="mt-2 flex flex-wrap gap-3 text-[9px] font-mono text-nexus-muted">
                  <span>{detectorReplay.sampleBatches ?? 0} sample batches</span>
                  <span>{detectorReplay.uniqueRadarKeys ?? 0} unique radar keys</span>
                  <span>{detectorReplay.timeline?.length ?? 0} improvements</span>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {!loading && archives.length === 0 && tab !== 'system' ? (
          <div className="mt-4 text-[9px] text-nexus-muted">
            No daily ZIP exists yet. The first available market snapshot creates it automatically.
          </div>
        ) : null}
      </div>
    </section>
  );
}
