# Retail Autopsy Engine 🔍

> **Know why retail gets liquidated. Before your agent does too.**

A liquidation intelligence layer for trading agents. Scans historical liquidation-like market events, tags them with regime context, and turns repeated failure patterns into an API that can be queried *before* a trade is opened.

The dashboard gives humans a forensic view of the corpus — symbol risk, liquidation clusters, recurring pattern cards, and a risk scanner. The API gives agents a compact pre-trade risk score with confidence, comparable event count, time-to-liquidation profile, and plain-English factors.

---

## Features

- **Pre-Trade Risk Scoring** — POST a proposed trade setup, get back a liquidation probability with similar-event count, median/worst-case time-to-liq, risk factors, and regime warnings.
- **Liquidation Feed** — Filterable event stream by symbol, side, and regime.
- **Pattern Graveyard** — Top-10 recurring liquidation patterns ranked by frequency, each with funding/RSI context and a human-readable insight.
- **Regime Tagging** — Auto-classifies every event and the current market into `trending_bull`, `trending_bear`, `ranging`, `volatile`, or `crash`.
- **Dashboard** — Aggregate stats, hourly liquidation volume (UTC), regime breakdown, and a symbol leaderboard with risk levels.
- **Resilient Scanner** — Fetches live data from Bitget on startup, then every 30 minutes. If Bitget is unavailable, it generates realistic simulated events with the same statistical shape — the dashboard and API never sit empty.
- **Agent-Ready API** — Simple JSON endpoints, CORS enabled, zero auth. Drop the `/api/v1/risk-score` call into any trading bot.

---

## Architecture

```
┌─────────────┐     ┌──────────┐     ┌───────────┐     ┌──────────────────┐
│  Bitget API  │────▶│ Scanner  │────▶│  SQLite   │◀────│  FastAPI Server  │
│ (live data)  │     │ (30 min) │     │  (local)  │     │  (port 8000)     │
└─────────────┘     └──────────┘     └───────────┘     └───────┬──────────┘
                          ▲                                    │
                          │                                    ├── /api/v1/risk-score
                     ┌────┴────┐                               ├── /api/v1/liquidations
                     │ Regime  │                               ├── /api/v1/liquidations/clusters
                     │ Tagger  │                               ├── /api/v1/liquidations/patterns
                     └─────────┘                               ├── /api/v1/regime/{symbol}
                                                               ├── /api/v1/stats
                                                               └── / (Static Dashboard)
```

- **Scanner** — Runs on startup + every 30 min via APScheduler. Pulls the latest fills from Bitget `/api/v2/mix/market/fills-history`. Falls back to synthetic events if the API is unreachable.
- **Regime Tagger** — Classifies each event using RSI (14), funding rate, Fear & Greed Index, and price change. Tags the current market regime for live endpoint queries.
- **SQLite DB** — Stored locally at `data/autopsy.db`. Three tables: `liquidations`, `regime_snapshots`, `api_queries`.
- **FastAPI** — Serves the REST API and static frontend files on a single port.

---

## Quick Start

### Prerequisites
- Python 3.9+
- (Optional) Bitget API keys for live data — if missing, simulated data is used automatically.

### Setup & Run

```bash
git clone <repo-url>
cd retail-autopsy-engine

cp .env.example .env
# Edit .env with your Bitget API keys (optional)

./start.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** for the dashboard, or hit the API directly.

---

## API Reference

All endpoints return JSON. CORS is enabled for all origins.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health + event count |
| `POST` | `/api/v1/risk-score` | Pre-trade liquidation probability |
| `GET` | `/api/v1/liquidations` | Filterable event feed (`?symbol=&side=&regime=&limit=&offset=`) |
| `GET` | `/api/v1/liquidations/clusters` | Cluster summaries by regime + side |
| `GET` | `/api/v1/liquidations/patterns` | Top-10 recurring patterns with insights |
| `GET` | `/api/v1/regime/{symbol}` | Current regime snapshot for a symbol |
| `GET` | `/api/v1/stats` | Dashboard aggregate stats |
| `GET` | `/api/v1/leaderboard` | Alias for `liquidations/patterns` |

### Example: Pre-Trade Risk Score

```bash
curl -X POST http://localhost:8000/api/v1/risk-score \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "long",
    "leverage": 20,
    "funding_rate": 0.035,
    "rsi": 74,
    "fear_greed": 82,
    "long_short_ratio": 1.24
  }'
```

Response:

```json
{
  "symbol": "BTCUSDT",
  "side": "long",
  "leverage": 20,
  "liquidation_probability": 0.2847,
  "confidence": "medium",
  "similar_events_found": 34,
  "median_time_to_liquidation_hours": 2.41,
  "worst_case_hours": 0.08,
  "top_risk_factors": [
    "Extreme leverage (20x+) - top liquidation tier",
    "RSI overbought - momentum exhaustion risk",
    "Extreme positive funding - longs overpaying",
    "Peak greed - historically precedes corrections"
  ],
  "regime_warning": "Volatility regime detected; liquidation gaps compress and stop-loss assumptions decay quickly.",
  "verdict": "Historical autopsy finds a 28% liquidation probability for a long BTCUSDT setup at 20x. The dominant warning is: Extreme leverage (20x+) - top liquidation tier. Similar setups appeared 34 times in the corpus, with medium confidence."
}
```

**Request Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbol` | string | ✅ | Trading pair (e.g. `BTCUSDT`, `ETHUSDT`) |
| `side` | string | ✅ | `long` or `short` |
| `leverage` | int | ✅ | 1-125x |
| `funding_rate` | float | ❌ | Current funding rate (e.g. 0.035 = 3.5%) |
| `rsi` | float | ❌ | RSI(14) value |
| `fear_greed` | int | ❌ | Fear & Greed Index (0-100) |
| `long_short_ratio` | float | ❌ | Long/short position ratio |

---

## Dashboard

The frontend (`frontend/`) is a single-page dark-themed dashboard with:

- **Market tickers** — Live BTC/ETH/SOL prices from CoinGecko
- **Dashboard** — Total liquidations, volume, most dangerous setup, API queries today, hourly volume chart, regime breakdown donut, and a symbol risk table
- **Liquidation Feed** — Filterable, paginated event stream with auto-refresh
- **Pattern Graveyard** — Top-10 deadliest liquidation patterns, each displayed as a tombstone card with funding, RSI, count, and a hard-earned insight
- **Risk Scanner** — Interactive form to run trade autopsies with animated probability bars and typewriter verdicts
- **API Docs** — Built-in reference with copyable curl examples

---

## Integrate Into Your Trading Agent

```python
import httpx


async def pre_trade_risk_check(setup):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "http://localhost:8000/api/v1/risk-score",
            json={
                "symbol": setup["symbol"],
                "side": setup["side"],
                "leverage": setup["leverage"],
                "funding_rate": setup.get("funding_rate"),
                "rsi": setup.get("rsi"),
                "fear_greed": setup.get("fear_greed"),
                "long_short_ratio": setup.get("long_short_ratio"),
            },
        )
        response.raise_for_status()
        risk = response.json()
        return risk["liquidation_probability"] < 0.35, risk
```

Use the verdict, risk factors, and regime warning fields as input for your agent's decision prompt. The score is deliberately conservativ e — it answers *"have setups like this been repeatedly punished?"*, not *"will this trade win?"*.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BITGET_API_KEY` | — | Bitget API key |
| `BITGET_SECRET_KEY` | — | Bitget API secret |
| `BITGET_PASSPHRASE` | — | Bitget API passphrase |
| `BITGET_BASE_URL` | `https://api.bitget.com` | Bitget API base URL |
| `PORT` | `8000` | Server port |

Without Bitget keys, the scanner falls back to simulated data — 300 synthetic events per symbol with realistic distributions for price, leverage, funding, RSI, and Fear & Greed.

---

## Project Structure

```
retail-autopsy-engine/
├── backend/
│   ├── main.py          # FastAPI app, scheduler, static mount
│   ├── router.py        # All API endpoints + risk score logic
│   ├── database.py      # SQLite queries, tables, indexes
│   ├── models.py        # Pydantic request/response models
│   ├── scanner.py       # Bitget fetcher + fallback simulator
│   ├── tagger.py        # Regime classification engine
│   └── requirements.txt
├── frontend/
│   ├── index.html       # SPA layout (5 pages)
│   ├── app.js           # Dashboard logic, Chart.js, API calls
│   └── style.css        # Dark theme, animations, tombstone cards
├── data/                # SQLite database (gitignored)
├── .env                 # Local config (gitignored)
├── .env.example         # Template for environment variables
├── start.sh             # One-command startup script
└── README.md
```

---

## Technical Details

- **Similarity matching** — Queries match on symbol, side, leverage (±5x), funding rate (±2%), RSI (±10), and Fear & Greed (±15). The probability is the ratio of matched events to total events for that symbol/side.
- **Regime classification logic** (`tagger.py:classify_regime`):
  - `crash` — price drop > 10%
  - `trending_bull` — RSI > 65, funding > 0.01
  - `trending_bear` — RSI < 35, funding < -0.005
  - `ranging` — RSI 40-60, near-zero funding
  - `volatile` — price swing > 5% (catch-all)
- **Simulation** — Uses numpy with deterministic seeds per symbol. Leverage follows a clipped normal (μ=10, σ=7), size follows a lognormal distribution, and each regime has its own realistic ranges for funding, RSI, and Fear & Greed.

---

## Built For

**Bitget AI Hackathon S1 — Track 2: Trading Infra**

The problem: trading agents execute thousands of setups, but they lack operational memory of what gets liquidated. This engine fills that gap — a lightweight, self-contained intelligence layer that any agent can query.
# bitZ
# bitZ
