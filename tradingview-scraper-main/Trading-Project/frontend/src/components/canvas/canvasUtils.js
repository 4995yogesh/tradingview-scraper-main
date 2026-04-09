// ── Canvas coordinate utilities ─────────────────────────────────────────────

/**
 * Convert world (time, price) → canvas pixel (x, y)
 * Pre-computes the scale factors to avoid repeated division.
 */
export function worldToCanvas(t, p, viewport) {
  const { timeMin, _timeScale, priceMin, _priceScale, height } = viewport;
  return {
    x: (t - timeMin) * _timeScale,
    y: height - (p - priceMin) * _priceScale,
  };
}

/**
 * Convert canvas pixel → world coordinates
 */
export function canvasToWorld(x, y, viewport) {
  const { timeMin, _timeScale, priceMin, _priceScale, height } = viewport;
  return {
    t: timeMin + x / _timeScale,
    p: priceMin + (height - y) / _priceScale,
  };
}

/**
 * Build a viewport from candle data + pan/zoom state.
 * Pre-computes _timeScale and _priceScale so worldToCanvas never divides.
 * Returns a cached result if inputs are identical (shallow compare on primitive fields).
 */
let _vpCache = null;

export function buildViewport(candles, scenarios, panX, panY, zoom, width, height) {
  // Cache key from primitive fields
  const key = `${candles.length}-${panX.toFixed(0)}-${panY.toFixed(5)}-${zoom.toFixed(4)}-${width}-${height}`;
  if (_vpCache && _vpCache._key === key) return _vpCache;

  if (!candles.length) {
    const vp = {
      timeMin: Date.now() - 3 * 3_600_000,
      timeMax: Date.now() + 1 * 3_600_000,
      priceMin: 1.0800,
      priceMax: 1.0900,
      width, height,
      _key: key,
    };
    vp._timeScale  = width  / (vp.timeMax  - vp.timeMin);
    vp._priceScale = height / (vp.priceMax - vp.priceMin);
    return (_vpCache = vp);
  }

  // Collect all times and prices in one pass over candles
  let tMin = Infinity, tMax = -Infinity;
  let pMin = Infinity, pMax = -Infinity;

  for (const c of candles) {
    if (c.time < tMin) tMin = c.time;
    if (c.time > tMax) tMax = c.time;
    if (c.low  < pMin) pMin = c.low;
    if (c.high > pMax) pMax = c.high;
  }

  // Extend for scenario paths — only if scenarios have content
  for (const arr of Object.values(scenarios)) {
    for (const s of arr) {
      if (s.entry != null) { if (s.entry < pMin) pMin = s.entry; if (s.entry > pMax) pMax = s.entry; }
      if (s.sl    != null) { if (s.sl    < pMin) pMin = s.sl;    if (s.sl    > pMax) pMax = s.sl;    }
      if (s.tp_zone) {
        const { high, low } = s.tp_zone;
        if (high != null && high > pMax) pMax = high;
        if (low  != null && low  < pMin) pMin = low;
      }
      if (s.path) {
        for (const pt of s.path) {
          if (pt.price < pMin) pMin = pt.price;
          if (pt.price > pMax) pMax = pt.price;
        }
      }
    }
  }

  const futureMs  = (tMax - tMin) * 0.5;
  const pricePad  = (pMax - pMin) * 0.10;

  const baseTimeRange  = (tMax - tMin + futureMs) / zoom;
  const basePriceRange = (pMax - pMin + 2 * pricePad) / zoom;

  const timeMid  = (tMin + tMax)  / 2 + futureMs / 2 + panX;
  const priceMid = (pMin + pMax) / 2 + pricePad + panY;

  const vpTimeMin  = timeMid  - baseTimeRange / 2;
  const vpTimeMax  = timeMid  + baseTimeRange / 2;
  const vpPriceMin = priceMid - basePriceRange / 2;
  const vpPriceMax = priceMid + basePriceRange / 2;

  const vp = {
    timeMin:  vpTimeMin,
    timeMax:  vpTimeMax,
    priceMin: vpPriceMin,
    priceMax: vpPriceMax,
    width,
    height,
    _key:        key,
    _timeScale:  width  / (vpTimeMax  - vpTimeMin),
    _priceScale: height / (vpPriceMax - vpPriceMin),
  };

  return (_vpCache = vp);
}

/**
 * Timeframe config: strokeWidth, opacity multiplier
 */
export const TF_CONFIG = {
  '4H': { strokeWidth: 3.5, opacity: 0.35 },
  '1H': { strokeWidth: 2.5, opacity: 0.50 },
  '15m': { strokeWidth: 1.8, opacity: 0.65 },
  '5m':  { strokeWidth: 1.2, opacity: 0.80 },
  '1m':  { strokeWidth: 0.8, opacity: 1.00 },
};

export const TF_ORDER = ['4H', '1H', '15m', '5m', '1m'];

// ── Color constants ──────────────────────────────────────────────────────────
export const COLORS = {
  buy:           '#22d3a5',
  sell:          '#f5525b',
  none:          '#8b8fa9',
  bg:            '#0d0f17',
  grid:          '#181c2a',
  gridLine:      '#1e2336',
  axis:          '#2a3050',
  candleUp:      '#22d3a5',
  candleDown:    '#f5525b',
  consolidation: '#3b4a7a',
  crosshair:     '#4a90d9',
  confirmed:     '#ffd700',
};

/**
 * Pre-computed RGBA cache — avoids re-parsing hex strings on every frame.
 * Format: RGBA_CACHE['#22d3a5'][0.6] = 'rgba(34,211,165,0.6)'
 */
const _rgbaCache = new Map();

/**
 * Convert hex + alpha → rgba string, with module-level caching.
 * Avoids the 10–20 hex parses per scenario per frame that the old code did.
 */
export function hexAlpha(hex, alpha) {
  const key = hex + alpha.toFixed(2);
  let cached = _rgbaCache.get(key);
  if (cached) return cached;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  cached = `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
  _rgbaCache.set(key, cached);
  return cached;
}

// Pre-warm the cache for all colours × common alphas
const _COMMON_ALPHAS = [0.10, 0.15, 0.20, 0.25, 0.35, 0.40, 0.50, 0.60, 0.65, 0.70, 0.80, 0.90, 1.00];
for (const hex of Object.values(COLORS)) {
  for (const a of _COMMON_ALPHAS) hexAlpha(hex, a);
}
