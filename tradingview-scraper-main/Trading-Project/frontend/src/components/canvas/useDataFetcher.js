import { useState, useEffect, useRef, useCallback } from 'react';

// ── Config ──────────────────────────────────────────────────────────────────
const API_URL       = process.env.REACT_APP_API_URL || 'http://localhost:8001';
const POLL_MS       = 5_000;
const USE_MOCK      = true;   // Set false when backend is live

// ── Stable mock data ─────────────────────────────────────────────────────────
// Candles are generated ONCE at module load and only the tail is updated on
// each poll tick — prevents the viewport from jumping every 5 seconds.
let _mockCandles = null;

function _buildMockCandles() {
  if (_mockCandles) return _mockCandles;

  const now   = Date.now();
  const base  = 1.08500;
  const N     = 200;
  const candles = [];
  let price = base;

  for (let i = N; i >= 0; i--) {
    const t      = now - i * 60_000;
    const phase  = i / N;
    // Drift: gentle uptrend → consolidation → breakout structure
    let drift;
    if (phase > 0.6)      drift = 0.0000;          // consolidation
    else if (phase > 0.3) drift = 0.0001;           // uptrend
    else                  drift = 0.0002;           // strong breakout

    const noise = (Math.random() - 0.5) * 0.00060;
    const open  = price;
    const close = +(open + drift + noise).toFixed(5);
    const high  = +(Math.max(open, close) + Math.random() * 0.00040).toFixed(5);
    const low   = +(Math.min(open, close) - Math.random() * 0.00040).toFixed(5);
    candles.push({ time: t, open, high, low, close, volume: 1000 + Math.random() * 1500 });
    price = close;
  }

  _mockCandles = candles;
  return candles;
}

// Returns mock candles with a fresh tail candle appended
function _getMockCandlesWithTickUpdate() {
  const base    = _buildMockCandles();
  const now     = Date.now();
  const noise   = (Math.random() - 0.5) * 0.00030;
  const lastClose = base[base.length - 1].close;
  const newClose  = +(lastClose + noise).toFixed(5);

  // Mutate the last candle's close in-place (doesn't shift the array → no viewport reset)
  base[base.length - 1] = {
    ...base[base.length - 1],
    close: newClose,
    high:  Math.max(base[base.length - 1].high,  newClose),
    low:   Math.min(base[base.length - 1].low,   newClose),
  };
  return [...base]; // shallow copy so React sees a new array reference
}

function _buildMockScenarios(candles) {
  if (!candles.length) return {};
  const basePrice = candles[candles.length - 1].close;
  const now       = Date.now();

  const makePath = (entry, direction, steps = 10) => {
    let price = entry;
    const pts = [];
    for (let i = 1; i <= steps; i++) {
      const zigzag = Math.sin(i * 0.9) * 0.00050;
      const trend  = direction === 'buy' ? 0.00020 : -0.00020;
      price += trend + zigzag;
      pts.push({ time: now + i * 60_000, price: +price.toFixed(5) });
    }
    return pts;
  };

  const makeScenario = (type, eOff, slOff, tpOff, confirmed = false) => ({
    type,
    entry:    +(basePrice + eOff).toFixed(5),
    sl:       +(basePrice + slOff).toFixed(5),
    tp_zone:  {
      high: +(basePrice + tpOff + 0.00080).toFixed(5),
      low:  +(basePrice + tpOff).toFixed(5),
    },
    path:          makePath(basePrice + eOff, type),
    scenario_name: type === 'none' ? 'No Trade' : (confirmed ? 'Continuation' : 'Trap Reversal'),
    confirmed,
    rr_ratio:  +(Math.abs(tpOff) / Math.abs(slOff)).toFixed(2),
    strength:  confirmed ? 0.85 : 0.55,
  });

  return {
    '4H':  [makeScenario('buy',  0, -0.0040, 0.0080, true),  makeScenario('sell', 0, 0.0040, -0.0080)],
    '1H':  [makeScenario('buy',  0, -0.0025, 0.0050),        makeScenario('none', 0, 0,       0)],
    '15m': [makeScenario('sell', 0,  0.0020, -0.0045),       makeScenario('buy',  0, -0.0012, 0.0028, true)],
    '5m':  [makeScenario('buy',  0, -0.0008, 0.0018),        makeScenario('sell', 0, 0.0010, -0.0020)],
    '1m':  [makeScenario('buy',  0, -0.0005, 0.0012, true),  makeScenario('none', 0, 0,       0)],
  };
}

function _buildMockConsolidations(candles) {
  if (!candles.length) return [];
  const now  = Date.now();
  const base = candles[candles.length - 1].close;
  return [
    {
      id: 'c1', timeframe: '15m',
      timeStart: now - 40 * 60_000, timeEnd: now - 10 * 60_000,
      priceLow: +(base - 0.00150).toFixed(5), priceHigh: +(base + 0.00120).toFixed(5),
    },
    {
      id: 'c2', timeframe: '1H',
      timeStart: now - 120 * 60_000, timeEnd: now - 60 * 60_000,
      priceLow: +(base - 0.00350).toFixed(5), priceHigh: +(base - 0.00100).toFixed(5),
    },
  ];
}

// ── Hook ─────────────────────────────────────────────────────────────────────
export function useDataFetcher() {
  const [scenarios,      setScenarios]      = useState({});
  const [candles,        setCandles]        = useState([]);
  const [consolidations, setConsolidations] = useState([]);
  const [nnZones,        setNnZones]        = useState([]);
  const [error,          setError]          = useState(null);
  const [lastUpdated,    setLastUpdated]    = useState(null);

  const abortRef = useRef(null);

  const fetchData = useCallback(async () => {
    if (USE_MOCK) {
      const cndls = _getMockCandlesWithTickUpdate();
      setCandles(cndls);
      setScenarios(_buildMockScenarios(cndls));
      setConsolidations(_buildMockConsolidations(cndls));
      setLastUpdated(Date.now());
      return;
    }

    // Cancel previous in-flight request
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const { signal } = abortRef.current;

    try {
      const [scenRes, candleRes, consRes] = await Promise.all([
        fetch(`${API_URL}/scenarios`,     { signal }),
        fetch(`${API_URL}/candles?tf=1m&limit=250`, { signal }),
        fetch(`${API_URL}/consolidations`, { signal }),
      ]);

      if (!scenRes.ok) throw new Error(`Scenarios ${scenRes.status}`);

      const [scenData, candleData, consData] = await Promise.all([
        scenRes.json(),
        candleRes.ok ? candleRes.json() : Promise.resolve({ candles: [] }),
        consRes.ok   ? consRes.json()   : Promise.resolve({ zones:   [] }),
      ]);

      setScenarios(scenData);
      setCandles(candleData.candles ?? []);
      setConsolidations(consData.zones ?? []);
      setError(null);
      setLastUpdated(Date.now());
    } catch (err) {
      if (err.name === 'AbortError') return;   // intentional cancel
      setError(err.message);
      // Graceful fallback to mock
      const cndls = _getMockCandlesWithTickUpdate();
      setCandles(cndls);
      setScenarios(_buildMockScenarios(cndls));
      setConsolidations(_buildMockConsolidations(cndls));
      setLastUpdated(Date.now());
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, POLL_MS);
    return () => {
      clearInterval(id);
      abortRef.current?.abort();
    };
  }, [fetchData]);

  useEffect(() => {
    if (USE_MOCK) return;
    const fetchNnZones = () => {
      fetch(`${API_URL}/api/nn/refined_zones?symbol=EURUSD&timeframe=5m`)
        .then(res => res.json())
        .then(data => setNnZones(data))
        .catch(err => console.error('[useDataFetcher] nnZones error:', err));
    };
    fetchNnZones();
    const id = setInterval(fetchNnZones, 10000);
    return () => clearInterval(id);
  }, []);

  return { scenarios, candles, consolidations, nnZones, error, lastUpdated };
}
