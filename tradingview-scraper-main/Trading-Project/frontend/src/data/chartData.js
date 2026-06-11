// API base URL – the FastAPI backend
const API_BASE = "http://localhost:8000/api";

// ── Initial candle budget ────────────────────────────────────────────────────
// Total candles to load across ALL panes on first paint. Callers divide this
// by pane count (e.g. 4 panes → 250 each) so charts appear instantly.
export const INITIAL_CANDLE_BUDGET = 1000;

// Symbol config for the 7 major forex pairs (price display + symbolInfo)
const SYMBOL_CONFIG = {
  'EURUSD': { basePrice: 1.08,   volatility: 0.005, name: 'EUR / USD', exchange: 'OANDA', type: 'Forex', currency: 'USD' },
  'XAUUSD': { basePrice: 2320.0, volatility: 15.0,  name: 'Gold / USD', exchange: 'OANDA', type: 'Commodity', currency: 'USD' },
};


// Timeframe config: bars to generate, interval in minutes
const TF_CONFIG = {
  '1m':  { bars: 500, intervalMin: 1, useTimestamp: true },
  '5m':  { bars: 500, intervalMin: 5, useTimestamp: true },
  '15m': { bars: 400, intervalMin: 15, useTimestamp: true },
  '1h':  { bars: 300, intervalMin: 60, useTimestamp: true },
  '4h':  { bars: 250, intervalMin: 240, useTimestamp: true },
  '1d':  { bars: 300, intervalMin: 1440, useTimestamp: false },
  '1w':  { bars: 200, intervalMin: 10080, useTimestamp: false },
  '1M':  { bars: 120, intervalMin: 43200, useTimestamp: false },
};

const candleCache = new Map();
const activeRequests = new Map();
const CACHE_TTL_MS = 30000; // 30 seconds — server refreshes every 5s, client caches longer

// ── Hot candle store ─────────────────────────────────────────────────────────
// Session-lifetime Map (no TTL). Keyed by "symbol-timeframe".
// Entries: { data: {candleData, volumeData}, isComplete: bool }
// isComplete=false → only the initial budget slice is cached.
// isComplete=true  → full history is cached; repeat visits are instant.
const hotCandleStore = new Map();

/**
 * fetchInitialCandles
 * ───────────────────
 * Returns exactly `budget` recent candles for the chart's first paint.
 * Hits the hot-store first (O(1), zero network), then falls back to the API.
 * Stores the result in the hot-store with isComplete=false.
 *
 * @param {string} symbol
 * @param {string} timeframe
 * @param {number} budget  – per-pane slice of INITIAL_CANDLE_BUDGET
 */
export async function fetchInitialCandles(symbol, timeframe, budget) {
  const hotKey = `${symbol}-${timeframe}`;
  const hit = hotCandleStore.get(hotKey);
  if (hit) {
    // Hot cache hit: return immediately (instant render)
    return hit.data;
  }

  // Cache miss: fetch the initial slice from the API
  const data = await fetchLiveCandles(symbol, timeframe, budget);
  hotCandleStore.set(hotKey, { data, isComplete: false });
  return data;
}

/**
 * fetchFullHistory
 * ────────────────
 * Fetches the complete candle history from the database (at normal speed).
 * Called in the background after the chart has already painted its initial slice.
 * Promotes the hot-store entry to isComplete=true so future visits are instant.
 *
 * @param {string} symbol
 * @param {string} timeframe
 * @param {number} fullCount – total candles to load (from TF_CANDLE_COUNT)
 */
export async function fetchFullHistory(symbol, timeframe, fullCount) {
  const data = await fetchLiveCandles(symbol, timeframe, fullCount);
  // Promote the hot-store entry regardless of whether it existed before
  hotCandleStore.set(`${symbol}-${timeframe}`, { data, isComplete: true });
  return data;
}

/**
 * clearHotStore
 * ─────────────
 * Evict all hot-store entries (e.g. after a hard refresh button). Exported so
 * ChartPage can call it from the toolbar Refresh button if needed.
 */
export function clearHotStore() {
  hotCandleStore.clear();
}

export async function fetchLiveCandles(symbol, timeframe = "1d", candles = 1000, endTime = null) {
  const cacheKey = `${symbol}-${timeframe}-${candles}-${endTime || 'latest'}`;
  const now = Date.now();

  // 1. Check cache first
  const cached = candleCache.get(cacheKey);
  // For small live tick polls (candles <= 10), use a much shorter TTL to ensure fresh data
  const ttl = candles <= 10 ? 2000 : CACHE_TTL_MS;
  if (cached && (now - cached.timestamp < ttl)) {
    return cached.data;
  }

  // 2. Check if there's an active request in progress
  if (activeRequests.has(cacheKey)) {
    return activeRequests.get(cacheKey);
  }

  const { exchange, tvSymbol } = resolveSymbol(symbol);
  
  // Create the fetch promise
  const fetchPromise = (async () => {
    try {
      let url = `${API_BASE}/ohlc?exchange=${exchange}&symbol=${tvSymbol}&timeframe=${timeframe}&candles=${candles}`;
      if (endTime) {
        url += `&end_time=${endTime}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error(`OHLC request failed: ${res.status}`);
      const json = await res.json();
      
      // Backend returns status='loading' when initial gap-fill is still in progress
      if (json.status === 'loading') {
        throw new Error('initial_load');
      }
      
      const result = { candleData: json.candleData || [], volumeData: json.volumeData || [] };
      
      // Store in cache
      candleCache.set(cacheKey, {
        timestamp: Date.now(),
        data: result
      });
      
      return result;
    } catch (err) {
      console.error("[API] fetchLiveCandles error:", err);
      throw err;  // Re-throw so ChartWidget can distinguish between errors and empty data
    } finally {
      // Clean up active request when done
      activeRequests.delete(cacheKey);
    }
  })();

  activeRequests.set(cacheKey, fetchPromise);
  return fetchPromise;
}

export async function fetchIndicators(symbol, timeframe = "1d", indicators = ["RSI"]) {
  const { exchange, tvSymbol } = resolveSymbol(symbol);
  try {
    const res = await fetch(
      `${API_BASE}/indicators?exchange=${exchange}&symbol=${tvSymbol}&timeframe=${timeframe}&indicators=${indicators.join(",")}`
    );
    if (!res.ok) throw new Error(`Indicator request failed: ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error("[API] fetchIndicators error:", err);
    return { status: "failed", data: {} };
  }
}

export async function fetchWatchlist() {
  try {
    const res = await fetch(`${API_BASE}/watchlist`);
    if (!res.ok) throw new Error(`Watchlist request failed: ${res.status}`);
    const json = await res.json();
    return json.data || [];
  } catch (err) {
    console.error("[API] fetchWatchlist error:", err);
    return null; // return null to use a fallback if desired
  }
}

function resolveSymbol(symbol) {
  // All forex pairs route through OANDA using the symbol as-is
  const config = SYMBOL_CONFIG[symbol];
  const exchange = config?.exchange || 'OANDA';
  return { exchange, tvSymbol: symbol };
}

function generateCandlestickData(symbol = 'AAPL', days = 300, timeframe = '1d') {
  const config = SYMBOL_CONFIG[symbol] || { basePrice: 100, volatility: 2 };
  const tfConfig = TF_CONFIG[timeframe] || TF_CONFIG['1d'];
  const bars = tfConfig.bars;
  const intervalMin = tfConfig.intervalMin;
  const useTimestamp = tfConfig.useTimestamp;
  const isCrypto = symbol === 'BTCUSD' || symbol === 'ETHUSD';
  const isForex = symbol === 'EURUSD';
  const decimals = isForex ? 5 : 2;

  let { basePrice, volatility } = config;

  // Scale volatility by timeframe
  const tfVolScale = Math.sqrt(intervalMin / 1440);
  volatility = volatility * (tfVolScale || 1);

  const data = [];
  const volumeData = [];
  let currentPrice = basePrice;

  const now = new Date();
  // Calculate start time
  const totalMinutes = bars * intervalMin;
  const startTime = new Date(now.getTime() - totalMinutes * 60000);

  // Trend phases
  const trendPhases = [];
  let remaining = bars;
  while (remaining > 0) {
    const len = Math.min(Math.floor(Math.random() * 40) + 10, remaining);
    const dir = Math.random() > 0.45 ? 1 : -1;
    const str = (Math.random() * 0.3 + 0.1) * dir;
    trendPhases.push({ len, str });
    remaining -= len;
  }

  let phaseIdx = 0, phaseCnt = 0;

  for (let i = 0; i < bars; i++) {
    const barTime = new Date(startTime.getTime() + i * intervalMin * 60000);

    // Skip weekends for non-crypto
    if (!isCrypto && !useTimestamp) {
      const dow = barTime.getDay();
      if (dow === 0 || dow === 6) continue;
    }

    const phase = trendPhases[phaseIdx] || { len: 1, str: 0 };
    phaseCnt++;
    if (phaseCnt >= phase.len && phaseIdx < trendPhases.length - 1) {
      phaseIdx++; phaseCnt = 0;
    }

    const trendBias = phase.str * volatility * 0.15;
    const noise = (Math.random() - 0.5) * volatility * 2;
    const momentum = data.length > 1 ? (data[data.length - 1].close - data[data.length - 1].open) * 0.15 : 0;
    const change = trendBias + noise + momentum;

    const open = currentPrice;
    const close = open + change;
    const highExtra = Math.abs(change) * (Math.random() * 0.8 + 0.2) + volatility * Math.random() * 0.5;
    const lowExtra = Math.abs(change) * (Math.random() * 0.8 + 0.2) + volatility * Math.random() * 0.5;
    const high = Math.max(open, close) + highExtra;
    const low = Math.min(open, close) - lowExtra;

    const baseVolume = isCrypto ? 25000 : 45000000;
    const volMult = 0.5 + Math.random() * 1.5 + Math.abs(change) / volatility * 0.5;
    const volume = Math.floor(baseVolume * volMult * (tfVolScale || 1));

    let time;
    if (useTimestamp) {
      time = Math.floor(barTime.getTime() / 1000);
    } else {
      const y = barTime.getFullYear();
      const m = String(barTime.getMonth() + 1).padStart(2, '0');
      const d = String(barTime.getDate()).padStart(2, '0');
      time = `${y}-${m}-${d}`;
    }

    data.push({
      time,
      open: Number(open.toFixed(decimals)),
      high: Number(high.toFixed(decimals)),
      low: Number(low.toFixed(decimals)),
      close: Number(close.toFixed(decimals)),
    });

    volumeData.push({
      time,
      value: volume,
      color: close >= open ? 'rgba(38,166,154,0.5)' : 'rgba(239,83,80,0.5)',
    });

    currentPrice = close;
  }

  return { candleData: data, volumeData };
}

export const symbolInfo = Object.fromEntries(
  Object.entries(SYMBOL_CONFIG).map(([k, v]) => [k, { name: v.name, exchange: v.exchange, type: v.type, currency: v.currency }])
);

export const timeframes = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '30m', value: '30m' },
  { label: '1H', value: '1h' },
  { label: '4H', value: '4h' },
  { label: '1D', value: '1d' },
  { label: '1W', value: '1w' },
  { label: '1M', value: '1M' },
];



export default generateCandlestickData;

export class LivePriceFeed {
  static subscribers = new Set();
  static isPolling = false;
  static currentDelay = 5000;
  static consecutiveStalls = 0;
  static lastPrices = {};
  
  static subscribe(symbol, callback) {
    const entry = { symbol, callback };
    this.subscribers.add(entry);
    if (!this.isPolling) {
      this.isPolling = true;
      setTimeout(() => this.poll(), 100);
    }
    return () => {
      this.subscribers.delete(entry);
    };
  }

  static async poll() {
    if (!this.isPolling || this.subscribers.size === 0) {
      this.isPolling = false;
      return;
    }
    
    const activeSymbols = Array.from(new Set([...this.subscribers].map(s => s.symbol)));
    if (activeSymbols.length === 0) {
      setTimeout(() => this.poll(), this.currentDelay);
      return;
    }
    
    const symbolsQuery = activeSymbols.join(',');
    
    try {
      const start = performance.now();
      const res = await fetch(`${API_BASE}/latest-prices?symbols=${symbolsQuery}`);
      if (!res.ok) throw new Error('Network error');
      const data = await res.json();
      const end = performance.now();
      const latency = end - start;
      
      if (latency > 5000) {
        console.warn(`[LivePriceFeed] High latency detected: ${latency.toFixed(0)}ms. Overlapping polls may occur.`);
      }

      this.currentDelay = 5000;
      
      let allStalled = true;
      let hasData = false;
      
      if (data.status === 'success' && data.prices) {
        for (const sym in data.prices) {
          hasData = true;
          const current = data.prices[sym];
          const last = this.lastPrices[sym];
          if (!last || last.timestamp !== current.timestamp || last.price !== current.price) {
            allStalled = false;
          }
          this.lastPrices[sym] = current;
          
          for (const sub of this.subscribers) {
            // Need to match exactly, or match the symbol suffix (e.g. OANDA:EURUSD matches EURUSD)
            if (sub.symbol === sym || sub.symbol.split(':').pop() === sym.split(':').pop()) {
              sub.callback({
                 price: current.price,
                 timestamp: current.timestamp,
                 volume: current.volume,
                 color: current.color,
                 latency,
                 dataAge: data.serverTime - current.backend_generation_ts,
                 error: null
              });
            }
          }
        }
      }
      
      if (hasData && allStalled) {
        this.consecutiveStalls++;
        if (this.consecutiveStalls >= 5) {
          for (const sub of this.subscribers) {
             sub.callback({ error: 'STALLED' });
          }
        }
      } else {
        this.consecutiveStalls = 0;
      }

    } catch (e) {
      console.error('[LivePriceFeed] Fetch failed:', e);
      this.currentDelay = Math.min(this.currentDelay * 2, 60000); 
    }
    
    setTimeout(() => this.poll(), this.currentDelay);
  }
}

