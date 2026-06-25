export interface StreamMetrics {
  lastLatencyMs: number;
  avgLatencyMs: number;
  lastUpdatedAt: Date | null;
  stalenessMs: number;
  pollIntervalMs: number;
  connectionQuality: 'excellent' | 'good' | 'slow' | 'offline';
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

export interface AutoTraderState {
  paperTrading: boolean;
  liveTradingEnabled: boolean;
  running: boolean;
  openPaperTrades: PaperTrade[];
  closedPaperTrades: PaperTrade[];
  dailyReport: DailyReport;
  tradeMastermind: TradeMastermind;
  skipped: { symbol: string; reason: string; trade: string }[];
  calibrationBlocks: Record<string, boolean>;
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
}

export interface DailyTokenStatus {
  hasToken: boolean;
  validToday: boolean;
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
