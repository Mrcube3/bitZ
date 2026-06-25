import os
import sqlite3
from datetime import datetime, timezone


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_VERCEL = os.environ.get("VERCEL") == "1"
if IS_VERCEL:
    DB_PATH = "/tmp/autopsy.db"
else:
    DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "data", "autopsy.db"))


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS liquidations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size_usd REAL NOT NULL,
                leverage INTEGER,
                price REAL NOT NULL,
                exchange TEXT DEFAULT 'bitget',
                regime TEXT,
                funding_rate REAL,
                rsi_at_event REAL,
                fear_greed_at_event INTEGER,
                long_short_ratio_at_event REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS regime_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                regime TEXT NOT NULL,
                rsi REAL,
                macd_signal TEXT,
                funding_rate REAL,
                fear_greed INTEGER,
                long_short_ratio REAL,
                btc_dxy_correlation REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS api_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                leverage INTEGER NOT NULL,
                funding_rate REAL,
                rsi REAL,
                fear_greed INTEGER,
                result_score REAL NOT NULL,
                similar_events_found INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_liq_match ON liquidations(symbol, side, leverage, funding_rate, rsi_at_event, fear_greed_at_event)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_liq_filters ON liquidations(symbol, side, regime, timestamp)")
        db.commit()


def insert_liquidation(event: dict):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO liquidations (
                timestamp, symbol, side, size_usd, leverage, price, exchange, regime,
                funding_rate, rsi_at_event, fear_greed_at_event, long_short_ratio_at_event
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["timestamp"],
                event["symbol"],
                event["side"],
                event["size_usd"],
                event.get("leverage"),
                event["price"],
                event.get("exchange", "bitget"),
                event.get("regime"),
                event.get("funding_rate"),
                event.get("rsi_at_event"),
                event.get("fear_greed_at_event"),
                event.get("long_short_ratio_at_event"),
            ),
        )
        db.commit()


def insert_regime_snapshot(snapshot: dict):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO regime_snapshots (
                timestamp, symbol, regime, rsi, macd_signal, funding_rate,
                fear_greed, long_short_ratio, btc_dxy_correlation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.get("timestamp", datetime.now(timezone.utc).isoformat()),
                snapshot["symbol"],
                snapshot["regime"],
                snapshot.get("rsi"),
                snapshot.get("macd_signal"),
                snapshot.get("funding_rate"),
                snapshot.get("fear_greed"),
                snapshot.get("long_short_ratio"),
                snapshot.get("btc_dxy_correlation"),
            ),
        )
        db.commit()


def insert_api_query(query: dict):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO api_queries (
                symbol, side, leverage, funding_rate, rsi, fear_greed,
                result_score, similar_events_found
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query["symbol"],
                query["side"],
                query["leverage"],
                query.get("funding_rate"),
                query.get("rsi"),
                query.get("fear_greed"),
                query["result_score"],
                query.get("similar_events_found"),
            ),
        )
        db.commit()


def _rows(sql: str, params=()):
    with get_db() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def get_liquidations(symbol=None, side=None, regime=None, limit=100, offset=0):
    clauses = []
    params = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if side:
        clauses.append("side = ?")
        params.append(side.lower())
    if regime:
        clauses.append("regime = ?")
        params.append(regime)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([limit, offset])
    return _rows(
        f"""
        SELECT id, timestamp, symbol, side, size_usd, leverage, price, regime,
               funding_rate, rsi_at_event, fear_greed_at_event
        FROM liquidations
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )


def get_stats():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*), COALESCE(SUM(size_usd), 0) FROM liquidations").fetchone()
        queries_today = db.execute(
            "SELECT COUNT(*) FROM api_queries WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        top_symbols = [
            dict(row)
            for row in db.execute(
                """
                SELECT
                    symbol,
                    COUNT(*) AS total_liquidations,
                    COALESCE(SUM(size_usd), 0) AS volume_usd,
                    ROUND(100.0 * SUM(CASE WHEN side = 'long' THEN 1 ELSE 0 END) / COUNT(*), 2) AS long_pct,
                    ROUND(100.0 * SUM(CASE WHEN side = 'short' THEN 1 ELSE 0 END) / COUNT(*), 2) AS short_pct
                FROM liquidations
                GROUP BY symbol
                ORDER BY total_liquidations DESC, volume_usd DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        for item in top_symbols:
            regime = db.execute(
                """
                SELECT regime, COUNT(*) AS c
                FROM liquidations
                WHERE symbol = ?
                GROUP BY regime
                ORDER BY c DESC
                LIMIT 1
                """,
                (item["symbol"],),
            ).fetchone()
            item["most_dangerous_regime"] = regime["regime"] if regime else "unknown"
            item["risk_level"] = min(1.0, item["total_liquidations"] / max(total[0], 1) * 2.5)

        by_regime = {
            row["regime"] or "unknown": row["count"]
            for row in db.execute(
                "SELECT COALESCE(regime, 'unknown') AS regime, COUNT(*) AS count FROM liquidations GROUP BY COALESCE(regime, 'unknown')"
            ).fetchall()
        }
        by_hour = [0.0 for _ in range(24)]
        for row in db.execute(
            "SELECT CAST(strftime('%H', timestamp) AS INTEGER) AS hour, COALESCE(SUM(size_usd), 0) AS volume FROM liquidations GROUP BY hour"
        ).fetchall():
            if row["hour"] is not None:
                by_hour[int(row["hour"])] = float(row["volume"])

        return {
            "total_count": total[0],
            "total_volume_usd": total[1],
            "api_queries_today": queries_today,
            "top_symbols": top_symbols,
            "by_regime": by_regime,
            "by_hour": by_hour,
        }


def _leverage_bucket_case():
    return """
    CASE
      WHEN leverage <= 5 THEN '2-5x'
      WHEN leverage <= 10 THEN '5-10x'
      WHEN leverage <= 20 THEN '10-20x'
      ELSE '20x+'
    END
    """


def get_patterns():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0] or 1
        rows = db.execute(
            f"""
            SELECT
                COALESCE(regime, 'unknown') AS regime,
                side,
                {_leverage_bucket_case()} AS leverage_bucket,
                AVG(funding_rate) AS avg_funding,
                AVG(rsi_at_event) AS avg_rsi,
                COUNT(*) AS count,
                ROUND(CAST(COUNT(*) AS REAL) / ?, 4) AS pct_of_total
            FROM liquidations
            GROUP BY COALESCE(regime, 'unknown'), side, leverage_bucket
            ORDER BY count DESC
            LIMIT 10
            """,
            (total,),
        ).fetchall()
        return [dict(row) | {"rank": i + 1} for i, row in enumerate(rows)]


def get_clusters():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0] or 1
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT
                    COALESCE(regime, 'unknown') AS regime,
                    side,
                    COUNT(*) AS total_liquidations,
                    ROUND(AVG(COALESCE(leverage, 0)), 2) AS avg_leverage,
                    AVG(funding_rate) AS avg_funding_rate,
                    AVG(rsi_at_event) AS avg_rsi,
                    ROUND(AVG(size_usd), 2) AS avg_size_usd,
                    ROUND(CAST(COUNT(*) AS REAL) / ?, 4) AS pct_of_total
                FROM liquidations
                GROUP BY COALESCE(regime, 'unknown'), side
                ORDER BY total_liquidations DESC
                """,
                (total,),
            ).fetchall()
        ]


def count_similar(symbol, side, leverage, funding_rate, rsi, fear_greed):
    where = ["symbol = ?", "side = ?", "leverage BETWEEN ? AND ?"]
    params = [symbol.upper(), side.lower(), max(0, leverage - 5), leverage + 5]
    if funding_rate is not None:
        where.append("funding_rate IS NOT NULL AND funding_rate BETWEEN ? AND ?")
        params.extend([funding_rate - 0.02, funding_rate + 0.02])
    if rsi is not None:
        where.append("rsi_at_event IS NOT NULL AND rsi_at_event BETWEEN ? AND ?")
        params.extend([rsi - 10, rsi + 10])
    if fear_greed is not None:
        where.append("fear_greed_at_event IS NOT NULL AND fear_greed_at_event BETWEEN ? AND ?")
        params.extend([fear_greed - 15, fear_greed + 15])
    with get_db() as db:
        return db.execute(f"SELECT COUNT(*) FROM liquidations WHERE {' AND '.join(where)}", params).fetchone()[0]


def get_similar_events(symbol, side, leverage, funding_rate, rsi, fear_greed, limit=250):
    where = ["symbol = ?", "side = ?", "leverage BETWEEN ? AND ?"]
    params = [symbol.upper(), side.lower(), max(0, leverage - 5), leverage + 5]
    if funding_rate is not None:
        where.append("funding_rate IS NOT NULL AND funding_rate BETWEEN ? AND ?")
        params.extend([funding_rate - 0.02, funding_rate + 0.02])
    if rsi is not None:
        where.append("rsi_at_event IS NOT NULL AND rsi_at_event BETWEEN ? AND ?")
        params.extend([rsi - 10, rsi + 10])
    if fear_greed is not None:
        where.append("fear_greed_at_event IS NOT NULL AND fear_greed_at_event BETWEEN ? AND ?")
        params.extend([fear_greed - 15, fear_greed + 15])
    params.append(limit)
    return _rows(
        f"SELECT timestamp FROM liquidations WHERE {' AND '.join(where)} ORDER BY timestamp ASC LIMIT ?",
        params,
    )
