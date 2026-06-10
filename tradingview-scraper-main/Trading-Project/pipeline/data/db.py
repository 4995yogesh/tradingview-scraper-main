"""
CandleDB — SQLite persistent store for OHLCV candle data.

Location: Trading-Project/data/candles.db
Thread-safe via WAL mode + thread-local connections.

Schema:
    candles(exchange, symbol, timeframe, ts INTEGER PK, open, high, low, close, volume)
"""

import sqlite3
import threading
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Database path: Trading-Project/data/candles.db ───────────────────────────
# Prefer env override (used by .exe builds), otherwise resolve relative to this file.
import os as _os
_env_db = _os.environ.get("CANDLE_DB_PATH")
DB_PATH = Path(_env_db) if _env_db else (Path(__file__).resolve().parent.parent.parent / "data" / "candles.db")


class CandleDB:
    """
    Persistent SQLite store for OHLCV candle data.

    Design choices:
    - WAL journal mode → concurrent reads without blocking writes
    - NORMAL synchronous mode → fast enough without risking corruption
    - Thread-local connections → FastAPI's thread pool workers each get their own conn
    - INSERT OR REPLACE primary key → idempotent upserts, no duplicates ever
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._setup_schema()

    # ── Connection management ─────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Return (or create) a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
            conn.row_factory = sqlite3.Row
            # Performance tuning
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-65536")   # 64 MB page cache
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456") # 256 MB memory-mapped I/O
            self._local.conn = conn
        return conn

    def _setup_schema(self):
        """Create tables and indices if they don't already exist."""
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
                exchange  TEXT    NOT NULL,
                symbol    TEXT    NOT NULL,
                timeframe TEXT    NOT NULL,
                ts        INTEGER NOT NULL,   -- Unix epoch seconds (always)
                open      REAL    NOT NULL,
                high      REAL    NOT NULL,
                low       REAL    NOT NULL,
                close     REAL    NOT NULL,
                volume    REAL    NOT NULL DEFAULT 0.0,
                PRIMARY KEY (exchange, symbol, timeframe, ts)
            );

            CREATE INDEX IF NOT EXISTS idx_candles_series
                ON candles (exchange, symbol, timeframe, ts);

            -- Track the last time each series was fully refreshed from TradingView
            CREATE TABLE IF NOT EXISTS refresh_log (
                exchange  TEXT NOT NULL,
                symbol    TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (exchange, symbol, timeframe)
            );
        """)
        conn.commit()
        logger.info("CandleDB ready → %s", self.db_path)

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert_candles(self, exchange: str, symbol: str, timeframe: str,
                       raw_candles: List[dict]):
        """
        Bulk insert-or-replace candles.

        Accepts dicts in the following formats:
          - Raw HistoricalFetcher: {'timestamp': <unix_float>, 'open': ..., ...}
          - Formatted storage:    {'time': <unix_int or 'YYYY-MM-DD'>, 'open': ..., ...}
          - Synthesized:          {'ts': <unix_int>, 'open': ..., ...}
        """
        if not raw_candles:
            return

        rows = []
        for c in raw_candles:
            # Support 'ts' (synthesized), 'timestamp' (HistoricalFetcher), 'time' (formatted)
            raw_ts = c.get("ts", c.get("timestamp", c.get("time", 0)))
            if isinstance(raw_ts, str):
                from datetime import datetime, timezone
                try:
                    dt = datetime.strptime(raw_ts, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    ts = int(dt.timestamp())
                except ValueError:
                    ts = int(float(raw_ts))
            else:
                ts = int(float(raw_ts))

            rows.append((
                exchange, symbol, timeframe, ts,
                float(c["open"]), float(c["high"]),
                float(c["low"]),  float(c["close"]),
                float(c.get("volume", 0.0)),
            ))

        conn = self._conn()
        with self._write_lock:
            conn.executemany(
                "INSERT OR REPLACE INTO candles "
                "(exchange, symbol, timeframe, ts, open, high, low, close, volume) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
        logger.debug("Upserted %d candles → %s:%s [%s]", len(rows), exchange, symbol, timeframe)

    def log_refresh(self, exchange: str, symbol: str, timeframe: str, fetched_at: int):
        """Record the wall-clock time of the last successful TV fetch."""
        conn = self._conn()
        with self._write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO refresh_log VALUES (?,?,?,?)",
                (exchange, symbol, timeframe, fetched_at),
            )
            conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_candles(self, exchange: str, symbol: str, timeframe: str,
                    count: Optional[int] = None,
                    end_ts: Optional[int] = None,
                    start_ts: Optional[int] = None) -> List[dict]:
        """
        Return candles sorted ASCENDING by timestamp.
        If count is given, returns the most recent N bars (tail of the series).
        If end_ts is given, excludes bars at or after end_ts (ceiling).
        If start_ts is given, excludes bars before start_ts (floor).
        """
        conn = self._conn()
        params: list = [exchange, symbol, timeframe]
        where = "WHERE exchange=? AND symbol=? AND timeframe=?"

        if end_ts is not None:
            where += " AND ts < ?"
            params.append(int(end_ts))

        if start_ts is not None:
            where += " AND ts >= ?"
            params.append(int(start_ts))

        limit_clause = f"LIMIT {int(count)}" if count else ""
        # DESC + LIMIT grabs the tail efficiently; we then reverse for ascending order
        sql = f"SELECT * FROM candles {where} ORDER BY ts DESC {limit_clause}"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_candles_since(self, exchange: str, symbol: str, timeframe: str,
                          since_ts: int) -> List[dict]:
        """
        Return all candles with ts >= since_ts, sorted ascending.
        Used by the delta-engine HTF synthesizer to read today's 1m/5m data.
        """
        return self.get_candles(exchange, symbol, timeframe, start_ts=since_ts)

    def get_latest_ts(self, exchange: str, symbol: str, timeframe: str) -> Optional[int]:
        """Most recent candle Unix timestamp, or None if no data exists."""
        row = self._conn().execute(
            "SELECT MAX(ts) FROM candles WHERE exchange=? AND symbol=? AND timeframe=?",
            (exchange, symbol, timeframe),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def get_oldest_ts(self, exchange: str, symbol: str, timeframe: str) -> Optional[int]:
        """Oldest candle Unix timestamp, or None if no data exists."""
        row = self._conn().execute(
            "SELECT MIN(ts) FROM candles WHERE exchange=? AND symbol=? AND timeframe=?",
            (exchange, symbol, timeframe),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def count(self, exchange: str, symbol: str, timeframe: str) -> int:
        """Number of stored candles for a particular series."""
        row = self._conn().execute(
            "SELECT COUNT(*) FROM candles WHERE exchange=? AND symbol=? AND timeframe=?",
            (exchange, symbol, timeframe),
        ).fetchone()
        return row[0] if row else 0

    def series_summary(self) -> List[dict]:
        """Return a summary of all stored series (for diagnostics)."""
        conn = self._conn()
        rows = conn.execute("""
            SELECT exchange, symbol, timeframe,
                   COUNT(*) AS candle_count,
                   MIN(ts)  AS oldest_ts,
                   MAX(ts)  AS newest_ts
            FROM candles
            GROUP BY exchange, symbol, timeframe
            ORDER BY exchange, symbol, timeframe
        """).fetchall()
        return [dict(r) for r in rows]


# ── Module-level singleton ────────────────────────────────────────────────────
candle_db = CandleDB()
