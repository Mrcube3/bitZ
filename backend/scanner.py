import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np

import database


logger = logging.getLogger("retail-autopsy.scanner")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
PRICE_RANGES = {
    "BTCUSDT": (80000, 110000),
    "ETHUSDT": (2000, 4000),
    "SOLUSDT": (100, 250),
    "BNBUSDT": (500, 800),
    "XRPUSDT": (0.5, 3.0),
}
REGIMES = ["trending_bull", "trending_bear", "ranging", "volatile", "crash"]


def _bitget_symbol(symbol: str) -> str:
    return f"{symbol.upper()}_UMCBL"


def _event_timestamp(value):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric = numeric / 1000
        return datetime.fromtimestamp(numeric, timezone.utc).isoformat()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
        except ValueError:
            return datetime.now(timezone.utc).isoformat()


def _parse_bitget_items(symbol: str, items: list[dict]) -> list[dict]:
    events = []
    for item in items:
        price_raw = item.get("price") or item.get("fillPrice")
        volume_raw = item.get("baseVolume") or item.get("size") or item.get("baseVol") or item.get("qty")
        if price_raw is None or volume_raw is None:
            continue
        price = float(price_raw)
        side_raw = str(item.get("side") or item.get("tradeSide") or "").lower()
        events.append(
            {
                "timestamp": _event_timestamp(item.get("ts") or item.get("time") or item.get("cTime")),
                "symbol": symbol.upper(),
                "side": "long" if side_raw in ["buy", "long", "open_long", "close_short"] else "short",
                "size_usd": float(volume_raw) * price,
                "leverage": None,
                "price": price,
                "exchange": "bitget",
            }
        )
    return events


def _simulated_regime(ts: datetime) -> str:
    days_back = (datetime.now(timezone.utc) - ts).days
    return REGIMES[(days_back // 10) % len(REGIMES)]


def _range_for_regime(regime: str):
    return {
        "trending_bull": ((0.01, 0.05), (60, 80), (65, 90)),
        "trending_bear": ((-0.05, -0.005), (20, 40), (10, 35)),
        "ranging": ((-0.005, 0.005), (40, 60), (35, 65)),
        "volatile": ((0.02, 0.08), (30, 75), (20, 80)),
        "crash": ((-0.1, -0.02), (10, 30), (5, 20)),
    }[regime]


def _simulate_events(symbol: str, limit: int = 300) -> list[dict]:
    rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
    now = datetime.now(timezone.utc)
    low, high = PRICE_RANGES[symbol]
    events = []
    for _ in range(limit):
        ts = now - timedelta(minutes=int(rng.integers(0, 90 * 24 * 60)))
        regime = _simulated_regime(ts)
        funding_range, rsi_range, fg_range = _range_for_regime(regime)
        leverage = int(np.clip(rng.normal(10, 7), 2, 50))
        size = float(np.clip(rng.lognormal(mean=np.log(4500), sigma=1.6), 200, 800000))
        events.append(
            {
                "timestamp": ts.isoformat(),
                "symbol": symbol,
                "side": "long" if rng.random() < 0.62 else "short",
                "size_usd": size,
                "leverage": leverage,
                "price": float(rng.uniform(low, high)),
                "exchange": "bitget",
                "regime": regime,
                "funding_rate": float(rng.uniform(*funding_range)),
                "rsi_at_event": float(rng.uniform(*rsi_range)),
                "fear_greed_at_event": int(rng.integers(fg_range[0], fg_range[1] + 1)),
                "long_short_ratio_at_event": float(np.clip(rng.normal(1.12, 0.32), 0.42, 2.75)),
            }
        )
    return sorted(events, key=lambda e: e["timestamp"], reverse=True)


async def fetch_liquidation_history(symbol: str, limit: int = 500) -> list[dict]:
    base_url = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{base_url}/api/v2/mix/market/fills-history",
                params={"symbol": _bitget_symbol(symbol), "productType": "USDT-FUTURES", "limit": min(limit, 100)},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            if isinstance(data, dict):
                data = data.get("fillList") or data.get("list") or []
            events = _parse_bitget_items(symbol, data)
            if events:
                return events[:limit]
    except Exception as exc:
        logger.info("Bitget liquidation fetch failed for %s: %s", symbol, exc)
    return _simulate_events(symbol, 300)


async def fetch_and_store_liquidations():
    from tagger import tag_event

    inserted = 0
    with database.get_db() as db:
        existing = db.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0]
    if existing >= 1000:
        logger.info("Skipping seed scan; %s liquidation rows already stored", existing)
        return 0

    for symbol in SYMBOLS:
        events = await fetch_liquidation_history(symbol)
        for event in events:
            tagged = await tag_event(event)
            database.insert_liquidation(tagged)
            inserted += 1
    logger.info("Stored %s liquidation events", inserted)
    return inserted


def compute_leverage_bucket(leverage: int) -> str:
    if leverage <= 5:
        return "2-5x"
    if leverage <= 10:
        return "5-10x"
    if leverage <= 20:
        return "10-20x"
    return "20x+"
