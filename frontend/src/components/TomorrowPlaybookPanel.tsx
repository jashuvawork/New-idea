import { Panel } from './Panel';
import type { AutoTraderState, DeploymentStatus, SymbolSnapshot } from '../types';
import {
  formatIstTime,
  morningCaptureWindowActive,
  momentumRallyWindowActive,
  openCautionWindowActive,
  primaryWindowActive,
} from '../lib/playbookSession';

const PHASE_TONE: Record<string, string> = {
  ACCUMULATE: 'bg-nexus-accent/90 text-black',
  BUILD: 'bg-blue-500/90 text-white',
  PROTECT: 'bg-nexus-yellow/90 text-black',
  EXTEND: 'bg-nexus-green/90 text-black',
};

const CONF_TONE: Record<string, string> = {
  LOW: 'text-nexus-red',
  MEDIUM: 'text-nexus-yellow',
  HIGH: 'text-nexus-green',
  ELITE: 'text-purple-300',
};

function StrategyChip({
  label,
  enabled,
  detail,
}: {
  label: string;
  enabled: boolean;
  detail?: string;
}) {
  return (
    <div
      className={`rounded-lg border px-2 py-1.5 ${
        enabled
          ? 'border-nexus-green/40 bg-nexus-green/10'
          : 'border-nexus-border/50 bg-black/20 opacity-60'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`text-[10px] font-bold uppercase ${enabled ? 'text-white' : 'text-nexus-muted'}`}>
          {label}
        </span>
        <span
          className={`text-[8px] font-semibold uppercase px-1 py-0.5 rounded ${
            enabled ? 'bg-nexus-green/20 text-nexus-green' : 'bg-gray-800 text-gray-500'
          }`}
        >
          {enabled ? 'ON' : 'OFF'}
        </span>
      </div>
      {detail ? <div className="text-[9px] text-nexus-muted mt-0.5 leading-snug">{detail}</div> : null}
    </div>
  );
}

function WindowChip({ label, active, hint }: { label: string; active: boolean; hint?: string }) {
  return (
    <span
      className={`text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded border ${
        active
          ? 'border-nexus-accent/50 bg-nexus-accent/10 text-nexus-accent'
          : 'border-nexus-border/40 text-gray-600 bg-black/10'
      }`}
      title={hint}
    >
      {label}
    </span>
  );
}

function hasMorningCaptureAlert(snapshots: Record<string, SymbolSnapshot>): boolean {
  for (const snap of Object.values(snapshots)) {
    for (const alert of snap.explosionAlerts ?? []) {
      if (alert.morningCapture || (alert.tier === 'BUILDING' && alert.tradeable)) {
        return true;
      }
    }
  }
  return false;
}

export function TomorrowPlaybookPanel({
  auto,
  snapshots,
  deployment,
}: {
  auto: AutoTraderState;
  snapshots: Record<string, SymbolSnapshot>;
  deployment: DeploymentStatus | null;
}) {
  const strategy = auto.dailyStrategy ?? {};
  const gate = auto.dailyProfitGate;
  const chop = auto.chopGuards ?? {};
  const flags = deployment?.flags ?? {};
  const expiry = chop.expiryGuards;

  const phase = String(strategy.phase ?? 'ACCUMULATE');
  const confTier = String(strategy.confidenceTier ?? 'MEDIUM');
  const dayMode = String(strategy.dayMode ?? chop.dayMode ?? 'NORMAL');
  const progress = Number(strategy.progressPct ?? gate?.progressPct ?? 0);
  const target = Number(strategy.dailyTargetInr ?? gate?.targetInr ?? 0);
  const sessionPnl = Number(strategy.sessionPnlInr ?? gate?.sessionPnlInr ?? 0);
  const minRank = Number(strategy.minRankScore ?? 58);
  const maxTrades = Number(strategy.maxTradesToday ?? 10);
  const closed = chop.closedTrades ?? auto.closedPaperTrades?.length ?? 0;
  const lotMult = Number(strategy.lotSizeMultiplier ?? 1);

  const morningCapture = morningCaptureWindowActive();
  const momentumRally = momentumRallyWindowActive() || Boolean(chop.momentumRallyWindow);
  const openCaution = openCautionWindowActive() || Boolean(chop.openCautionWindow);
  const morningSurge = hasMorningCaptureAlert(snapshots);

  const allowExplosion =
    Boolean(strategy.allowExplosion) || (morningCapture && (morningSurge || momentumRally));
  const allowQuick = strategy.allowQuickSideways !== false;
  const explosionMode = Boolean(flags.explosionCaptureMode ?? true);
  const quickMode = Boolean(flags.quickSidewaysEnabled ?? true);
  const scalpMode = Boolean(flags.simpleProfitMode ?? auto.tradeMastermind?.simpleProfitMode);
  const swingMode = Boolean(flags.swingTradingEnabled ?? auto.tradeMastermind?.swingTradingEnabled);

  const entriesAllowed = gate?.newEntriesAllowed !== false;
  const sessionBlockers = (auto.skipped ?? []).filter((s) => s.symbol === 'SESSION');

  const playbook: string[] = Array.isArray(strategy.playbook) ? strategy.playbook : [];
  const phaseBadge = PHASE_TONE[phase] ?? PHASE_TONE.ACCUMULATE;

  return (
    <Panel title="Live Strategy Playbook" badge={phase} badgeColor={phaseBadge}>
      <p className="text-[10px] text-nexus-muted leading-relaxed mb-3">
        Real-time plan for today&apos;s session — phase, enabled strategies, time windows, and blockers.
        <span className="text-nexus-accent ml-1 font-mono">{formatIstTime()} IST</span>
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3 text-[10px]">
        <div className="p-2 rounded bg-black/30">
          <div className="text-nexus-muted uppercase mb-0.5">Day mode</div>
          <div className="font-bold text-white">{dayMode}</div>
        </div>
        <div className="p-2 rounded bg-black/30">
          <div className="text-nexus-muted uppercase mb-0.5">Confidence</div>
          <div className={`font-bold font-mono ${CONF_TONE[confTier] ?? 'text-white'}`}>
            {confTier} ({Number(strategy.marketConfidence ?? 0).toFixed(0)})
          </div>
        </div>
        <div className="p-2 rounded bg-black/30">
          <div className="text-nexus-muted uppercase mb-0.5">18% target</div>
          <div className="font-mono text-white">
            ₹{sessionPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })} / ₹
            {target.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </div>
          <div className="text-nexus-muted">{progress.toFixed(0)}%</div>
        </div>
        <div className="p-2 rounded bg-black/30">
          <div className="text-nexus-muted uppercase mb-0.5">Rank / trades</div>
          <div className="font-mono text-white">
            ≥{minRank.toFixed(0)} · {closed}/{maxTrades}
          </div>
          <div className="text-nexus-muted">lots ×{lotMult.toFixed(2)}</div>
        </div>
      </div>

      {gate ? (
        <div className="mb-3 p-2 rounded border border-nexus-border/50 bg-black/20 text-[10px]">
          <div className="text-nexus-muted uppercase mb-0.5">Profit gate</div>
          <div className={entriesAllowed ? 'text-nexus-green' : 'text-nexus-red'}>
            {gate.status} — {gate.message}
          </div>
        </div>
      ) : null}

      <div className="text-[10px] text-nexus-muted uppercase mb-1.5">Active strategies</div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <StrategyChip
          label="Explosion"
          enabled={explosionMode && allowExplosion}
          detail={
            allowExplosion
              ? morningCapture
                ? 'BUILDING+ OK in morning capture'
                : 'EXPLODING / ELITE tier'
              : 'Blocked — chop day / low confidence'
          }
        />
        <StrategyChip
          label="Quick sideways"
          enabled={quickMode && allowQuick}
          detail="Chop scalps +3pt / −2pt · 120s hold"
        />
        <StrategyChip
          label="Regular scalp"
          enabled={scalpMode}
          detail="ML suggestions · velocity ≥1.2%"
        />
        <StrategyChip
          label="Swing"
          enabled={swingMode}
          detail="2–5 day holds · max 2 open"
        />
      </div>

      <div className="text-[10px] text-nexus-muted uppercase mb-1.5">Time windows (IST)</div>
      <div className="flex flex-wrap gap-1 mb-3">
        <WindowChip label="Open caution 9:15–9:45" active={openCaution} />
        <WindowChip label="Morning capture 10:00–11:45" active={morningCapture} hint="BUILDING CE/PE surges" />
        <WindowChip label="Momentum rally 10:00–13:45" active={momentumRally} />
        <WindowChip label="Primary ≥10:00" active={primaryWindowActive()} />
        <WindowChip label="Midday chop" active={Boolean(chop.middayChopWindow)} />
        {expiry?.expirySession ? (
          <>
            <WindowChip label="Expiry AM" active={Boolean(expiry.morningWindow)} />
            <WindowChip label="Expiry PM block" active={Boolean(expiry.eveningBlock)} />
          </>
        ) : null}
        {morningSurge ? (
          <span className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded border border-nexus-green/50 text-nexus-green bg-nexus-green/10">
            Surge live
          </span>
        ) : null}
      </div>

      {playbook.length > 0 ? (
        <div className="mb-3">
          <div className="text-[10px] text-nexus-muted uppercase mb-1">Playbook</div>
          <ul className="list-disc list-inside text-[10px] text-gray-300 space-y-0.5">
            {playbook.map((line, i) => (
              <li key={`pb-${i}`}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {strategy.message ? (
        <div className="mb-3 text-[10px] text-nexus-accent font-mono">{strategy.message}</div>
      ) : null}

      {!entriesAllowed || sessionBlockers.length > 0 ? (
        <div className="p-2 rounded border border-nexus-red/40 bg-nexus-red/10 text-[10px]">
          <div className="text-nexus-red font-semibold uppercase mb-1">Entries blocked</div>
          {sessionBlockers.length === 0 ? (
            <div className="text-white font-mono">{gate?.message ?? 'Profit gate closed'}</div>
          ) : (
            sessionBlockers.map((b, i) => (
              <div key={`blk-${i}`} className="text-white font-mono">
                {b.reason}
                {b.message ? ` — ${b.message}` : ''}
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="text-[10px] text-nexus-green font-semibold">
          Scanning — explosion &gt; quick sideways &gt; scalp &gt; swing
        </div>
      )}
    </Panel>
  );
}
