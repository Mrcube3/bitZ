import os
from datetime import datetime, timezone

import httpx

import database


def _bitget_symbol(symbol: str) -> str:
    return f"{symbol.upper()}_UMCBL"


def compute_rsi(closes: list, period=14) -> float:
    if len(closes) <= period:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def classify_regime(rsi, funding_rate, fear_greed, price_change_pct) -> str:
    if price_change_pct is not None and price_change_pct < -10:
        return "crash"
    if rsi > 65 and funding_rate > 0.01:
        return "trending_bull"
    if rsi < 35 and funding_rate < -0.005:
        return "trending_bear"
    if 40 <= rsi <= 60 and abs(funding_rate) < 0.005:
        return "ranging"
    if abs(price_change_pct or 0) > 5:
        return "volatile"
    return "unknown"


def _fallback(symbol: str):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "regime": "unknown",
        "rsi": None,
        "macd_signal": None,
        "funding_rate": None,
        "fear_greed": None,
        "long_short_ratio": None,
        "btc_dxy_correlation": None,
    }


async def get_current_regime(symbol: str) -> dict:
    symbol = symbol.upper()
    base_url = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            candles_resp = await client.get(
                f"{base_url}/api/v2/mix/market/candles",
                params={"symbol": _bitget_symbol(symbol), "productType": "USDT-FUTURES", "granularity": "1H", "limit": 50},
            )
            candles_resp.raise_for_status()
            candle_data = candles_resp.json().get("data", [])
            closes = [float(c[4]) for c in candle_data if len(c) > 4]
            if len(closes) < 2:
                raise ValueError("not enough candles")
            rsi = compute_rsi(closes)
            price_change_pct = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] else 0

            funding = 0.0
            funding_resp = await client.get(
                f"{base_url}/api/v2/mix/market/current-fund-rate",
                params={"symbol": _bitget_symbol(symbol), "productType": "USDT-FUTURES"},
            )
            if funding_resp.status_code == 200:
                data = funding_resp.json().get("data", {})
                if isinstance(data, list):
                    data = data[0] if data else {}
                funding = float(data.get("fundingRate") or data.get("fundRate") or 0)

            fear_greed = None
            fg_resp = await client.get("https://api.alternative.me/fng/", params={"limit": 1})
            if fg_resp.status_code == 200:
                fg_data = fg_resp.json().get("data", [])
                if fg_data:
                    fear_greed = int(fg_data[0]["value"])

            long_short_ratio = None
            ratio_resp = await client.get(
                f"{base_url}/api/v2/mix/market/long-short-account-ratio",
                params={"symbol": _bitget_symbol(symbol), "productType": "USDT-FUTURES", "period": "1H"},
            )
            if ratio_resp.status_code == 200:
                ratio_data = ratio_resp.json().get("data", [])
                if isinstance(ratio_data, list) and ratio_data:
                    latest = ratio_data[-1]
                    long_short_ratio = float(latest.get("longShortRatio") or latest.get("ratio") or 0)

            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "regime": classify_regime(rsi, funding, fear_greed, price_change_pct),
                "rsi": rsi,
                "macd_signal": "bullish" if closes[-1] >= sum(closes[-12:]) / min(12, len(closes)) else "bearish",
                "funding_rate": funding,
                "fear_greed": fear_greed,
                "long_short_ratio": long_short_ratio,
                "btc_dxy_correlation": None,
            }
            database.insert_regime_snapshot(snapshot)
            return snapshot
    except Exception:
        return _fallback(symbol)


async def tag_event(event: dict) -> dict:
    if event.get("regime") is not None:
        return event
    result = await get_current_regime(event["symbol"])
    event["regime"] = result["regime"]
    event["funding_rate"] = result["funding_rate"]
    event["rsi_at_event"] = result["rsi"]
    event["fear_greed_at_event"] = result["fear_greed"]
    event["long_short_ratio_at_event"] = result["long_short_ratio"]
    return event
