export interface StreamMetrics {
  lastLatencyMs: number;
  avgLatencyMs: number;
  lastUpdatedAt: Date | null;
  stalenessMs: number;
  pollIntervalMs: number;
  connectionQuality: 'excellent' | 'good' | 'slow' | 'offline';
  streamMode?: 'sse' | 'poll';
}

export interface MultiSnapshot {
  type: string;
  timestamp: string;
  dataReady: boolean;
  waitingReason?: string;
  snapshots: Record<string, SymbolSnapshot>;
  autoTrader: AutoTraderState;
  news: NewsItem[];
}

export interface SymbolSnapshot {
  symbol: string;
  timestamp: string;
  marketPhase: string;
  dataAvailable: boolean;
  error?: string;
  tradeQualityScore: number;
  regime: string;
  spot?: number;
  atmStrike?: number;
  heatmap: HeatmapStrike[];
  orderflow: Orderflow;
  greeks: Greeks;
  marketProfile: MarketProfile;
  breadth: Breadth;
  explosiveRunner: ExplosiveRunner;
  explosiveRunnerWatchlist: RunnerWatchItem[];
  suggestedTrades: SuggestedTrade[];
  optimizedProfile: OptimizedProfile;
  strategyMatrix?: StrategyMatrixEntry[];
  mlInsights?: MLInsights;
  pcr?: number;
  maxPain?: number;
  explosionAlerts?: ExplosionAlert[];
  topExplosion?: ExplosionAlert;
  swingAlerts?: SwingAlert[];
  topSwing?: SwingAlert;
  constituentHeatmap?: ConstituentHeatmap | null;
  psychology?: Record<string, unknown>;
  adaptiveExitHint?: Record<string, unknown>;
  premarket?: PremarketAnalysis | null;
}

export interface PremarketAnalysis {
  prevClose: number;
  indicativeOpen: number;
  gapPoints: number;
  gapPct: number;
  gapDirection: string;
  gapSize: string;
  preOpenHigh: number;
  preOpenLow: number;
  preOpenVolume: number;
  constituentGapBreadth: number;
  volumeSurgeScore: number;
  auctionBias: string;
  openPlay: string;
  explosionRisk: string;
  confidence: number;
  minutesToOpen: number;
  gapLeaders: string[];
  gapLaggards: string[];
  scenarios: string[];
  analysis: string;
}

export interface ConstituentTile {
  symbol: string;
  name: string;
  weight: number;
  ltp: number;
  changePct: number;
  open: number;
  high: number;
  low: number;
  vwap: number;
  volume: number;
}

export interface ConstituentHeatmap {
  symbol: string;
  indexLabel: string;
  timestamp?: string;
  dataAvailable: boolean;
  error?: string;
  stockCount: number;
  advancing: number;
  declining: number;
  unchanged: number;
  breadthPct: number;
  bias: string;
  analysis: string;
  tiles: ConstituentTile[];
}

export interface SwingAlert {
  symbol: string;
  side: string;
  strike: number;
  premium: number;
  swingType: string;
  confidence: number;
  reason: string;
  targetPct: number;
  stopPct: number;
  maxHoldDays: number;
  tradeable: boolean;
  metadata?: Record<string, unknown>;
}

export interface ExplosionAlert {
  symbol: string;
  side: string;
  strike: number;
  premium: number;
  velocity3s: number;
  velocity9s: number;
  velocity15s: number;
  volumeSurge: number;
  explosionScore: number;
  tier: string;
  reason: string;
  tradeable: boolean;
}

export interface StrategyMatrixEntry {
  id: string;
  name: string;
  status: string;
  confidence: number;
  mlProbability: number;
  preferredSession?: string[];
  sessionMatch?: boolean;
}

export interface MLInsights {
  featureImportance?: Record<string, number>;
  modelTrained?: boolean;
  activeStrategies?: number;
  topStrategy?: StrategyMatrixEntry;
}

export interface HeatmapStrike {
  strike: number;
  callOi: number;
  putOi: number;
  callLtp?: number;
  putLtp?: number;
  gammaWall: boolean;
  liquidityScore: number;
  sweepRisk: number;
}

export interface Orderflow {
  deltaVelocity: number;
  volumeAcceleration: number;
  breakoutVelocity: number;
  bidAskImbalance: number;
  tickMomentum: number;
}

export interface Greeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  ivExpansion: number;
  ivRank: number;
}

export interface MarketProfile {
  poc: number;
  vah: number;
  val: number;
  openingRangeHigh: number;
  openingRangeLow: number;
}

export interface Breadth {
  score: number;
  bias: string;
  aligned: boolean;
}

export interface ExplosiveRunner {
  candidate: boolean;
  score: number;
  side?: string;
  strike?: number;
  premium?: number;
  signal?: RunnerSignal;
}

export interface RunnerSignal {
  score: number;
  premiumVelocityPct: number;
  volumeSurge: number;
  elite: boolean;
}

export interface RunnerWatchItem {
  strike: number;
  side: string;
  score: number;
  premiumVelocityPct: number;
  premium: number;
  elite: boolean;
}

export interface SuggestedTrade {
  id: string;
  symbol: string;
  side: string;
  strike: number;
  lastPremium: number;
  tqs: number;
  strategyType: string;
  runnerSignal?: RunnerSignal;
  confidence: number;
  adaptiveTarget?: number;
}

export interface OptimizedProfile {
  targetPoints: number;
  stopPoints: number;
  microTargetPoints: number;
  maxHoldSeconds: number;
  sessionLabel: string;
}

export interface ChopGuards {
  chopSession?: boolean;
  dailyTradeCap?: number;
  dailyTradeCapLabel?: string;
  closedTrades?: number;
  tradeCapReached?: boolean;
  tradeCapMessage?: string | null;
  lossStreak?: number;
  sessionPaused?: boolean;
  pauseReason?: string | null;
  beforePrimaryWindow?: boolean;
  momentumRallyWindow?: boolean;
  openCautionWindow?: boolean;
  middayChopWindow?: boolean;
  sessionLabel?: string;
  sessionTargetPoints?: number;
  guardsEnabled?: boolean;
  dayMode?: string;
  dayModeTone?: string;
  dayModeHint?: string;
  symbolBreadth?: Record<string, SymbolBreadthSummary>;
  indexMoments?: Record<string, IndexMomentSummary>;
}

export interface SymbolBreadthSummary {
  bias: string;
  score: number;
  aligned: boolean;
  regime: string;
}

export interface IndexMomentSummary {
  exchange?: string;
  momentActive?: boolean;
  momentReason?: string | null;
  gapDirection?: string | null;
  gapSize?: string | null;
  gapPct?: number | null;
  auctionBias?: string | null;
  explosionRisk?: string | null;
  constituentBreadthPct?: number | null;
  constituentBias?: string | null;
  constituentAdvancing?: number | null;
  constituentDeclining?: number | null;
}

export interface AutoTraderState {
  paperTrading: boolean;
  liveTradingEnabled: boolean;
  autoTradingEnabled: boolean;
  running: boolean;
  openPaperTrades: PaperTrade[];
  closedPaperTrades: PaperTrade[];
  dailyReport: DailyReport;
  tradeMastermind: TradeMastermind;
  skipped: { symbol: string; reason: string; trade?: string; message?: string; mode?: string; score?: number; tradeId?: string }[];
  calibrationBlocks: Record<string, boolean>;
  capitalAllocation?: CapitalAllocation;
  dailyProfitGate?: DailyProfitGate;
  lastEntry?: AutoTradeEvent | null;
  lastExit?: AutoTradeEvent | null;
  liveOrdersPlaced?: number;
  chopGuards?: ChopGuards;
}

export interface AutoTradeEvent {
  tradeId?: string;
  symbol?: string;
  side?: string;
  strike?: number;
  lots?: number;
  mode?: string;
  score?: number;
  reason?: string;
  pnlInr?: number;
  executionMode?: string;
  brokerOrderId?: string;
  brokerExitOrderId?: string;
  at?: string;
}

export interface CapitalAllocation {
  availableMarginInr: number;
  usedMarginInr: number;
  totalEquityInr: number;
  source: string;
  perTradeRiskInr: number;
  perTradeCapitalInr: number;
  maxExposureInr: number;
  minLots: number;
  targetLots: number;
  maxLots: number;
  fetchedAt?: string;
  lotSizes?: Record<string, number>;
  lotSizesSource?: string;
  lotSizesFetchedAt?: string;
}

export interface DailyProfitGate {
  targetInr: number;
  minTargetInr?: number;
  trailInr: number;
  capitalBaseInr?: number;
  sessionPnlInr: number;
  bestPnlInr: number;
  trailFloorInr: number;
  lockedFloorInr?: number;
  currentStage?: number;
  minTargetHit?: boolean;
  targetHit: boolean;
  trailLocked: boolean;
  newEntriesAllowed: boolean;
  status: string;
  message: string;
  progressPct: number;
  stageLockMode?: boolean;
  stages?: Array<{
    stage: number;
    pct: number;
    thresholdInr: number;
    reached: boolean;
    label: string;
  }>;
}

export interface PaperTrade {
  id: string;
  symbol: string;
  side: string;
  strike: number;
  entryPremium: number;
  currentPremium?: number;
  lots: number;
  pnlInr: number;
  pnlPoints: number;
  openedAt: string;
  closedAt?: string;
  sessionDate?: string;
  status: string;
  exitReason?: string;
  strategyType: string;
  bestPnlPoints: number;
  entryContext?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

export interface DayArchiveSummary {
  totalTrades?: number;
  wins?: number;
  losses?: number;
  scratches?: number;
  netPnlInr?: number;
  profitFactor?: number;
  winRate?: number;
}

export interface TradeDaySummary {
  date: string;
  summary: DayArchiveSummary;
  tradeCount: number;
  eventCount: number;
}

export interface TradeHistoryResponse {
  days: TradeDaySummary[];
  storeDir: string;
  logFile?: string;
  logSizeBytes?: number;
}

export interface TradeLogEntry {
  ts: string;
  event: string;
  trade?: Record<string, unknown>;
  context?: Record<string, unknown>;
  reason?: string;
  holdSeconds?: number;
}

export interface TradeLogResponse {
  logFile: string;
  entries: TradeLogEntry[];
}

export interface DeploymentReadiness {
  readyForPaper: boolean;
  readyForLive: boolean;
  executionMode: string;
  checks: Record<string, boolean>;
  tradeLog: {
    storeDir: string;
    logFile: string;
    logSizeBytes: number;
    todayCounts: { open: number; closed: number; total: number };
  };
  armLiveSteps: string[];
  openTrades: number;
  milestone?: PerformanceMilestone;
}

export interface TradeLogStatus {
  storeDir: string;
  logFile: string;
  logSizeBytes: number;
  writable: boolean;
  todayOpen: number;
  todayClosed: number;
}

export interface DeploymentStatus {
  status: string;
  commit: string;
  environment: string;
  upstox: DailyTokenStatus;
  flags: Record<string, boolean | number>;
  tradeLog?: TradeLogStatus;
}

export interface DailyTokenStatus {
  hasToken: boolean;
  validToday: boolean;
  expired?: boolean;
  expiresAt?: string;
  recommendedLoginAfter?: string;
  sessionDate?: string;
  today: string;
  generatedAt?: string;
  oneTimePerDay: boolean;
  canLogin: boolean;
  message: string;
}

export interface DailyReport {
  wins: number;
  losses: number;
  scratches: number;
  profitFactor: number;
  netPnlInr: number;
  winRate: number;
  exitReasons: Record<string, number>;
}

export interface PerformanceMilestone {
  tradeCount: number;
  targetTrades: number;
  tradeProgressPct: number;
  batchNumber: number;
  completedBatches: number;
  lifetimeTradeCount: number;
  wins: number;
  losses: number;
  scratches: number;
  profitFactor: number;
  targetProfitFactor: number;
  winRate: number;
  targetWinRate: number;
  maxDrawdownPct: number;
  maxDrawdownLimitPct: number;
  netPnlInr: number;
  checks: {
    tradeCountMet: boolean;
    profitFactorMet: boolean;
    winRateMet: boolean;
    drawdownMet: boolean;
  };
  checksPassed: number;
  checksTotal: number;
  readyForLiveMilestone: boolean;
  message: string;
  slippageAdjusted?: boolean;
  slippageNote?: string;
}

export interface TradeMastermind {
  simpleProfitMode: boolean;
  dualStrategyEnabled: boolean;
  swingTradingEnabled?: boolean;
  simpleMaxLots: number;
  simpleTargetLots: number;
  simpleMinLots: number;
  simpleMicroTargetPoints: number;
  enhancedMode: boolean;
  adaptiveTargets: boolean;
}

export interface NewsItem {
  headline: string;
  summary: string;
  source: string;
  sentiment: string;
}

export interface DeploymentStatus {
  status: string;
  commit: string;
  environment: string;
  upstox: DailyTokenStatus;
  flags: Record<string, boolean | number>;
}
