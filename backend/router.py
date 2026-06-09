from datetime import datetime
from statistics import median
from typing import Optional

from fastapi import APIRouter, Query

import database
import tagger
from models import ClusterSummary, LiquidationEvent, PatternEntry, RegimeSnapshot, RiskResponse, TradeQuery


router = APIRouter()


INSIGHTS = {
    ("trending_bull", "long"): "High leverage longs during peak greed. Every time.",
    ("trending_bull", "short"): "Shorting momentum - the most expensive mistake in crypto.",
    ("trending_bear", "short"): "Late shorts pile in at the bottom. Trapped by reversals.",
    ("trending_bear", "long"): "Catching falling knives with leverage. No survivors.",
    ("ranging", "long"): "Range longs get faked out by false breakouts.",
    ("ranging", "short"): "Range shorts eaten alive by the upper wick.",
    ("volatile", "long"): "Volatility spikes liquidate longs in seconds.",
    ("volatile", "short"): "Dead cat bounces destroy leveraged shorts.",
    ("crash", "long"): "Buying the dip with leverage during a crash. Never works.",
    ("crash", "short"): "Shorts opened too late - liquidated on the bounce.",
}


@router.get("/health")
def health():
    db = database.get_db()
    count = db.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0]
    db.close()
    return {"status": "ok", "version": "1.0.0", "db_events": count}


def _parse_ts(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _time_metrics(events: list[dict]):
    if len(events) < 2:
        return None, None
    timestamps = sorted(_parse_ts(row["timestamp"]) for row in events)
    gaps = [
        max(0.01, (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600)
        for i in range(1, len(timestamps))
    ]
    if not gaps:
        return None, None
    return round(median(gaps), 2), round(min(gaps), 2)


def _risk_factors(query: TradeQuery):
    factors = []
    if query.leverage >= 20:
        factors.append("Extreme leverage (20x+) - top liquidation tier")
    elif query.leverage >= 10:
        factors.append("High leverage in volatile conditions")
    if query.rsi is not None and query.rsi > 70 and query.side == "long":
        factors.append("RSI overbought - momentum exhaustion risk")
    if query.rsi is not None and query.rsi < 30 and query.side == "short":
        factors.append("RSI oversold - short squeeze risk")
    if query.funding_rate is not None and query.funding_rate > 0.03:
        factors.append("Extreme positive funding - longs overpaying")
    if query.funding_rate is not None and query.funding_rate < -0.02:
        factors.append("Extreme negative funding - shorts overpaying")
    if query.fear_greed is not None and query.fear_greed > 75 and query.side == "long":
        factors.append("Peak greed - historically precedes corrections")
    if query.fear_greed is not None and query.fear_greed < 25 and query.side == "short":
        factors.append("Extreme fear - capitulation risk for shorts")
    if not factors:
        factors.append("No single extreme input, risk comes from historical similarity cluster")
    return factors


def _regime_warning(regime: str, side: str):
    if regime == "crash" and side == "long":
        return "Current regime resembles crash conditions; leveraged long entries are historically fragile."
    if regime == "trending_bull" and side == "short":
        return "Momentum regime detected; shorts can be forced out before thesis confirmation."
    if regime == "trending_bear" and side == "long":
        return "Bear trend regime detected; long entries are vulnerable to continuation flushes."
    if regime == "volatile":
        return "Volatility regime detected; liquidation gaps compress and stop-loss assumptions decay quickly."
    return None


@router.post("/api/v1/risk-score", response_model=RiskResponse)
async def risk_score(query: TradeQuery):
    symbol = query.symbol.upper()
    side = query.side.lower()
    similar_count = database.count_similar(
        symbol, side, query.leverage, query.funding_rate, query.rsi, query.fear_greed
    )
    with database.get_db() as db:
        total_count = db.execute(
            "SELECT COUNT(*) FROM liquidations WHERE symbol = ? AND side = ?",
            (symbol, side),
        ).fetchone()[0]
    probability = min(1.0, max(0.0, similar_count / max(total_count, 1)))
    confidence = "low" if similar_count < 10 else "medium" if similar_count < 50 else "high"
    similar_events = database.get_similar_events(
        symbol, side, query.leverage, query.funding_rate, query.rsi, query.fear_greed
    )
    median_hours, worst_hours = _time_metrics(similar_events)
    regime = await tagger.get_current_regime(symbol)
    factors = _risk_factors(query)
    warning = _regime_warning(regime["regime"], side)
    key = factors[0] if factors else "historical liquidation clustering"
    verdict = (
        f"Historical autopsy finds a {probability:.0%} liquidation probability for a {side} "
        f"{symbol} setup at {query.leverage}x. The dominant warning is: {key}. "
        f"Similar setups appeared {similar_count} times in the corpus, with {confidence} confidence."
    )
    database.insert_api_query(
        {
            "symbol": symbol,
            "side": side,
            "leverage": query.leverage,
            "funding_rate": query.funding_rate,
            "rsi": query.rsi,
            "fear_greed": query.fear_greed,
            "result_score": probability,
            "similar_events_found": similar_count,
        }
    )
    return RiskResponse(
        symbol=symbol,
        side=side,
        leverage=query.leverage,
        liquidation_probability=round(probability, 4),
        confidence=confidence,
        similar_events_found=similar_count,
        median_time_to_liquidation_hours=median_hours,
        worst_case_hours=worst_hours,
        top_risk_factors=factors,
        regime_warning=warning,
        verdict=verdict,
    )


@router.get("/api/v1/liquidations", response_model=list[LiquidationEvent])
def liquidations(
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    regime: Optional[str] = None,
    limit: int = Query(default=100, le=500, ge=1),
    offset: int = Query(default=0, ge=0),
):
    return database.get_liquidations(symbol, side, regime, limit, offset)


@router.get("/api/v1/liquidations/clusters", response_model=list[ClusterSummary])
def clusters():
    return database.get_clusters()


@router.get("/api/v1/liquidations/patterns", response_model=list[PatternEntry])
def patterns():
    entries = []
    for row in database.get_patterns():
        row["insight"] = INSIGHTS.get((row["regime"], row["side"]), "Recurring liquidation cluster with repeatable pre-trade risk markers.")
        entries.append(row)
    return entries


@router.get("/api/v1/regime/{symbol}", response_model=RegimeSnapshot)
async def regime(symbol: str):
    return await tagger.get_current_regime(symbol)


@router.get("/api/v1/stats")
def stats():
    return database.get_stats()


@router.get("/api/v1/leaderboard", response_model=list[PatternEntry])
def leaderboard():
    return patterns()
