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
  status: string;
  exitReason?: string;
  strategyType: string;
  bestPnlPoints: number;
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
  upstox: { hasToken: boolean };
  flags: Record<string, boolean | number>;
}
