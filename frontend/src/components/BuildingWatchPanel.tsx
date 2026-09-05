import { useMemo, useState } from 'react';
import { Panel, Metric } from './Panel';
import type {
  AutoTraderState,
  BuildingLtpScoreRow,
  ExplosionAlert,
  MultiSnapshot,
  SymbolSnapshot,
} from '../types';

type FilterTier = 'ALL' | 'BUILDING' | 'WATCH' | 'LTP';

interface WatchRow {
  key: string;
  symbol: string;
  side: string;
  strike: number;
  tier: string;
  score: number;
  premium: number;
  localPct: number;
  fvq: number;
  velocity3s: number;
  source: 'radar' | 'ltp' | 'runner';
  ready: boolean;
  readyReason: string;
  helping: boolean;
  suddenLift: boolean;
  helpers: string[];
  tradeable: boolean;
  momentType: string;
  ictTags: string[];
  rank: number;
  isBestReady: boolean;
}

const TIER_COLORS: Record<string, string> = {
  ELITE: 'text-yellow-400 border-yellow-500/40 bg-yellow-500/10',
  EXPLODING: 'text-nexus-green border-nexus-green/40 bg-nexus-green/10',
  BUILDING: 'text-nexus-accent border-nexus-accent/40 bg-nexus-accent/10',
  WATCH: 'text-nexus-muted border-nexus-border bg-black/20',
};

const TIER_RANK: Record<string, number> = {
  ELITE: 4,
  EXPLODING: 3,
  BUILDING: 2,
  WATCH: 1,
};

function ictTagsFromAlert(alert: ExplosionAlert): string[] {
  const tags: string[] = [];
  if (alert.ictVRipReady) tags.push('V-RIP');
  if (alert.ictBaseArmed) tags.push('ARMED');
  if (alert.ictArmedBaseLaunch) tags.push('LAUNCH');
  if (alert.ictEliteBaseReady) tags.push('ELITE-BASE');
  if (alert.ictBuildingRipReady) tags.push('BUILD-RIP');
  if (alert.ictFlatThenVertical) tags.push('FTV');
  if (alert.ictVolumeAwakening) tags.push('VOL↑');
  if (alert.ictDisplacement) tags.push('DISP');
  if (alert.ictLocalSwingBase) tags.push('SWING');
  return tags;
}

function rowFromAlert(symbol: string, alert: ExplosionAlert): WatchRow {
  const tier = String(alert.tier || 'WATCH').toUpperCase();
  return {
    key: `${symbol}:${alert.side}:${alert.strike}:radar`,
    symbol,
    side: String(alert.side || '').toUpperCase(),
    strike: Number(alert.strike || 0),
    tier,
    score: Number(alert.explosionScore || 0),
    premium: Number(alert.premium || 0),
    localPct: Number(alert.ictBaseRelativeMovePct ?? alert.localBaseMovePct ?? 0),
    fvq: Number(alert.flatVerticalQuality || 0),
    velocity3s: Number(alert.velocity3s || 0),
    source: 'radar',
    ready: Boolean(alert.tradeable),
    readyReason: alert.tradeable ? 'tradeable' : tier,
    helping: false,
    suddenLift: false,
    helpers: alert.ictReasons?.slice(0, 4) ?? [],
    tradeable: Boolean(alert.tradeable),
    momentType: String(alert.momentType || ''),
    ictTags: ictTagsFromAlert(alert),
    rank: 0,
    isBestReady: false,
  };
}

function rowFromLtp(row: BuildingLtpScoreRow): WatchRow {
  return {
    key: row.key || `${row.symbol}:${row.side}:${row.strike}:ltp`,
    symbol: row.symbol,
    side: String(row.side || '').toUpperCase(),
    strike: Number(row.strike || 0),
    tier: String(row.tier || 'BUILDING').toUpperCase(),
    score: Number(row.score || 0),
    premium: Number(row.ltp || 0),
    localPct: Number(row.local_move_pct || 0),
    fvq: 0,
    velocity3s: Number(row.velocity_3s || 0),
    source: 'ltp',
    ready: Boolean(row.ready),
    readyReason: String(row.ready_reason || ''),
    helping: Boolean(row.helping),
    suddenLift: Boolean(row.sudden_lift),
    helpers: row.helpers ?? [],
    tradeable: Boolean(row.ready),
    momentType: '',
    ictTags: row.sudden_lift ? ['LIFT'] : row.helping ? ['HELPING'] : [],
    rank: Number(row.rank || 0),
    isBestReady: Boolean(row.is_best_ready),
  };
}

function mergeWatchRows(
  snapshots: Record<string, SymbolSnapshot>,
  ltpRows: BuildingLtpScoreRow[],
): WatchRow[] {
  const byKey = new Map<string, WatchRow>();

  for (const [symbol, snap] of Object.entries(snapshots)) {
    if (!snap?.dataAvailable) continue;
    for (const alert of snap.explosionAlerts ?? []) {
      const tier = String(alert.tier || 'WATCH').toUpperCase();
      if (tier !== 'BUILDING' && tier !== 'WATCH' && tier !== 'EXPLODING') continue;
      const row = rowFromAlert(symbol, alert as ExplosionAlert);
      byKey.set(`${symbol}:${row.side}:${row.strike}`, row);
    }
    for (const runner of snap.explosiveRunnerWatchlist ?? []) {
      const side = String(runner.side || '').toUpperCase();
      const strike = Number(runner.strike || 0);
      const dedupeKey = `${symbol}:${side}:${strike}`;
      if (byKey.has(dedupeKey)) continue;
      const score = Number(runner.score || 0);
      byKey.set(dedupeKey, {
        key: `${dedupeKey}:runner`,
        symbol,
        side,
        strike,
        tier: runner.elite ? 'ELITE' : score >= 45 ? 'EXPLODING' : 'BUILDING',
        score,
        premium: Number(runner.premium || 0),
        localPct: 0,
        fvq: 0,
        velocity3s: Number(runner.premiumVelocityPct || 0),
        source: 'runner',
        ready: false,
        readyReason: 'runner_watch',
        helping: false,
        suddenLift: false,
        helpers: [],
        tradeable: false,
        momentType: '',
        ictTags: runner.elite ? ['RUNNER-ELITE'] : ['RUNNER'],
        rank: 0,
        isBestReady: false,
      });
    }
  }

  for (const ltp of ltpRows) {
    const dedupeKey = `${ltp.symbol}:${String(ltp.side).toUpperCase()}:${ltp.strike}`;
    byKey.set(dedupeKey, rowFromLtp(ltp));
  }

  return Array.from(byKey.values()).sort((a, b) => {
    const tierDiff = (TIER_RANK[b.tier] ?? 0) - (TIER_RANK[a.tier] ?? 0);
    if (tierDiff !== 0) return tierDiff;
    if (a.isBestReady !== b.isBestReady) return a.isBestReady ? -1 : 1;
    if (a.ready !== b.ready) return a.ready ? -1 : 1;
    return b.score - a.score;
  });
}

function GateChip({ label, active, tone = 'neutral' }: { label: string; active: boolean; tone?: 'good' | 'warn' | 'neutral' }) {
  const cls =
    tone === 'good'
      ? 'border-nexus-green/50 bg-nexus-green/10 text-nexus-green'
      : tone === 'warn'
        ? 'border-nexus-yellow/50 bg-nexus-yellow/10 text-nexus-yellow'
        : 'border-nexus-border bg-black/20 text-nexus-muted';
  return (
    <span className={`text-[8px] font-semibold uppercase px-1.5 py-0.5 rounded border ${active ? cls : 'border-nexus-border/30 text-gray-600 bg-black/10'}`}>
      {label}
    </span>
  );
}

export function BuildingWatchPanel({
  data,
  auto,
}: {
  data: MultiSnapshot;
  auto: AutoTraderState;
}) {
  const [filter, setFilter] = useState<FilterTier>('ALL');
  const guards = auto.chopGuards ?? {};
  const budget = guards.eliteTradeBudget;
  const gates = budget?.winRateGates;
  const lock = guards.directionalLock;
  const ltp = auto.buildingLtpMonitor;
  const ict = guards.ictBreakoutMonitor;

  const rows = useMemo(
    () => mergeWatchRows(data.snapshots, ltp?.scoreboard ?? []),
    [data.snapshots, ltp?.scoreboard],
  );

  const buildingCount = rows.filter((r) => r.tier === 'BUILDING').length;
  const watchCount = rows.filter((r) => r.tier === 'WATCH').length;
  const readyCount = rows.filter((r) => r.ready).length;

  const filtered = rows.filter((r) => {
    if (filter === 'BUILDING') return r.tier === 'BUILDING';
    if (filter === 'WATCH') return r.tier === 'WATCH';
    if (filter === 'LTP') return r.source === 'ltp';
    return true;
  });

  const badge =
    readyCount > 0
      ? `${readyCount} READY`
      : buildingCount + watchCount > 0
        ? `${buildingCount + watchCount} WATCHING`
        : 'SCAN';

  return (
    <Panel
      title="Building & Watchlist"
      badge={badge}
      badgeColor={readyCount > 0 ? 'bg-nexus-green' : buildingCount > 0 ? 'bg-nexus-accent' : 'bg-gray-600'}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        <Metric label="Building" value={buildingCount} color="text-nexus-accent" />
        <Metric label="Watch" value={watchCount} color="text-nexus-muted" />
        <Metric label="LTP ready" value={ltp?.readyCount ?? readyCount} color="text-nexus-green" />
        <Metric
          label="Elite cap"
          value={budget?.enabled ? `${budget.entriesUsed ?? 0}/${budget.weeklyCap ?? 8}` : 'OFF'}
          color={budget?.capReached ? 'text-nexus-red' : 'text-white'}
        />
      </div>

      <div className="mb-3 p-2 rounded border border-nexus-border/60 bg-black/20 space-y-2">
        <div className="text-[9px] text-nexus-muted uppercase tracking-wide">System helpers</div>
        <div className="flex flex-wrap gap-1">
          <GateChip label={`LTP ${ltp?.enabled ? 'ON' : 'OFF'}`} active={Boolean(ltp?.enabled)} tone="good" />
          <GateChip
            label={`LTP cycle ${ltp?.active ? 'LIVE' : 'idle'}`}
            active={Boolean(ltp?.active)}
            tone={ltp?.active ? 'good' : 'neutral'}
          />
          <GateChip label="V-only" active={Boolean(gates?.vRipOnly)} tone="warn" />
          <GateChip label={`FVQ≤${gates?.blockFvqAbove ?? 80}`} active={Boolean(gates?.blockFvqAbove)} />
          <GateChip label={`local≤${gates?.maxLocalBasePct ?? 20}%`} active={Boolean(gates?.maxLocalBasePct)} />
          <GateChip label="shallow-lift block" active={Boolean(gates?.shallowLiftBlock)} tone="warn" />
          <GateChip label="MR CALL block" active={Boolean(gates?.callBlockMomentumRally)} tone="warn" />
          <GateChip label="perfect-score block" active={Boolean(gates?.blockPerfectScore)} tone="warn" />
          {budget?.capReached ? <GateChip label="WEEKLY CAP" active tone="warn" /> : null}
        </div>

        {lock?.enabled && lock.symbols ? (
          <div className="flex flex-wrap gap-2 text-[9px] font-mono">
            {Object.entries(lock.symbols).map(([sym, info]) => (
              <span key={sym} className="text-nexus-muted">
                {sym}{' '}
                <span className="text-white">{info.lockedSide || '—'}</span>
                {' · '}
                {info.direction}
                {info.indexRallySideFlip ? ' · rally-flip' : ''}
                {info.indexSlideSideFlip ? ' · slide-flip' : ''}
              </span>
            ))}
          </div>
        ) : null}

        {ict?.enabled && (ict.signals?.length ?? 0) > 0 ? (
          <div className="text-[9px] text-nexus-muted">
            ICT signals: {(ict.signals ?? []).slice(0, 3).map((s) => `${s.symbol} ${s.side} ${s.strike}`).join(' · ')}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-1 mb-2">
        {(['ALL', 'BUILDING', 'WATCH', 'LTP'] as FilterTier[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded border ${
              filter === f
                ? 'border-nexus-accent bg-nexus-accent/20 text-nexus-accent'
                : 'border-nexus-border text-nexus-muted hover:text-white'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="max-h-56 overflow-y-auto space-y-1">
        {filtered.length === 0 ? (
          <p className="text-xs text-nexus-muted text-center py-4">
            No BUILDING or WATCH names — scanning chain for base setups
          </p>
        ) : (
          filtered.map((row) => (
            <div
              key={row.key}
              className={`p-1.5 rounded border text-[10px] ${TIER_COLORS[row.tier] || TIER_COLORS.WATCH}`}
            >
              <div className="flex justify-between gap-2 items-start">
                <div className="min-w-0">
                  <span className="font-bold text-white">{row.symbol}</span>{' '}
                  <span className={row.side === 'CALL' ? 'text-nexus-green' : 'text-nexus-red'}>
                    {row.side} {row.strike}
                  </span>
                  <span className="ml-1 opacity-70">{row.tier}</span>
                  {row.isBestReady ? <span className="ml-1 text-nexus-green font-bold">★ BEST</span> : null}
                  {row.ready && !row.isBestReady ? <span className="ml-1 text-nexus-yellow">✓ ready</span> : null}
                  {row.helping ? <span className="ml-1 text-nexus-accent">↑ helping</span> : null}
                  {row.suddenLift ? <span className="ml-1 text-nexus-green">LIFT</span> : null}
                </div>
                <div className="text-right shrink-0 font-mono">
                  <div>{row.score} pts · v3 +{row.velocity3s.toFixed(1)}%</div>
                  <div className="text-[9px] opacity-80">
                    {row.localPct > 0 ? `base ${row.localPct.toFixed(1)}%` : 'base —'}
                    {row.fvq > 0 ? ` · FVQ ${row.fvq.toFixed(0)}` : ''}
                    {row.premium > 0 ? ` · ₹${row.premium.toFixed(1)}` : ''}
                  </div>
                </div>
              </div>
              <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[8px] opacity-90">
                <span className="text-nexus-muted uppercase">{row.source}</span>
                {row.momentType ? <span>{row.momentType}</span> : null}
                {row.readyReason && row.readyReason !== row.tier ? <span>{row.readyReason}</span> : null}
                {row.ictTags.map((tag) => (
                  <span key={tag} className="text-nexus-accent">{tag}</span>
                ))}
                {row.rank > 0 ? <span>LTP #{row.rank}</span> : null}
              </div>
              {row.helpers.length > 0 ? (
                <div className="mt-0.5 text-[8px] text-nexus-muted truncate">
                  {row.helpers.slice(0, 5).join(' · ')}
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>

      {ltp?.best ? (
        <div className="mt-2 pt-2 border-t border-nexus-border text-[9px] font-mono text-nexus-accent">
          LTP leader: {ltp.best.side} {ltp.best.strike} · score {ltp.best.score}
          {ltp.best.helper_count != null ? ` · ${ltp.best.helper_count} helpers` : ''}
        </div>
      ) : null}

      <div className="mt-2 text-[9px] text-nexus-muted border-t border-nexus-border pt-1 leading-relaxed">
        Rank-1 per radar moment · max lots on best BUILDING/LTP ready · elite gates + weekly cap apply at entry
      </div>
    </Panel>
  );
}
