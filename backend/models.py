from pydantic import BaseModel
from typing import Optional


class TradeQuery(BaseModel):
    symbol: str
    side: str
    leverage: int
    funding_rate: Optional[float] = None
    rsi: Optional[float] = None
    fear_greed: Optional[int] = None
    long_short_ratio: Optional[float] = None


class RiskResponse(BaseModel):
    symbol: str
    side: str
    leverage: int
    liquidation_probability: float
    confidence: str
    similar_events_found: int
    median_time_to_liquidation_hours: Optional[float]
    worst_case_hours: Optional[float]
    top_risk_factors: list[str]
    regime_warning: Optional[str]
    verdict: str


class LiquidationEvent(BaseModel):
    id: int
    timestamp: str
    symbol: str
    side: str
    size_usd: float
    leverage: Optional[int]
    price: float
    regime: Optional[str]
    funding_rate: Optional[float]
    rsi_at_event: Optional[float]
    fear_greed_at_event: Optional[int]


class RegimeSnapshot(BaseModel):
    symbol: str
    regime: str
    rsi: Optional[float]
    macd_signal: Optional[str]
    funding_rate: Optional[float]
    fear_greed: Optional[int]
    long_short_ratio: Optional[float]


class ClusterSummary(BaseModel):
    regime: str
    side: str
    total_liquidations: int
    avg_leverage: float
    avg_funding_rate: Optional[float]
    avg_rsi: Optional[float]
    avg_size_usd: float
    pct_of_total: float


class PatternEntry(BaseModel):
    rank: int
    regime: str
    side: str
    leverage_bucket: str
    avg_funding: Optional[float]
    avg_rsi: Optional[float]
    count: int
    pct_of_total: float
    insight: str
