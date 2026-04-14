/**
 * swingLevels.js
 * ──────────────
 * Pure utility functions for multi-timeframe swing level detection.
 * No React, no side effects — fully testable in isolation.
 *
 * Ported from Pine Script "Swing Levels" indicator by LeviathanCapital.
 * Pivot rule: high[i] > high[i-1] AND high[i] > high[i+1]  → swing high
 *             low[i]  < low[i-1]  AND low[i]  < low[i+1]   → swing low
 */

// ── Timeframe definitions ─────────────────────────────────────────────────────

/** Seconds per bar for each supported timeframe */
export const TF_SECONDS = {
  '1m':  60,
  '5m':  300,
  '15m': 900,
  '30m': 1800,
  '1h':  3600,
  '4h':  14400,
  '1d':  86400,
  '1w':  604800,
};

/** TradingView-style display labels */
export const TF_LABELS = {
  '1m': '1M', '5m': '5M', '15m': '15M', '30m': '30M',
  '1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W',
};

/** All supported timeframes in descending order (highest first) */
export const ALL_TFS = ['1w', '1d', '4h', '1h', '15m', '5m', '1m'];

/**
 * Default colors exactly matching the Pine Script indicator:
 * 1W=teal, 1D=purple, 4H=yellow, 1H=red, 15m=blue, 5m=green, 1m=orange
 */
export const TF_COLORS = {
  '1w':  '#27a7b0',
  '1d':  '#9C27B0',
  '4h':  '#FFC107',
  '1h':  '#F44336',
  '15m': '#2196F3',
  '5m':  '#4CAF50',
  '1m':  '#FF9800',
};

/** Color applied to a swing line once price has touched (mitigated) it */
export const FILLED_COLOR = 'rgba(120,123,134,0.55)';

// ── Default settings (analogous to Pine Script input defaults) ────────────────

export const DEFAULT_SWING_SETTINGS = {
  showHighs:       true,
  showLows:        true,
  hideFilled:      false,
  filterMitigated: false,
  showMitigated:   false,
  tfs: {
    '1w':  { enabled: true, color: TF_COLORS['1w'],  lookback: 30,  extendTillFilled: true },
    '1d':  { enabled: true, color: TF_COLORS['1d'],  lookback: 40,  extendTillFilled: true },
    '4h':  { enabled: true, color: TF_COLORS['4h'],  lookback: 60,  extendTillFilled: true },
    '1h':  { enabled: true, color: TF_COLORS['1h'],  lookback: 60,  extendTillFilled: true },
    '15m': { enabled: true, color: TF_COLORS['15m'], lookback: 50,  extendTillFilled: true },
    '5m':  { enabled: true, color: TF_COLORS['5m'],  lookback: 50,  extendTillFilled: true },
    '1m':  { enabled: true, color: TF_COLORS['1m'],  lookback: 50,  extendTillFilled: true },
  },
};

// ── Aggregation ───────────────────────────────────────────────────────────────

/** Minutes per each target timeframe bucket */
const TF_MINUTES = {
  '15m': 15, '30m': 30, '1h': 60, '4h': 240, '1d': 1440, '1w': 10080,
};

/**
 * normalizeTimeForChart
 * ─────────────────────
 * Converts a unix-second timestamp (from aggregateCandles output) into
 * the time format used by the chart's own candleData.
 *   - Intraday charts (1m–4h) use unix-second numbers.
 *   - Daily/weekly charts (1d, 1w) use 'YYYY-MM-DD' strings.
 */
export function normalizeTimeForChart(unixSec, chartTf) {
  const intraday = ['1m', '5m', '15m', '30m', '1h', '4h'].includes(chartTf);
  if (intraday) return unixSec;
  return new Date(unixSec * 1000).toISOString().substring(0, 10);
}

/**
 * aggregateCandles
 * ────────────────
 * Groups lower-TF candles into higher-TF OHLC buckets.
 * Equivalent to the backend's resample_candles() function.
 *
 * @param {Array} candles  – sorted ascending [{time, open, high, low, close}]
 *                           time may be a unix-second number or 'YYYY-MM-DD' string
 * @param {string} targetTf – target timeframe key, e.g. '4h'
 * @returns {Array} aggregated candles sorted ascending, time is unix-seconds
 */
export function aggregateCandles(candles, targetTf) {
  const minutes = TF_MINUTES[targetTf];
  if (!minutes || !candles || candles.length === 0) return [];

  const bucketSecs = minutes * 60;
  const buckets    = {};

  for (const c of candles) {
    // Normalise time to unix-seconds
    let ts;
    if (typeof c.time === 'number') {
      ts = c.time;
    } else {
      // 'YYYY-MM-DD' → treat as UTC midnight → unix-seconds
      ts = Math.floor(new Date(c.time + 'T00:00:00Z').getTime() / 1000);
    }

    const bucket = Math.floor(ts / bucketSecs) * bucketSecs;

    if (!buckets[bucket]) {
      buckets[bucket] = {
        time:   bucket,
        open:   c.open,
        high:   c.high,
        low:    c.low,
        close:  c.close,
        volume: c.volume || 0,
      };
    } else {
      const b    = buckets[bucket];
      b.high     = Math.max(b.high,   c.high);
      b.low      = Math.min(b.low,    c.low);
      b.close    = c.close;
      b.volume  += c.volume || 0;
    }
  }

  return Object.values(buckets).sort((a, b) => a.time - b.time);
}

// ── Swing detection ───────────────────────────────────────────────────────────

/**
 * detectSwings
 * ────────────
 * Finds pivot highs and lows using the 3-candle rule:
 *   Pivot high: candles[i].high > candles[i-1].high AND > candles[i+1].high
 *   Pivot low:  candles[i].low  < candles[i-1].low  AND < candles[i+1].low
 *
 * Returns only the `lookbackBars` most recent candles (from the right).
 *
 * @param {Array}  candles      – aggregated OHLC sorted ascending
 * @param {number} lookbackBars – how many bars from the end to scan
 * @returns {{ highs: Array, lows: Array }}
 */
export function detectSwings(candles, lookbackBars = 300) {
  if (!candles || candles.length < 3) return { highs: [], lows: [] };

  const highs = [];
  const lows  = [];

  // Only scan within lookback window, but need at least one candle of context on each side
  const startIdx = Math.max(1, candles.length - lookbackBars - 1);
  const endIdx   = candles.length - 1; // exclusive (can't pivot on last candle — no right neighbour)

  for (let i = startIdx; i < endIdx; i++) {
    const prev = candles[i - 1];
    const cur  = candles[i];
    const next = candles[i + 1];

    if (cur.high > prev.high && cur.high > next.high) {
      highs.push({ time: cur.time, price: cur.high, mitigated: false, mitigatedAt: null, active: false });
    }
    if (cur.low < prev.low && cur.low < next.low) {
      lows.push({ time: cur.time, price: cur.low, mitigated: false, mitigatedAt: null, active: false });
    }
  }

  return { highs, lows };
}

// ── Level state helpers ───────────────────────────────────────────────────────

/**
 * isFilled
 * ────────
 * Returns true if the current candle has traded *through* the swing level
 * (i.e., its range engulfs the level price).
 */
export function isFilled(levelPrice, currentHigh, currentLow) {
  return currentHigh >= levelPrice && currentLow <= levelPrice;
}

/**
 * updateMitigationState
 * ──────────────────────
 * Updates mitigation state incrementally for a single candle.
 * Modifies swing objects in-place.
 */
export function updateMitigationState({ swings, currentHigh, currentLow, currentTime }) {
  for (let i = 0; i < swings.length; i++) {
    const swing = swings[i];
    if (!swing.mitigated) {
      if (currentHigh >= swing.price && currentLow <= swing.price) {
        swing.mitigated = true;
        swing.mitigatedAt = currentTime;
        swing.active = false;
      }
    }
  }
}

/**
 * classifySwings
 * ──────────────
 * Splits swings into unmitigated above, unmitigated below, and mitigated.
 */
export function classifySwings(swings, currentPrice) {
  const unmitigatedAbove = [];
  const unmitigatedBelow = [];
  const mitigated = [];

  for (let i = 0; i < swings.length; i++) {
    const s = swings[i];
    if (s.mitigated) {
      mitigated.push(s);
    } else {
      if (s.price > currentPrice) {
        unmitigatedAbove.push(s);
      } else {
        unmitigatedBelow.push(s);
      }
    }
  }
  return { unmitigatedAbove, unmitigatedBelow, mitigated };
}

/**
 * selectActiveSwings
 * ──────────────────
 * Assigns active=true for 3 closest unmitigated above and below.
 * Assigns active=false for all others.
 */
export function selectActiveSwings(swings, currentPrice) {
  const { unmitigatedAbove, unmitigatedBelow } = classifySwings(swings, currentPrice);

  for (let i = 0; i < swings.length; i++) {
    swings[i].active = false;
  }

  // Stable sort by distance
  unmitigatedAbove.sort((a, b) => Math.abs(a.price - currentPrice) - Math.abs(b.price - currentPrice));
  unmitigatedBelow.sort((a, b) => Math.abs(a.price - currentPrice) - Math.abs(b.price - currentPrice));

  const activeAbove = unmitigatedAbove.slice(0, 3);
  const activeBelow = unmitigatedBelow.slice(0, 3);

  for (let i = 0; i < activeAbove.length; i++) activeAbove[i].active = true;
  for (let i = 0; i < activeBelow.length; i++) activeBelow[i].active = true;

  return { activeAbove, activeBelow };
}

/**
 * enforceMaxLines
 * ───────────────
 * Restricts array size to maxLinesPerTF, prioritizing active > unmitigated > recent mitigated.
 */
export function enforceMaxLines(swings, maxLines = 20) {
  if (swings.length <= maxLines) return swings;

  const active = swings.filter(s => s.active);
  const unmitigated = swings.filter(s => !s.mitigated && !s.active).sort((a, b) => b.time - a.time);
  const mitigated = swings.filter(s => s.mitigated).sort((a, b) => b.time - a.time);

  const retained = [];
  retained.push(...active);

  let remaining = maxLines - retained.length;
  if (remaining > 0) {
    const toAdd = unmitigated.slice(0, remaining);
    retained.push(...toAdd);
    remaining -= toAdd.length;
  }
  if (remaining > 0) {
    const toAdd = mitigated.slice(0, remaining);
    retained.push(...toAdd);
  }

  return retained.sort((a, b) => Math.abs(a.time - b.time)); // optional restore time order
}

/**
 * getHigherTfs
 * ────────────
 * Returns all TFs in ALL_TFS that are strictly higher than the chart's TF.
 * Only higher-TF swings are relevant to display on a given chart.
 */
export function getHigherTfs(chartTf) {
  const chartSecs = TF_SECONDS[chartTf] || 0;
  return ALL_TFS.filter(tf => TF_SECONDS[tf] > chartSecs);
}

// ── ML data persistence ───────────────────────────────────────────────────────

const ML_KEY     = 'swing_ml_data';
const ML_MAX     = 10000; // maximum stored entries

/**
 * saveSwingsToMemory
 * ──────────────────
 * Persists detected swing highs/lows for a given symbol+tf to localStorage.
 * Existing entries for the same symbol+tf are replaced (fresh snapshot).
 * Total entries are capped at ML_MAX (oldest are discarded).
 *
 * Schema per entry:
 *   { symbol, tf, type:'high'|'low', price, time, savedAt }
 *
 * Load for ML training:
 *   const data = JSON.parse(localStorage.getItem('swing_ml_data') || '[]');
 *   // → array ready for pandas / sklearn / pytorch
 */
export function saveSwingsToMemory(symbol, tf, highs, lows) {
  try {
    const existing = JSON.parse(localStorage.getItem(ML_KEY) || '[]');
    const savedAt  = Math.floor(Date.now() / 1000);

    // Remove old snapshot for this symbol+tf (replace strategy)
    const filtered = existing.filter(e => !(e.symbol === symbol && e.tf === tf));

    const newEntries = [
      ...highs.map(h => ({ symbol, tf, type: 'high', price: h.price, time: h.time, savedAt })),
      ...lows.map(l  => ({ symbol, tf, type: 'low',  price: l.price, time: l.time, savedAt })),
    ];

    const updated = [...filtered, ...newEntries];
    const trimmed = updated.length > ML_MAX ? updated.slice(-ML_MAX) : updated;
    localStorage.setItem(ML_KEY, JSON.stringify(trimmed));
  } catch {
    /* Storage quota exceeded – fail silently */
  }
}

/**
 * loadSwingsFromMemory
 * ────────────────────
 * Returns all stored swing records, optionally filtered by symbol and/or tf.
 */
export function loadSwingsFromMemory(symbol = null, tf = null) {
  try {
    const data = JSON.parse(localStorage.getItem(ML_KEY) || '[]');
    return data.filter(e =>
      (symbol === null || e.symbol === symbol) &&
      (tf     === null || e.tf     === tf)
    );
  } catch {
    return [];
  }
}

/**
 * exportSwingsAsCsv
 * ─────────────────
 * Converts all stored swing records to a CSV string ready for download
 * or copy-paste into a spreadsheet / pandas.
 */
export function exportSwingsAsCsv(symbol = null) {
  const data = loadSwingsFromMemory(symbol);
  if (!data.length) return '';
  const header = 'symbol,tf,type,price,time,savedAt';
  const rows   = data.map(r =>
    `${r.symbol},${r.tf},${r.type},${r.price},${r.time},${r.savedAt}`
  );
  return [header, ...rows].join('\n');
}

/**
 * clearSwingsFromMemory
 * ──────────────────────
 * Wipes all stored swing records (use from dev console or "Clear ML Data" button).
 */
export function clearSwingsFromMemory() {
  try { localStorage.removeItem(ML_KEY); } catch { /* ignore */ }
}
