import threading
import time
import json
import random
import string
import logging
import os
import re
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import websocket
from tqdm import tqdm

# ==========================================
# EXCEPTIONS
# ==========================================
class SessionExhausted(Exception): 
    """Raised when watchdog detects stall or heartbeat flood."""
    pass

class SessionError(Exception): 
    """Raised on WebSocket or protocol error."""
    pass

class FetchError(Exception): 
    """Raised when all retries fail."""
    pass

# ==========================================
# CLASS 1: TradingViewSession
# ==========================================
class TradingViewSession:
    """Manages a single ephemeral WebSocket session to TradingView."""
    
    def __init__(self, auth_token: str = "unauthorized_user_token", cookie: str | None = None, timeout: float = 8.0):
        self.auth_token = auth_token
        self.cookie = cookie
        self.timeout = timeout
        self.ws = None
        
        self.cs_id = "cs_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        self.qs_id = "qs_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        
        self.bars = []
        self._completed = False
        self._last_msg_time = time.time()
        self._consecutive_heartbeats = 0
        self._watchdog_thread = None
        self._stop_event = threading.Event()
        self._error = None

    def _pack(self, msg: dict) -> str:
        """Packs a dictionary into TradingView's ~m~ framed string format."""
        s = json.dumps(msg)
        return f"~m~{len(s)}~m~{s}"

    def connect(self) -> None:
        """Opens WebSocket, sends auth + session setup messages."""
        headers = {
            "Origin": "https://www.tradingview.com",
            "User-Agent": "Mozilla/5.0 (compatible)"
        }
        if self.cookie:
            headers["Cookie"] = f"sessionid={self.cookie}"
        
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect("wss://data.tradingview.com/socket.io/websocket", header=headers, timeout=self.timeout)
        except Exception as e:
            raise SessionError(f"Connection failed: {e}")

        # Step 1 — Set auth token
        self.ws.send(self._pack({"m": "set_auth_token", "p": [self.auth_token]}))
        # Step 2 — Create chart session
        self.ws.send(self._pack({"m": "chart_create_session", "p": [self.cs_id, ""]}))
        # Step 3 — Create quote session
        self.ws.send(self._pack({"m": "quote_create_session", "p": [self.qs_id]}))
        # Step 4 — Resolve symbol
        res_sym = '={"symbol":"EURUSD","adjustment":"splits","session":"extended"}'
        self.ws.send(self._pack({"m": "resolve_symbol", "p": [self.cs_id, "sds_sym_1", res_sym]}))

    def _watchdog_loop(self) -> None:
        """Daemon thread. Monitors session stall and exact heartbeat count."""
        while not self._stop_event.is_set():
            if self._completed:
                return
                
            elapsed = time.time() - self._last_msg_time
            if elapsed > self.timeout:
                self._error = SessionExhausted("Watchdog timeout: No valid data message arrived.")
                return
                
            if self._consecutive_heartbeats > 5:
                self._error = SessionExhausted("Watchdog threshold: > 5 consecutive heartbeats.")
                return
                
            time.sleep(1.0)

    def fetch_bars(self, symbol: str, timeframe: str, bar_count: int, from_ts: int) -> list[dict]:
        """Sends create_series, reads messages until completed or exhausted."""
        from_val = from_ts if from_ts else ""
        self.ws.send(self._pack({"m": "create_series", "p": [self.cs_id, "sds_1", "s1", "sds_sym_1", timeframe, bar_count, from_val]}))
        
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

        try:
            self.ws.settimeout(1.0)
            while not self._completed:
                if self._error:
                    raise self._error

                try:
                    raw = self.ws.recv()
                    self._parse_messages(raw)
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException:
                    raise SessionError("WebSocket closed prematurely")
        finally:
            self.disconnect()

        return self.bars

    def disconnect(self) -> None:
        """Stops watchdog, closes WebSocket cleanly."""
        self._stop_event.set()
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=2.0)
        if self.ws:
            self.ws.close()

    def _parse_messages(self, raw: str) -> None:
        """Splits ~m~ framed stream into individual JSON messages and extracts OHLCV."""
        pattern = r"~m~\d+~m~"
        parts = [p.strip() for p in re.split(pattern, raw) if p.strip()]
        
        for item in parts:
            if item.startswith("~h~"):
                self.ws.send(f"~m~{len(item)}~m~{item}")
                self._consecutive_heartbeats += 1
                continue
            
            try:
                data = json.loads(item)
            except json.JSONDecodeError:
                continue
                
            m = data.get("m")
            if m in ["timescale_update", "series_loading"]:
                self._last_msg_time = time.time()
                self._consecutive_heartbeats = 0
                
            if m == "series_completed":
                self._completed = True
                return
                
            if m == "timescale_update":
                p = data.get("p", [])
                if len(p) > 1:
                    sds_1 = p[1].get("sds_1", {})
                    if "s" in sds_1:
                        for entry in sds_1["s"]:
                            v = entry.get("v", [])
                            if len(v) >= 5:
                                bar = {
                                    "ts": int(v[0]),
                                    "open": float(v[1]),
                                    "high": float(v[2]),
                                    "low": float(v[3]),
                                    "close": float(v[4]),
                                    "volume": float(v[5]) if len(v) > 5 else 0.0
                                }
                                self.bars.append(bar)

# ==========================================
# CLASS 2: PaginationController
# ==========================================
class PaginationController:
    """Orchestrates multiple TradingViewSessions to step backwards through time."""
    
    def __init__(self, symbol: str, timeframe: str, target_start_ts: int, 
                 bars_per_session: int = 25000, session_delay: float = 2.0, 
                 auth_token: str = "unauthorized_user_token", cookie: str | None = None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.target_start_ts = target_start_ts
        self.bars_per_session = bars_per_session
        self.session_delay = session_delay
        self.auth_token = auth_token
        self.cookie = cookie
        
        self.chunks = []
        self.anchor_ts = None
        self.session_count = 0

    def _timeframe_to_seconds(self, tf: str) -> int:
        """Converts string timeframe to integer seconds."""
        mapping = {
            "1": 60, "5": 300, "15": 900, "60": 3600, 
            "240": 14400, "1D": 86400, "1W": 604800, "D": 86400, "W": 604800
        }
        return mapping.get(tf, 60)

    def _merge_chunks(self) -> pd.DataFrame:
        """Concatenates chunks, sorts, drops duplicates seamlessly."""
        if not self.chunks:
            return pd.DataFrame()
        flat = [item for sublist in self.chunks for item in sublist]
        df = pd.DataFrame(flat)
        df.drop_duplicates(subset=["ts"], keep="last", inplace=True)
        df.sort_values(by="ts", ascending=True, inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def run(self) -> dict:
        """Main entry point for extracting full backward history using chained chunks."""
        tf_secs = self._timeframe_to_seconds(self.timeframe)
        logger = logging.getLogger("PaginationController")
        
        reason = "target_reached"
        complete = True
        
        start_time = int(time.time())
        total_time_range = max(1, start_time - self.target_start_ts)
        pbar = tqdm(total=total_time_range, desc=f"TF {self.timeframe} Pagination", unit="s")
        last_progress_ts = start_time
        
        while self.anchor_ts is None or self.anchor_ts > self.target_start_ts:
            for attempt in range(4):
                try:
                    session = TradingViewSession(auth_token=self.auth_token, cookie=self.cookie)
                    session.connect()
                    
                    try:
                        # Use self.anchor_ts (which handles None -> "")
                        chunk = session.fetch_bars(self.symbol, self.timeframe, self.bars_per_session, self.anchor_ts)
                    except SessionExhausted as e:
                        logger.warning(f"Session exhausted at anchor {self.anchor_ts}: {e}")
                        chunk = session.bars
                        if not chunk:
                            if attempt < 3:
                                logger.info(f"Retrying empty exhaust ({attempt+1}/3)")
                                time.sleep(2.0)
                                continue
                            
                            total_bars = sum(len(c) for c in self.chunks)
                            logger.warning(
                                f"Pagination stopped: no more data available from provider at anchor {self.anchor_ts}. "
                                f"Total bars collected: {total_bars}. "
                                f"This may be a provider limit, not true historical exhaustion."
                            )
                            reason = "provider_limit"
                            complete = False
                            self.anchor_ts = 0
                            break
                    
                    self.session_count += 1
                    
                    if chunk:
                        self.chunks.append(chunk)
                        oldest_ts = min(b["ts"] for b in chunk)
                        logger.debug(f"Used {self.session_count} sessions. Anchor: {self.anchor_ts}. Oldest fetched: {oldest_ts} (Bars: {len(chunk)})")
                        
                        progress_step = last_progress_ts - oldest_ts
                        if progress_step > 0:
                            pbar.update(progress_step)
                            last_progress_ts = oldest_ts
                            
                        if self.anchor_ts is not None and oldest_ts >= self.anchor_ts:
                            logger.info("No backwards progress. Stopping.")
                            reason = "provider_limit"
                            complete = False
                            self.anchor_ts = 0  
                        else:
                            self.anchor_ts = oldest_ts - tf_secs
                    else:
                        logger.warning("Empty chunk received. Stopping pagination.")
                        reason = "provider_limit"
                        complete = False
                        self.anchor_ts = 0
                    
                    time.sleep(self.session_delay)
                    break 
                    
                except Exception as e:
                    if isinstance(e, FetchError):
                        raise e
                    if attempt < 3:
                        backoff = 2 ** (attempt + 1)
                        logger.warning(f"Error: {e}. Retrying via backoff in {backoff}s...")
                        time.sleep(backoff)
                    else:
                        reason = "error"
                        complete = False
                        self.anchor_ts = 0
                        break
        
        pbar.close()
        df = self._merge_chunks()
        return {
            "data": df,
            "complete": complete,
            "reason": reason
        }

# ==========================================
# CLASS 3: GapDetector
# ==========================================
class GapDetector:
    """Detects missing chunks between contiguous market hours."""
    
    def __init__(self, df: pd.DataFrame, timeframe_seconds: int, symbol: str = "EURUSD"):
        self.df = df
        self.timeframe_seconds = timeframe_seconds
        self.symbol = symbol
        self.gap_ranges = []
        self.total_missing_candles = 0

    def _is_market_closure(self, ts_before: int, ts_after: int) -> bool:
        """Returns True if the entire gap is exclusively inside known closures."""
        ts = ts_before + self.timeframe_seconds
        while ts < ts_after:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            is_weekend = False
            
            # Friday >= 22:00, all Saturday, Sunday < 22:00
            if dt.weekday() == 4 and dt.hour >= 22:
                is_weekend = True
            elif dt.weekday() == 5:
                is_weekend = True
            elif dt.weekday() == 6 and dt.hour < 22:
                is_weekend = True
                
            is_christmas = (dt.month == 12 and dt.day == 25)
            is_new_years = (dt.month == 1 and dt.day == 1)
            
            if not (is_weekend or is_christmas or is_new_years):
                return False
                
            ts += self.timeframe_seconds
            
        return True

    def detect(self) -> list[dict]:
        """Scans dataset identifying structural gaps outside natural market closures."""
        self.gap_ranges = []
        self.total_missing_candles = 0
        if self.df.empty:
            return []
            
        ts_array = self.df["ts"].values
        logger = logging.getLogger("GapDetector")
        
        for i in range(len(ts_array) - 1):
            t1 = ts_array[i]
            t2 = ts_array[i+1]
            delta = t2 - t1
            
            if delta == self.timeframe_seconds:
                continue
            if delta < self.timeframe_seconds:
                continue
                
            if delta > self.timeframe_seconds:
                if self._is_market_closure(int(t1), int(t2)):
                    continue
                
                miss_count = int((delta // self.timeframe_seconds) - 1)
                if miss_count > 0:
                    self.gap_ranges.append({"from_ts": int(t1), "to_ts": int(t2), "missing_count": miss_count})
                    self.total_missing_candles += miss_count
                    logger.info(f"Gap found: {t1} -> {t2} (Missing {miss_count} candles)")
                    
        return self.gap_ranges

    def summary(self) -> dict:
        """Returns statistical overview of structural dataset continuity."""
        return {
            "total_bars": len(self.df),
            "gaps_found": len(self.gap_ranges),
            "total_missing_candles": self.total_missing_candles,
            "gap_ranges": self.gap_ranges
        }

# ==========================================
# CLASS 4: GapRefetcher
# ==========================================
class GapRefetcher:
    """Opens targeted single sessions to close missing structural data segments."""
    
    def __init__(self, gaps: list[dict], symbol: str, timeframe: str, auth_token: str = "unauthorized_user_token"):
        self.gaps = gaps
        self.symbol = symbol
        self.timeframe = timeframe
        self.auth_token = auth_token

    def _fetch_gap(self, gap: dict) -> list[dict]:
        """Fetches up to 10000 bars strictly covering the gap window up to right edge."""
        from_ts = gap["from_ts"]
        to_ts = gap["to_ts"]
        
        logger = logging.getLogger("GapRefetcher")
        logger.info(f"Refetching gap range {from_ts} -> {to_ts}")
        
        session = TradingViewSession(auth_token=self.auth_token)
        session.connect()
        try:
            bars = session.fetch_bars(self.symbol, self.timeframe, 10000, to_ts)
        except Exception as e:
            logger.warning(f"Error refetching gap up to {to_ts}: {e}")
            bars = session.bars
            
        valid = [b for b in bars if from_ts <= b["ts"] <= to_ts]
        logger.info(f"Refetch extracted {len(valid)} interior boundary bars for target gap.")
        return valid

    def run(self) -> pd.DataFrame:
        """Executes targeted gap pulls consecutively with safety limits."""
        all_bars = []
        for gap in self.gaps:
            bars = self._fetch_gap(gap)
            all_bars.extend(bars)
            time.sleep(2.0)
            
        if not all_bars:
            return pd.DataFrame()
            
        df = pd.DataFrame(all_bars)
        df.drop_duplicates(subset=["ts"], keep="last", inplace=True)
        df.sort_values(by="ts", ascending=True, inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

# ==========================================
# CLASS 5: OHLCFetcher
# ==========================================
class OHLCFetcher:
    """Master orchestrator for the entire pagination, structural gap bridging and output IO."""
    
    def __init__(self, symbol: str = "EURUSD", timeframes: list[str] = None, 
                 years_back: int = 3, output_dir: str = "./ohlc_data", 
                 auth_token: str = "unauthorized_user_token", cookie: str | None = None):
                     
        self.symbol = symbol
        self.timeframes = timeframes if timeframes else ["1", "5", "15", "60"]
        self.years_back = years_back
        self.output_dir = output_dir
        self.auth_token = auth_token
        self.cookie = cookie

    def _validate(self, df: pd.DataFrame, timeframe: str) -> None:
        """Mathematically verifies deterministic structural rules over the full output."""
        if df.empty:
            raise ValueError(f"Validation failed: DF for {timeframe} is empty")
            
        if not df["ts"].is_monotonic_increasing or not df["ts"].is_unique:
            raise ValueError("Validation failed: ts column is not strictly monotonic increasing")
            
        if df[["open", "high", "low", "close"]].isnull().any().any():
            raise ValueError("Validation failed: NaN values found in essential columns")
            
        if not (df["high"] >= df["low"]).all():
            raise ValueError("Validation failed: structural logic high < low somewhere")
            
        if not (df["high"] >= df["open"]).all() or not (df["high"] >= df["close"]).all():
            raise ValueError("Validation failed: high boundary breached by structural body")
            
        if not (df["low"] <= df["open"]).all() or not (df["low"] <= df["close"]).all():
            raise ValueError("Validation failed: low boundary breached by structural body")

    def _save(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        """Guarantees pathing logic and physical local commits for CSV+Parquet outputs."""
        logger = logging.getLogger("OHLCFetcher")
        os.makedirs(self.output_dir, exist_ok=True)
        
        df["datetime_utc"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.strftime('%Y-%m-%d %H:%M:%S')
        csv_path = os.path.join(self.output_dir, f"{symbol}_{timeframe}.csv")
        pq_path = os.path.join(self.output_dir, f"{symbol}_{timeframe}.parquet")
        
        df.to_csv(csv_path, index=False)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, pq_path)
        logger.info(f"Successfully saved {len(df)} structural rows into {csv_path} and Parquet backend.")

    def load_data(self) -> dict[str, pd.DataFrame]:
        """Provides instant dataset access directly from permanent local memory, skipping live retrieval."""
        logger = logging.getLogger("OHLCFetcher")
        results = {}
        for tf in self.timeframes:
            pq_path = os.path.join(self.output_dir, f"{self.symbol}_{tf}.parquet")
            if os.path.exists(pq_path):
                df = pd.read_parquet(pq_path)
                logger.info(f"Loaded TF {tf} exclusively from memory ({len(df)} bars).")
                results[tf] = df
            else:
                logger.warning(f"No memory cache localized for TF {tf}. Consider running `run()` first.")
                results[tf] = pd.DataFrame()
        return results

    def run(self) -> dict[str, pd.DataFrame]:
        """Drives complete sequence across designated matrix targets."""
        logger = logging.getLogger("OHLCFetcher")
        results = {}
        base_target_ts = int(time.time() - (self.years_back * 365 * 24 * 3600))
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        for tf in self.timeframes:
            logger.info(f"=== Beginning matrix operation for Timeframe {tf} ===")
            
            existing_df = pd.DataFrame()
            pq_path = os.path.join(self.output_dir, f"{self.symbol}_{tf}.parquet")
            
            tf_target_ts = base_target_ts
            if os.path.exists(pq_path):
                existing_df = pd.read_parquet(pq_path)
                if not existing_df.empty:
                    tf_target_ts = int(existing_df["ts"].max())
                    logger.info(f"Detected existing file ({len(existing_df)} bars). Syncing target anchor to {tf_target_ts} to grow structurally.")
            
            controller = PaginationController(self.symbol, tf, tf_target_ts, 
                                              auth_token=self.auth_token, cookie=self.cookie)
            res = controller.run()
            df = res["data"]
            complete = res["complete"]
            reason = res["reason"]
            
            if df.empty:
                logger.warning(f"No structural boundaries produced for {tf}")
                results[tf] = df
                continue
                
            tf_secs = controller._timeframe_to_seconds(tf)
            detector = GapDetector(df, tf_secs, self.symbol)
            gaps = detector.detect()
            logger.info(f"Primary scan isolated {len(gaps)} potential structural gaps inside volume.")
            
            if gaps:
                refetcher = GapRefetcher(gaps, self.symbol, tf, self.auth_token)
                df_gap = refetcher.run()
                
                if not df_gap.empty:
                    df = pd.concat([df, df_gap])
                    df.drop_duplicates(subset=["ts"], keep="last", inplace=True)
                    df.sort_values(by="ts", ascending=True, inplace=True)
                    df.reset_index(drop=True, inplace=True)
                    
                det2 = GapDetector(df, tf_secs, self.symbol)
                gaps2 = det2.detect()
                if gaps2:
                    logger.warning(f"Secondary boundary validation flagged: {len(gaps2)} residual gaps persist.")
                else:
                    logger.info("Secondary boundary validation clean. Structural gaps eliminated.")

            if not existing_df.empty and not df.empty:
                df = pd.concat([existing_df, df])
                df.drop_duplicates(subset=["ts"], keep="last", inplace=True)
                df.sort_values(by="ts", ascending=True, inplace=True)
                df.reset_index(drop=True, inplace=True)
                logger.info(f"Incremental merge executed. Total dataset expanded to {len(df)} discrete bars.")
            elif not existing_df.empty and df.empty:
                df = existing_df
                logger.info(f"Zero novel intervals detected. Maintaining existing dataset of {len(df)} bars.")

            if not df.empty:
                self._validate(df, tf)
                
                earliest = df["ts"].iloc[0]
                if earliest > base_target_ts + (7 * 24 * 3600):
                    logger.warning(
                        f"Dataset truncated: earliest ts={earliest}, target={base_target_ts}. "
                        f"Likely provider limitation."
                    )

            diffs = df["ts"].diff()
            logger.info(f"Continuity check:\n{diffs.value_counts().head()}")
            
            self._save(df, self.symbol, tf)
            
            logger.info(f"[FINAL] TF={tf} | bars={len(df)} | complete={complete} | reason={reason}")
            results[tf] = df
            
        return results

# ==========================================
# ENTRY POINT Execution
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    from dotenv import load_dotenv
    load_dotenv()
    
    fetcher = OHLCFetcher(
        symbol="EURUSD",
        timeframes=["1", "5", "15", "60", "240", "1D", "1W"],
        years_back=2,
        output_dir="./ohlc_data_pro",
        auth_token=os.getenv("TV_JWT_TOKEN", "unauthorized_user_token"),
        cookie=os.getenv("TRADINGVIEW_COOKIE", "").strip()
    )

    # To grow with data, call fetcher.run()
    # To fetch exclusively from memory without live web connections:
    results = fetcher.run()

    for tf, df in results.items():
        if not df.empty:
            print(f"Timeframe {tf}: {len(df)} bars | "
                  f"From {df['datetime_utc'].iloc[0]} "
                  f"To {df['datetime_utc'].iloc[-1]}")
