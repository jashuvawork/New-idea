"""Pydantic models for NexusQuant API payloads."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MarketPhase(str, Enum):
    PREMARKET = "PREMARKET"
    LIVE_MARKET = "LIVE_MARKET"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"


class Regime(str, Enum):
    TREND_EXPANSION = "TREND_EXPANSION"
    RANGE_BOUND = "RANGE_BOUND"
    CHOP = "CHOP"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"


class Side(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class StrategyType(str, Enum):
    SCALP = "SCALP"
    EXPLOSIVE = "EXPLOSIVE"
    DUAL_SCALP = "DUAL_SCALP"
    SWING = "SWING"


class HeatmapStrike(BaseModel):
    strike: float
    callOi: int = 0
    putOi: int = 0
    callLtp: Optional[float] = None
    putLtp: Optional[float] = None
    gammaWall: bool = False
    liquidityScore: float = 0
    sweepRisk: float = 0


class Orderflow(BaseModel):
    deltaVelocity: float = 0
    volumeAcceleration: float = 0
    breakoutVelocity: float = 0
    bidAskImbalance: float = 0
    tickMomentum: float = 0  # enhanced: tick-level fusion


class Greeks(BaseModel):
    delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0
    ivExpansion: float = 1.0
    ivRank: float = 50


class MarketProfile(BaseModel):
    poc: float = 0
    vah: float = 0
    val: float = 0
    openingRangeHigh: float = 0
    openingRangeLow: float = 0


class Breadth(BaseModel):
    score: float = 50
    bias: str = "NEUTRAL"
    aligned: bool = False


class ConstituentTile(BaseModel):
    symbol: str
    name: str
    weight: float
    ltp: float
    changePct: float
    open: float = 0
    high: float = 0
    low: float = 0
    vwap: float = 0
    volume: float = 0


class ConstituentHeatmap(BaseModel):
    symbol: str
    indexLabel: str = ""
    timestamp: Optional[datetime] = None
    dataAvailable: bool = False
    error: Optional[str] = None
    stockCount: int = 0
    advancing: int = 0
    declining: int = 0
    unchanged: int = 0
    breadthPct: float = 50.0
    bias: str = "NEUTRAL"
    analysis: str = ""
    tiles: list[ConstituentTile] = []


class RunnerSignal(BaseModel):
    score: float = 0
    premiumVelocityPct: float = 0
    volumeSurge: float = 0
    elite: bool = False


class ExplosiveRunner(BaseModel):
    candidate: bool = False
    score: float = 0
    side: Optional[Side] = None
    strike: Optional[float] = None
    premium: Optional[float] = None
    signal: Optional[RunnerSignal] = None


class SuggestedTrade(BaseModel):
    id: str
    symbol: str
    side: Side
    strike: float
    lastPremium: float
    tqs: float
    strategyType: StrategyType = StrategyType.SCALP
    runnerSignal: Optional[RunnerSignal] = None
    confidence: float = 0
    adaptiveTarget: Optional[float] = None  # enhanced


class OptimizedProfile(BaseModel):
    targetPoints: float = 6.0
    stopPoints: float = 3.0
    microTargetPoints: float = 2.5
    maxHoldSeconds: int = 180
    sessionLabel: str = "normal"


class SymbolSnapshot(BaseModel):
    symbol: str
    timestamp: datetime
    marketPhase: MarketPhase
    dataAvailable: bool = True
    error: Optional[str] = None
    tradeQualityScore: float = 0
    regime: Regime = Regime.RANGE_BOUND
    spot: Optional[float] = None
    atmStrike: Optional[float] = None
    heatmap: list[HeatmapStrike] = []
    orderflow: Orderflow = Field(default_factory=Orderflow)
    greeks: Greeks = Field(default_factory=Greeks)
    marketProfile: MarketProfile = Field(default_factory=MarketProfile)
    breadth: Breadth = Field(default_factory=Breadth)
    explosiveRunner: ExplosiveRunner = Field(default_factory=ExplosiveRunner)
    explosiveRunnerWatchlist: list[dict[str, Any]] = []
    suggestedTrades: list[SuggestedTrade] = []
    optimizedProfile: OptimizedProfile = Field(default_factory=OptimizedProfile)
    strategyMatrix: list[dict[str, Any]] = []
    mlInsights: dict[str, Any] = {}
    pcr: float = 1.0
    maxPain: float = 0
    explosionAlerts: list[dict[str, Any]] = []
    topExplosion: Optional[dict[str, Any]] = None
    swingAlerts: list[dict[str, Any]] = []
    topSwing: Optional[dict[str, Any]] = None
    constituentHeatmap: Optional[ConstituentHeatmap] = None
    psychology: dict[str, Any] = {}
    adaptiveExitHint: dict[str, Any] = {}


class PaperTrade(BaseModel):
    id: str
    symbol: str
    side: Side
    strike: float
    entryPremium: float
    currentPremium: Optional[float] = None
    lots: int
    pnlInr: float = 0
    pnlPoints: float = 0
    openedAt: datetime
    status: str = "OPEN"
    exitReason: Optional[str] = None
    strategyType: StrategyType = StrategyType.SCALP
    bestPnlPoints: float = 0
    closedAt: Optional[datetime] = None
    sessionDate: Optional[str] = None
    entryContext: dict[str, Any] = {}


class DailyReport(BaseModel):
    wins: int = 0
    losses: int = 0
    scratches: int = 0
    profitFactor: float = 0
    netPnlInr: float = 0
    winRate: float = 0
    exitReasons: dict[str, int] = {}


class TradeMastermind(BaseModel):
    simpleProfitMode: bool = True
    dualStrategyEnabled: bool = False
    swingTradingEnabled: bool = True
    simpleMaxLots: int = 14
    simpleTargetLots: int = 10
    simpleMinLots: int = 6
    simpleMicroTargetPoints: float = 2.5
    enhancedMode: bool = True
    adaptiveTargets: bool = True


class AutoTraderState(BaseModel):
    paperTrading: bool = True
    liveTradingEnabled: bool = False
    running: bool = True
    openPaperTrades: list[PaperTrade] = []
    closedPaperTrades: list[PaperTrade] = []
    dailyReport: DailyReport = Field(default_factory=DailyReport)
    tradeMastermind: TradeMastermind = Field(default_factory=TradeMastermind)
    skipped: list[dict[str, Any]] = []
    calibrationBlocks: dict[str, bool] = {"CALL": False, "PUT": False}


class MultiSnapshot(BaseModel):
    type: str = "multi_snapshot"
    timestamp: datetime
    dataReady: bool = False
    waitingReason: Optional[str] = None
    snapshots: dict[str, SymbolSnapshot] = {}
    autoTrader: AutoTraderState = Field(default_factory=AutoTraderState)
    news: list[dict[str, Any]] = []


class RiskProfile(BaseModel):
    maxOpenTrades: int = 3
    maxExposureInr: float = 100_000
    tqsThreshold: int = 68
    safeMode: bool = False


class CapitalConfig(BaseModel):
    allocatedInr: float = 500_000
    perTradeRiskInr: float = 12_000
    emergencyStopInr: float = 18_000
