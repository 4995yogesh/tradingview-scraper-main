import React, { useEffect, useRef, useCallback, useState, forwardRef, useImperativeHandle } from 'react';
import { createChart, CandlestickSeries, LineSeries, AreaSeries, BarSeries, BaselineSeries } from 'lightweight-charts';
import { fetchLiveCandles, fetchInitialCandles, INITIAL_CANDLE_BUDGET } from '../../data/chartData';
import { ChevronsRight } from 'lucide-react';
import {
  aggregateCandles, detectSwings, getHigherTfs, ALL_TFS,
  normalizeTimeForChart, TF_COLORS, FILLED_COLOR,
} from '../../lib/swingLevels';
import LabelDialog from './LabelDialog';
import { ConsolidationBoxesPrimitive } from './plugins/BoxPrimitive';

let globalLastBarSpacing = null;
let globalLastCenterTime = null;

// Sensible number of bars to fetch per timeframe so candles are visible at the initial zoom
const TF_CANDLE_COUNT = {
  '1m':  300,
  '5m':  600,  // 600 × 5m = 50h — covers full overnight + weekend gaps
  '15m': 400,
'1h':  500,
  '4h':  600,
  '1d':  750,
  '1w':  500,
  '1M':  240,
};

// Default bar spacing (pixels per bar) per timeframe
const TF_BAR_SPACING = {
  '1m':  6,
  '5m':  6,
  '15m': 6,
'1h':  8,
  '4h':  8,
  '1d':  8,
  '1w':  10,
  '1M':  14,
};
// ================================
// MARKET CLOSED FILTER (SAFE)
// ================================
function isWeekendBlackout(time) {
  const d = new Date(time * 1000);
  const day = d.getUTCDay();
  const hr = d.getUTCHours();

  // Saturday is always closed implicitly
  if (day === 6) return true;

  // Friday shutdown boundaries (approx 21:00 or 22:00 UTC depending on DST)
  // Safely bounding >= 21 UTC handles both winter/summer NY closures
  if (day === 5 && hr >= 21) return true;

  // Sunday open boundaries (approx 21:00 or 22:00 UTC)
  // Safely bouncing < 21 UTC captures stray ticks emitted during dead zones
  if (day === 0 && hr < 21) return true;

  return false;
}

// ================================
// DAILY STRING CONVERSION
// ================================
function toDayString(time) {
  const d = new Date(time * 1000);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
}

// ================================
// WEEKLY ALIGNMENT (MANDATORY)
// ================================
function toWeekString(time) {
  const d = new Date(time * 1000);

  const day = d.getUTCDay();
  const diff = (day === 0 ? -6 : 1 - day); // Monday

  const monday = new Date(d);
  monday.setUTCDate(d.getUTCDate() + diff);
  monday.setUTCHours(0, 0, 0, 0);

  return `${monday.getUTCFullYear()}-${String(monday.getUTCMonth()+1).padStart(2,'0')}-${String(monday.getUTCDate()).padStart(2,'0')}`;
}

// ================================
// STAGE 1: RAW DEDUPE (UNIX LEVEL)
// ================================
function dedupeRaw(data) {
  const map = new Map();

  for (const c of data) {
    const key = c.time;

    if (!map.has(key)) {
      map.set(key, { ...c });
    } else {
      const existing = map.get(key);

      map.set(key, {
        ...existing,
        high: Math.max(existing.high, c.high),
        low: Math.min(existing.low, c.low),
        close: c.close
      });
    }
  }

  return Array.from(map.values());
}

// ================================
// STAGE 2: FINAL DEDUPE
// ================================
function dedupeAfterTimeTransform(data) {
  const map = new Map();

  for (const c of data) {
    const key = c.time;

    if (!map.has(key)) {
      map.set(key, { ...c });
    } else {
      const existing = map.get(key);

      map.set(key, {
        ...existing,
        high: Math.max(existing.high, c.high),
        low: Math.min(existing.low, c.low),
        close: c.close
      });
    }
  }

  return Array.from(map.values());
}

// ================================
// STRICT ORDER VALIDATION
// ================================
function assertStrictOrder(data) {
  for (let i = 1; i < data.length; i++) {
    if (data[i].time <= data[i - 1].time) {
      console.error("ORDER ERROR", data[i], data[i - 1]);
      throw new Error("Time ordering violation");
    }
  }
}

// ================================
// SAFE PIPELINE
// ================================
function prepareChartData(rawCandles, timeframe) {
  if (!Array.isArray(rawCandles)) return [];

  // normalize properly to handle String dates from backend
  let data = rawCandles
    .map(c => {
      let t = c.time;
      if (typeof t === 'string' && t.includes('-')) {
        t = new Date(t).getTime() / 1000;
      } else {
        t = Number(t);
      }
      return { ...c, time: t };
    })
    .filter(c => {
      const basic = Number.isFinite(c.time);
      if (!basic) return false;

      const hasCandlePrices = c.open !== undefined && c.high !== undefined && c.low !== undefined && c.close !== undefined &&
                              c.open !== null && c.high !== null && c.low !== null && c.close !== null;
      if (hasCandlePrices) {
        const o = Number(c.open), h = Number(c.high), l = Number(c.low), cl = Number(c.close);
        return Number.isFinite(o) && Number.isFinite(h) && Number.isFinite(l) && Number.isFinite(cl);
      }

      const hasVolume = c.value !== undefined && c.value !== null;
      if (hasVolume) {
        return Number.isFinite(Number(c.value));
      }

      return false;
    });

  // STAGE 1 DEDUPE (raw)
  data = dedupeRaw(data);

  // Filter missing blackout spans (weekends + rogue server noise)
  data = data.filter(c => !isWeekendBlackout(c.time));

  // transform
  if (timeframe === '1d') {
    data = data.map(c => ({
      ...c,
      realTime: c.time,
      time: toDayString(c.time)
    }));
  }

  if (timeframe === '1w') {
    data = data.map(c => ({
      ...c,
      realTime: c.time,
      time: toWeekString(c.time)
    }));
  }

  // STAGE 2 DEDUPE (post-transform)
  data = dedupeAfterTimeTransform(data);

  // sort
  data.sort((a, b) => (a.time > b.time ? 1 : -1));

  // validate
  assertStrictOrder(data);

  return data;
}

// ================================
// OVERLAY MAPPING HELPER
// ================================
function mapOverlayTime(realTime, tf) {
  if (tf === '1d') return toDayString(realTime);
  if (tf === '1w') return toWeekString(realTime);
  return realTime;
}




const ChartWidget = forwardRef(({ symbol, timeframe, chartType, onPriceUpdate, logScale, chartSettings, refreshKey, symbolKey = 0, symbolPrecision = 4, swingSettings, consolidationSettings, neuralSettings, liveTickKey, aiMode, nnMode, pmMode, isSubchart, initialBars, paneIndex = 0, paneCount = 1, sharedConsolidations, sharedSwings, sharedAutoLabels, sharedNNZones }, ref) => {
  const chartContainerRef      = useRef(null);
  const chartRef               = useRef(null);
  const seriesRef              = useRef(null);
  const isLoadingMoreRef       = useRef(false);
  const swingSeriesRef         = useRef([]); // swing level LineSeries
  const emaHighSeriesRef       = useRef(null);
  const emaLowSeriesRef        = useRef(null);
  const consolidationPrimitiveRef = useRef(null); // Fast native shape plugin
  const aiPrimitiveRef = useRef(null); // Separate AI-predicted box layer
  const nnPrimitiveRef = useRef(null); // Separate Neural-predicted box layer
  const pendingScrollBoxRef = useRef(null);
  const isFetchingOlderRef = useRef(false);
  const loadedContextRef = useRef(null);
  const pmPrimitiveRef = useRef(null); // Pattern Memory box layer
  const [chartKey, setChartKey] = useState(0); // increments when chart is re-initialised

  const [domZones, setDomZones] = useState([]);
  const domZonesRef = useRef([]);

  const [chartData, setChartData] = useState(null);
  const chartDataRef = useRef(null);
  chartDataRef.current = chartData;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  // ML label dialog state
  const [activeLabelZone, setActiveLabelZone] = useState(null);
  const [hoveredBoxId, setHoveredBoxId] = useState(null);
  const [specialHighlightedBox, setSpecialHighlightedBox] = useState(null);
  const [highlightedBoxId, setHighlightedBoxId] = useState(null);
  // Store zone data keyed by box_id for overlay rendering
  const activeBoxesRef = useRef([]);
  const [autoLabels, setAutoLabels] = useState([]);




  useImperativeHandle(ref, () => ({
    getChart: () => chartRef.current,
    getSeries: () => seriesRef.current,
    getContainer: () => chartContainerRef.current,
    setVisibleRange: (range) => {
      if (chartRef.current && chartData) {
        try {
          const ts = chartRef.current.timeScale();
          const len = chartData.candleData.length;
          if (range === 'all') { ts.fitContent(); return; }
          const barsMap = { '1D': 1, '5D': 5, '1M': 22, '3M': 66, '6M': 132, 'YTD': 180, '1Y': 252, '5Y': 1260 };
          const barsToShow = barsMap[range] || len;
          const from = Math.max(0, len - barsToShow);
          ts.setVisibleRange({ from: chartData.candleData[from].time, to: chartData.candleData[len - 1].time });
        } catch (e) { console.warn('setVisibleRange error', e); }
      }
    },
    fitContent: () => { chartRef.current?.timeScale().fitContent(); },
  }));

  const lastContextRef = useRef(`${symbol}:${timeframe}`);
  const hasDataRef = useRef(false);
  // Refs so initChart's scroll handler always sees the latest symbol/timeframe
  // without needing them as useCallback dependencies (avoids full canvas teardown).
  const symbolRef = useRef(symbol);
  const timeframeRef = useRef(timeframe);
  useEffect(() => { symbolRef.current = symbol; }, [symbol]);
  useEffect(() => { timeframeRef.current = timeframe; }, [timeframe]);

  // ── Initial candle fetch (budget-limited) ─────────────────────────────────
  // Loads exactly Math.floor(1000 / paneCount) candles for the first paint,
  // for EVERY pair — not just the first one opened. The hot in-memory store
  // (hotCandleStore) returns cached slices instantly (O(1)) on revisits.
  // Historical candles beyond the budget are loaded on-demand by the
  // infinite-scroll handler below (user pans left), which calls fetchLiveCandles
  // with the full TF_CANDLE_COUNT — matching the original "rest load at normal
  // speed" intent.
  useEffect(() => {
    let cancelled = false;
    const newContext = `${symbol}:${timeframe}`;
    const isContextChange = lastContextRef.current !== newContext;
    lastContextRef.current = newContext;

    if (isContextChange || !hasDataRef.current) {
      setLoading(true);
      setError(null);
      hasDataRef.current = false;
    }

    const perPaneBudget = Math.max(50, Math.floor(INITIAL_CANDLE_BUDGET / paneCount));
    fetchInitialCandles(symbol, timeframe, perPaneBudget)
      .then((data) => {
        if (cancelled) return;
        setChartData(data);
        loadedContextRef.current = `${symbol}:${timeframe}`;
        setLoading(false);
        hasDataRef.current = true;
      })
      .catch((err) => {
        if (cancelled) return;
        if (!hasDataRef.current) {
          const msg = err?.message === 'initial_load'
            ? 'Fetching initial data from TradingView…'
            : 'Failed to load chart data';
          setError(msg);
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [symbol, timeframe, refreshKey, retryCount, paneCount]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!error) return;
    const retryDelay = error.includes('Fetching initial') ? 8000 : null;
    if (!retryDelay) return;
    const t = setTimeout(() => setRetryCount(c => c + 1), retryDelay);
    return () => clearTimeout(t);
  }, [error]);

  // ── Live Polling: Fetch latest candles and push directly to series ──
  useEffect(() => {
    if (loading || error || typeof liveTickKey === 'undefined' || liveTickKey === 0) return;
    if (!seriesRef.current || !chartRef.current) return;

    let active = true;

    (async () => {
      try {
        const latest = await fetchLiveCandles(symbol, timeframe, 10);
        if (!active) return;
        if (!seriesRef.current || !chartRef.current) return;
        if (!latest || latest.candleData.length === 0) return;

        // Normalise timestamps the same way prepareChartData does
        const mapped = latest.candleData.map(c => {
          let t = c.time;
          if (typeof t === 'string' && t.includes('-')) {
            t = timeframe === '1d' ? t : new Date(t).getTime() / 1000;
          } else {
            t = Number(t);
          }
          if (timeframe === '1d') t = typeof c.time === 'string' ? c.time : new Date(c.time * 1000).toISOString().slice(0, 10);
          if (timeframe === '1w') {
            const d = typeof c.time === 'string' ? new Date(c.time) : new Date(c.time * 1000);
            const day = d.getDay();
            const diff = d.getDate() - day + (day === 0 ? -6 : 1);
            const mon = new Date(d.setDate(diff));
            t = mon.toISOString().slice(0, 10);
          }
          return { ...c, time: t };
        }).filter(c => {
          const hasPrices = c.open !== undefined && c.high !== undefined && c.low !== undefined && c.close !== undefined &&
                            c.open !== null && c.high !== null && c.low !== null && c.close !== null;
          if (!hasPrices) return false;
          return Number.isFinite(Number(c.open)) && Number.isFinite(Number(c.high)) && Number.isFinite(Number(c.low)) && Number.isFinite(Number(c.close));
        });

        // Push each candle via series.update() — the correct LightweightCharts live-update API
        for (const candle of mapped) {
          try {
            if (!active || !seriesRef.current) break;
            if (chartType === 'line' || chartType === 'area') {
              seriesRef.current.update({ time: candle.time, value: candle.close });
            } else {
              seriesRef.current.update(candle);
            }
          } catch (_) { /* silently skip duplicate/out-of-order candles */ }
        }

        if (!active) return;

        // Keep chartData state in sync so other effects (consolidations, swings) stay current
        setChartData(prev => {
          if (!prev) return latest;
          try {
            const combined = prev.candleData.concat(latest.candleData);
            const combinedVol = prev.volumeData.concat(latest.volumeData);
            return {
              candleData: prepareChartData(combined, timeframe),
              volumeData: prepareChartData(combinedVol, timeframe),
            };
          } catch (_) {
            return prev; // keep old data on any pipeline error — never crash
          }
        });
      } catch (err) {
        console.warn('[LiveTick] fetch failed:', err?.message);
      }
    })();

    return () => {
      active = false;
    };
  }, [liveTickKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const performScrollToBox = useCallback((box) => {
    const chart = chartRef.current;
    const candles = chartDataRef.current?.candleData;
    if (!chart || !candles?.length) return false;
    if (loadedContextRef.current !== `${symbol}:${timeframe}`) return false;

    const startMs = box.time_start_ms || box.timeStart;
    if (!startMs) return false;

    const targetUnix = Math.floor(startMs / 1000);
    const getUnix = (t) => typeof t === 'string' ? new Date(t + (t.length === 10 ? 'T00:00:00Z' : '')).getTime() / 1000 : Number(t);

    // Find nearest candle in current cache
    let nearestIdx = -1;
    let minDiff = Infinity;
    candles.forEach((c, i) => {
      const diff = Math.abs(getUnix(c.time) - targetUnix);
      if (diff < minDiff) { minDiff = diff; nearestIdx = i; }
    });

    const daySecs = 86400;
    if (nearestIdx === -1 || minDiff > daySecs) {
      // Out of range? Just scroll to extreme left and let data load
      chart.timeScale().scrollToPosition(-100000, true);
      return true;
    }

    // Center view: show ~80 candles around the target
    const half = 40;
    const from = Math.max(0, nearestIdx - half);
    const to   = Math.min(candles.length - 1, nearestIdx + half);

    try {
      chart.timeScale().setVisibleRange({
        from: candles[from].time,
        to:   candles[to].time,
      });
      return true;
    } catch (_) {
      return false;
    }
  }, [symbol, timeframe]);

  // ── Navigate chart to a box when FP/FN entry is clicked in Monitor ─────────
  useEffect(() => {
    const handleGotoBox = (e) => {
      const box = e.detail;
      const startMs = box.time_start_ms || box.timeStart;
      if (!box || !startMs) return;

      // Auto-switch timeframe if needed (requires parent to handle ml-change-timeframe)
      if (box.timeframe && box.timeframe.toLowerCase() !== timeframe.toLowerCase()) {
        console.log(`[ML/Nav] Timeframe mismatch: box=${box.timeframe} vs chart=${timeframe}. Switching...`);
        window.dispatchEvent(new CustomEvent('ml-change-timeframe', { 
          detail: { 
            timeframe: box.timeframe,
            originalEvent: box 
          } 
        }));
        return;
      }
      console.log(`[ML/Nav] Target box ${box.box_id} on ${timeframe}`);

      // Set highlights immediately
      setHighlightedBoxId(box.box_id);
      setSpecialHighlightedBox(box);
      setTimeout(() => {
        setHighlightedBoxId(null);
        setSpecialHighlightedBox(null);
      }, 8000); // 8s visibility

      if (loadedContextRef.current !== `${symbol}:${timeframe}`) {
        console.log(`[ML/Nav] Context mismatch (${loadedContextRef.current} vs ${symbol}:${timeframe}), storing pending scroll`);
        pendingScrollBoxRef.current = box;
        return;
      }

      // Check if target is in current candles range. If not, fetch more candles on-demand!
      const candles = chartDataRef.current?.candleData;
      let needsFetch = false;
      let requiredCount = TF_CANDLE_COUNT[timeframe] || 500;

      if (candles?.length) {
        const getUnix = (t) => typeof t === 'string' ? new Date(t + (t.length === 10 ? 'T00:00:00Z' : '')).getTime() / 1000 : Number(t);
        const firstUnix = getUnix(candles[0].time);
        const lastUnix = getUnix(candles[candles.length - 1].time);
        const targetUnix = Math.floor(startMs / 1000);

        if (targetUnix < firstUnix) {
          needsFetch = true;
          const tfSecs = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800 }[timeframe] || 300;
          const diffSecs = lastUnix - targetUnix;
          requiredCount = Math.min(5000, Math.ceil(diffSecs / tfSecs) + 150);
        }
      } else {
        needsFetch = true;
      }

      if (needsFetch) {
        console.log(`[ML/Nav] Target box is older than loaded candles. Fetching ${requiredCount} candles...`);
        setLoading(true);
        isFetchingOlderRef.current = true;
        pendingScrollBoxRef.current = box; // Ensure pending scroll is marked
        fetchLiveCandles(symbol, timeframe, requiredCount)
          .then((data) => {
            isFetchingOlderRef.current = false;
            setChartData(data);
            loadedContextRef.current = `${symbol}:${timeframe}`;
            setLoading(false);
          })
          .catch((err) => {
            console.error('[ML/Nav] Failed to fetch older candles:', err);
            isFetchingOlderRef.current = false;
            setLoading(false);
          });
      } else {
        // Try scrolling immediately
        const scrolled = performScrollToBox(box);
        if (!scrolled) {
          console.log(`[ML/Nav] Candles not loaded yet, storing pending scroll for ${box.box_id}`);
          pendingScrollBoxRef.current = box;
        } else {
          pendingScrollBoxRef.current = null;
        }
      }
    };

    window.addEventListener('ml-goto-box', handleGotoBox);
    return () => window.removeEventListener('ml-goto-box', handleGotoBox);
  }, [timeframe, symbol, performScrollToBox]);

  // Handle pending scroll to box once candles are loaded
  useEffect(() => {
    if (isFetchingOlderRef.current) {
      console.log('[ML/Nav] Delaying pending scroll because older candles are currently fetching...');
      return;
    }
    const box = pendingScrollBoxRef.current;
    if (box && loadedContextRef.current === `${symbol}:${timeframe}`) {
      const candles = chartData?.candleData;
      if (candles?.length) {
        const startMs = box.time_start_ms || box.timeStart;
        const getUnix = (t) => typeof t === 'string' ? new Date(t + (t.length === 10 ? 'T00:00:00Z' : '')).getTime() / 1000 : Number(t);
        const firstUnix = getUnix(candles[0].time);
        const lastUnix = getUnix(candles[candles.length - 1].time);
        const targetUnix = Math.floor(startMs / 1000);

        if (targetUnix < firstUnix) {
          // Needs fetch of older candles!
          const tfSecs = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800 }[timeframe] || 300;
          const diffSecs = lastUnix - targetUnix;
          const requiredCount = Math.min(5000, Math.ceil(diffSecs / tfSecs) + 150);

          console.log(`[ML/Nav] Target box is older than loaded candles. Fetching ${requiredCount} candles...`);
          setLoading(true);
          isFetchingOlderRef.current = true;
          fetchLiveCandles(symbol, timeframe, requiredCount)
            .then((data) => {
              isFetchingOlderRef.current = false;
              setChartData(data);
              loadedContextRef.current = `${symbol}:${timeframe}`;
              setLoading(false);
            })
            .catch((err) => {
              console.error('[ML/Nav] Failed to fetch older candles:', err);
              isFetchingOlderRef.current = false;
              setLoading(false);
            });
          return;
        }
      }

      console.log(`[ML/Nav] Executing pending scroll to box ${box.box_id}`);
      const scrolled = performScrollToBox(box);
      if (scrolled) {
        pendingScrollBoxRef.current = null;
      }
    }
  }, [chartData, performScrollToBox, symbol, timeframe]);

  // Structural Initialization of HTML Canvas ONLY
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return;

    if (chartRef.current) {
      try {
        chartRef.current.remove();
      } catch (e) {
        console.warn('Error removing old chart in initChart:', e);
      }
      chartRef.current = null;
    }

    // Clear indicator series refs since the chart (and all its series) is destroyed
    seriesRef.current = null;
    swingSeriesRef.current = [];
    emaHighSeriesRef.current = null;
    emaLowSeriesRef.current = null;
    consolidationPrimitiveRef.current = null;

    const container = chartContainerRef.current;
    const bg = chartSettings?.background || '#000000';
    const gridColor = chartSettings?.showGrid !== false ? (chartSettings?.gridColor || '#000000') : 'transparent';
    const crosshairMode = chartSettings?.crosshairMode === 'magnet' ? 1 : 0;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      localization: { 
        locale: 'en-IN',
        timeFormatter: (time) => {
          if (typeof time === 'string') return time;
          return new Date(time * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false, month: 'short', day: 'numeric', year: 'numeric' });
        }
      },
      layout: { background: { type: 'solid', color: bg }, textColor: chartSettings?.priceScaleColor || '#787B86', fontSize: 9, fontFamily: 'Inter, -apple-system, sans-serif' },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      crosshair: { mode: crosshairMode, vertLine: { width: 1, color: '#787B8650', style: 2, labelBackgroundColor: '#2962FF' }, horzLine: { width: 1, color: '#787B8650', style: 2, labelBackgroundColor: '#2962FF' } },
      timeScale: {
        borderColor: chartSettings?.priceScaleColor || '#2A2E39', 
        timeVisible: ['1m', '5m', '15m', '1h', '4h'].includes(timeframe),
        secondsVisible: false, rightOffset: 10, barSpacing: TF_BAR_SPACING[timeframe] || 8, minBarSpacing: 1,
        tickMarkFormatter: (time, tickMarkType, locale) => {
          if (typeof time === 'string') return time;
          const date = new Date(time * 1000);
          const parts = new Intl.DateTimeFormat('en-IN', { 
            timeZone: 'Asia/Kolkata', 
            year: 'numeric', month: 'short', day: 'numeric', 
            hour: '2-digit', minute: '2-digit', hour12: false 
          }).formatToParts(date);
          const p = {};
          parts.forEach(obj => p[obj.type] = obj.value);
          
          if (tickMarkType === 0) return p.year;
          if (tickMarkType === 1) return p.month;
          if (tickMarkType === 2) return `${p.day}`; // e.g. "15"
          return `${p.hour}:${p.minute}`;
        }
      },
      rightPriceScale: { borderColor: chartSettings?.priceScaleColor || '#2A2E39', scaleMargins: { top: 0.3, bottom: 0.3 }, mode: logScale ? 1 : 0, visible: true, borderVisible: true, autoScale: true, entireTextOnly: false, minimumWidth: 25 },
      handleScroll: { vertTouchDrag: false },
    });

    chartRef.current = chart;

    const baseUpColor = chartSettings?.upColor || '#26A69A';
    const baseDownColor = chartSettings?.downColor || '#EF5350';
    const showBody = chartSettings?.showBody !== false;
    const borderVisible = chartSettings?.showBorders !== false;
    const wickVisible = chartSettings?.showWick !== false;

    let upColor = showBody ? baseUpColor : 'rgba(0,0,0,0)';
    let downColor = showBody ? baseDownColor : 'rgba(0,0,0,0)';
    const borderUp = chartSettings?.borderUpColor || baseUpColor;
    const borderDown = chartSettings?.borderDownColor || baseDownColor;
    const wickUp = chartSettings?.wickUpColor || baseUpColor;
    const wickDown = chartSettings?.wickDownColor || baseDownColor;

    const precision = symbolPrecision;
    const minMove = 1 / Math.pow(10, precision);
    const priceFormat = { type: 'price', precision, minMove };

    let mainSeries;
    if (chartType === 'line') {
      mainSeries = chart.addSeries(LineSeries, { color: '#2962FF', lineWidth: 2, priceFormat, crosshairMarkerVisible: true, crosshairMarkerRadius: 4 });
    } else if (chartType === 'area') {
      mainSeries = chart.addSeries(AreaSeries, { topColor: 'rgba(41,98,255,0.3)', bottomColor: 'rgba(41,98,255,0.02)', lineColor: '#2962FF', lineWidth: 2, priceFormat });
    } else if (chartType === 'bar') {
      mainSeries = chart.addSeries(BarSeries, { upColor, downColor, priceFormat });
    } else if (chartType === 'hollow') {
      mainSeries = chart.addSeries(CandlestickSeries, { 
        upColor: 'rgba(0,0,0,0)', downColor, 
        borderUpColor: borderUp, borderDownColor: borderDown, 
        wickUpColor: wickUp, wickDownColor: wickDown, 
        borderVisible, wickVisible, priceFormat 
      });
    } else {
      mainSeries = chart.addSeries(CandlestickSeries, { 
        upColor, downColor, 
        borderUpColor: borderUp, borderDownColor: borderDown, 
        wickUpColor: wickUp, wickDownColor: wickDown, 
        borderVisible, wickVisible, priceFormat 
      });
    }
    seriesRef.current = mainSeries;

    // --- EMA Channel Series (High/Low) ---
    emaHighSeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(0, 255, 255, 0.65)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    emaLowSeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(255, 0, 255, 0.65)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time) {
        if (chartDataRef.current?.candleData.length > 0) onPriceUpdate?.(chartDataRef.current.candleData[chartDataRef.current.candleData.length - 1]);
        return;
      }
      const d = param.seriesData?.get(mainSeries);
      if (d) onPriceUpdate?.(d);
    });

    // Signal that a new series instance is ready (triggers swing re-draw)
    setChartKey(k => k + 1);

    chart.timeScale().subscribeVisibleLogicalRangeChange(async (logicalRange) => {
      if (!logicalRange) return;
      globalLastBarSpacing = chart.timeScale().options().barSpacing;
      
      const currentData = chartDataRef.current;
      if (currentData && currentData.candleData.length > 0) {
        const midLogical = (logicalRange.from + logicalRange.to) / 2;
        const idx = Math.max(0, Math.min(currentData.candleData.length - 1, Math.round(midLogical)));
        globalLastCenterTime = currentData.candleData[idx].time;
      }

      if (logicalRange.from < -5 && !isLoadingMoreRef.current) {
        if (!currentData || currentData.candleData.length === 0) return;
        
        isLoadingMoreRef.current = true;
        try {
          const oldestTime = currentData.candleData[0].time;
          const sym = symbolRef.current;
          const tf  = timeframeRef.current;
          const newData = await fetchLiveCandles(sym, tf, TF_CANDLE_COUNT[tf] || 500, oldestTime);
          if (newData.candleData.length > 0) {
            setChartData(prev => {
              const combinedCandles = prev.candleData.concat(newData.candleData);
              const combinedVolume  = prev.volumeData.concat(newData.volumeData);

              return {
                candleData: prepareChartData(combinedCandles, tf),
                volumeData: prepareChartData(combinedVolume, tf)
              };
            });
          }
        } catch (err) {
          console.warn('Infinite scroll fetch failed:', err?.message);
        } finally {
          setTimeout(() => { isLoadingMoreRef.current = false; }, 500);
        }
      }
    });
  }, [chartType, logScale, chartSettings, symbolPrecision, onPriceUpdate]);

  // Stagger chart canvas initialisation in multi-pane layouts so all 4 charts
  // don't create their WebGL canvas simultaneously (causes browser jank / blank panes).
  // Depends on symbolKey (not the full initChart callback) so the canvas is only
  // destroyed/rebuilt when the user explicitly switches pairs — not on every
  // chartSettings/chartType/logScale prop update.
  useEffect(() => {
    const delay = paneIndex * 120; // 0ms, 120ms, 240ms, 360ms — slightly wider gap
    let t;
    if (delay === 0) {
      initChart();
    } else {
      t = setTimeout(initChart, delay);
    }
    return () => {
      clearTimeout(t);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolKey, paneIndex]); // ← symbolKey is the only hard-reset signal

  const [consolidations, setConsolidations] = useState([]);
  const [swingLevels, setSwingLevels]       = useState([]);
  const [nnZones, setNNZones]               = useState([]);
  const [pmZones, setPMZones]               = useState([]);

  const globalZoneMap = React.useMemo(() => {
    const map = {};
    if (chartData && consolidations) {
      consolidations.forEach(z => { 
        if (z.box_id) map[z.box_id] = z; 
      });
    }
    return map;
  }, [consolidations, chartData]);

  // ── Sync shared data from parent when supplied (multi-pane mode) ─────────────
  // When ChartPage passes pre-fetched shared data, we skip internal polling entirely
  // to avoid N-pane × 4-endpoint = 16+ requests/5s hammering the backend.
  useEffect(() => {
    if (sharedConsolidations !== undefined) setConsolidations(sharedConsolidations);
  }, [sharedConsolidations]);
  useEffect(() => {
    if (sharedSwings !== undefined) setSwingLevels(sharedSwings);
  }, [sharedSwings]);
  useEffect(() => {
    if (sharedAutoLabels !== undefined) setAutoLabels(sharedAutoLabels);
  }, [sharedAutoLabels]);
  useEffect(() => {
    if (sharedNNZones !== undefined) setNNZones(sharedNNZones);
  }, [sharedNNZones]);

  // ── Internal polling — only runs when parent does NOT supply shared data ──────
  useEffect(() => {
    // Skip: parent is providing this data via props (multi-pane optimisation)
    if (sharedConsolidations !== undefined) return;

    let iv;
    const poll = async () => {
      try {
        const [cRes, sRes, aRes, nRes] = await Promise.all([
          fetch('http://localhost:8000/consolidations'),
          fetch('http://localhost:8000/swings'),
          fetch('http://localhost:8000/api/ml/quality/auto-labels'),
          fetch(`http://localhost:8000/api/nn/refined_zones?symbol=${symbol}&timeframe=${timeframe}`),
        ]);
        if (cRes.ok) {
          const d = await cRes.json();
          if (d.status === 'ok') setConsolidations(d.zones || []);
        }
        if (sRes.ok) {
          const d = await sRes.json();
          if (d.status === 'ok') setSwingLevels(d.swings || []);
        }
        if (aRes.ok) {
          const d = await aRes.json();
          setAutoLabels(d || []);
        }
        if (nRes && nRes.ok) {
          const d = await nRes.json();
          setNNZones(d || []);
        }
      } catch (_) {}
    };
    poll();
    iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, [symbol, timeframe, sharedConsolidations]);

  // ── Fetch Pattern Memory Zones from backend ───────────────────────────────
  useEffect(() => {
    let cancelled = false;
    const bareSymbol = symbol.split(':').pop().toUpperCase();
    fetch(`http://localhost:8000/api/patterns?symbol=${bareSymbol}&timeframe=${timeframe}&limit=500`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!cancelled && d?.patterns) {
          setPMZones(d.patterns);
        }
      })
      .catch(err => console.warn('[PM] Failed to fetch pattern memory zones:', err));

    return () => { cancelled = true; };
  }, [symbol, timeframe, refreshKey]);

  // ── Consolidation Boxes Drawing ───────────────────────────────────────────
  const visibleZones = React.useMemo(() => {
    if (!consolidationSettings?.enabled) return [];
    const chartTf    = timeframe.toLowerCase();
    const chartTfIdx = ALL_TFS.indexOf(chartTf);
    const showHTF    = consolidationSettings?.settings?.showHTF !== false; // default on

    return consolidations.filter(z => {
      const ztf = (z.timeframe || '').toLowerCase();
      if (!ztf) return false;

      // Chart-TF ordering rules
      if (chartTf === '5m' && ztf === '15m') return false;
      if (chartTf === '1m' && ztf === '5m')  return false;
      const ztfIdx = ALL_TFS.indexOf(ztf);
      if (ztfIdx === -1 || ztfIdx > chartTfIdx) return false;

      // HTF toggle: ztfIdx < chartTfIdx means zone is from a higher TF
      if (!showHTF && ztfIdx < chartTfIdx) return false;

      // IST Session Filter (00:00 to 06:00 IST): For chart <= 1h
      // IST is UTC +5:30 (19800000 ms)
      if (chartTfIdx >= 3 && z.timeStart) {
        const istTime = z.timeStart + 19800000;
        const hr = new Date(istTime).getUTCHours();
        if (hr >= 0 && hr < 6) return false;
      }

      return true;
    });
  }, [consolidations, timeframe, consolidationSettings?.enabled, consolidationSettings?.settings?.showHTF]);


  // Keep the raw parsed zones so we can filter them dynamically on scroll
  const rawParsedZonesRef = useRef({ curr: [], htf: [] });

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !chartDataRef.current?.candleData?.length) return;
    if (!consolidationSettings?.enabled && !specialHighlightedBox) return;

    if (!consolidationPrimitiveRef.current) {
      consolidationPrimitiveRef.current = new ConsolidationBoxesPrimitive();
      series.attachPrimitive(consolidationPrimitiveRef.current);
    }

    const candles  = chartDataRef.current.candleData;
    const getUnix  = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);
    const lastUnix = getUnix(candles[candles.length - 1].time);
    const chartTfIdx = ALL_TFS.indexOf(timeframe.toLowerCase());

    const zones = visibleZones;
    if (!zones.length && !specialHighlightedBox) {
      if (consolidationPrimitiveRef.current) {
        consolidationPrimitiveRef.current.setData([]);
      }
      activeBoxesRef.current = [];
      rawParsedZonesRef.current = { curr: [], htf: [] };
      return;
    }

    const unixArr    = candles.map(c => getUnix(c.time));
    const bisectLeft = (arr, target) => {
      let lo = 0, hi = arr.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (arr[mid] < target) lo = mid + 1; else hi = mid; }
      return lo;
    };
    const snapToChart = (unixSec) => {
      if (!unixArr.length) return null;
      const idx = bisectLeft(unixArr, unixSec);
      if (idx === 0) return candles[0].time;
      if (idx >= unixArr.length) return candles[candles.length - 1].time;
      const before = unixArr[idx - 1], after = unixArr[idx];
      return (unixSec - before <= after - unixSec) ? candles[idx - 1].time : candles[idx].time;
    };

    const parsedCurr = [];
    const parsedHtf = [];

    zones.forEach(zone => {
      const ztfIdx = ALL_TFS.indexOf((zone.timeframe || '').toLowerCase());
      const isHTF  = ztfIdx < chartTfIdx;

      const startUnix = Math.floor(zone.timeStart / 1000);
      const endUnix   = Math.floor(zone.timeEnd   / 1000);

      const t1 = snapToChart(startUnix);
      const t2 = endUnix >= lastUnix ? candles[candles.length - 1].time : snapToChart(endUnix);
      if (!t1 || !t2 || t1 === t2) return;

      const s1 = Math.min(getUnix(t1), getUnix(t2));
      const s2 = Math.max(getUnix(t1), getUnix(t2));

      const lo     = bisectLeft(unixArr, s1);
      const hi     = bisectLeft(unixArr, s2 + 1);
      const points = candles.slice(lo, hi).map(c => c.time);
      if (points.length < 2) return;

      if (points.length < 2) return;

      const hasLabel  = zone.label != null;
      const score     = zone.score || {};
      const isFb      = score.is_fallback !== false;
      const pGood     = !isFb ? ((score.probabilities?.good || 0) + (score.probabilities?.very_good || 0)) : null;

      let borderColor, fillColor, isDashed = false;
      let aiLabel = null;

      if (!isFb && score.probabilities) {
        const p = score.probabilities;
        const maxScore = Math.max(p.very_good || 0, p.good || 0, p.bad || 0, p.very_bad || 0);
        if (maxScore === p.very_good) aiLabel = 'very_good';
        else if (maxScore === p.good) aiLabel = 'good';
        else if (maxScore === p.bad) aiLabel = 'bad';
        else aiLabel = 'very_bad';
        
        // Save the argmax label back into score for LabelDialog to consume easily
        score.aiLabel = aiLabel;
      }

      if (hasLabel) {
        if (zone.label === 'very_good') { borderColor = 'rgba(0,191,165,0.85)';  fillColor = 'rgba(0,191,165,0.12)'; }
        else if (zone.label === 'good') { borderColor = 'rgba(38,166,154,0.85)'; fillColor = 'rgba(38,166,154,0.12)'; }
        else if (zone.label === 'bad')  { borderColor = 'rgba(239,83,80,0.85)';  fillColor = 'rgba(239,83,80,0.12)'; }
        else                            { borderColor = 'rgba(211,47,47,0.85)';  fillColor = 'rgba(211,47,47,0.12)'; }
      } else if (aiLabel) {
        isDashed = true;
        if (aiLabel === 'very_good') { borderColor = 'rgba(0,191,165,0.85)';  fillColor = 'rgba(0,191,165,0.12)'; }
        else if (aiLabel === 'good') { borderColor = 'rgba(38,166,154,0.85)'; fillColor = 'rgba(38,166,154,0.12)'; }
        else if (aiLabel === 'bad')  { borderColor = 'rgba(239,83,80,0.85)';  fillColor = 'rgba(239,83,80,0.12)'; }
        else                         { borderColor = 'rgba(211,47,47,0.85)';  fillColor = 'rgba(211,47,47,0.12)'; }
      } else {
        borderColor = 'rgba(144, 202, 249, 0.85)';
        fillColor   = 'rgba(144, 202, 249, 0.15)';
      }

      // Map Auto-Labels (for status marker)
      const al = autoLabels.find(l => l.box_id === zone.box_id);

      // ── Structural Classification Mapping ──
      if (zone.type === 'TIGHT') {
        borderColor = 'rgba(76, 175, 80, 0.95)';
        fillColor   = 'rgba(76, 175, 80, 0.08)';
      } else if (zone.type === 'LOOSE') {
        borderColor = 'rgba(255, 235, 59, 0.95)';
        fillColor   = 'rgba(255, 235, 59, 0.08)';
      } else if (zone.type === 'DRIFT') {
        borderColor = 'rgba(255, 152, 0, 0.95)';
        fillColor   = 'rgba(255, 152, 0, 0.08)';
      }

      const boxDef = {
        box_id:      zone.box_id,
        t1:          points[0],
        t2:          points[points.length - 1],
        drawT1:      points[0],
        drawT2:      points[points.length - 1],
        priceHigh:   zone.priceHigh,
        priceLow:    zone.priceLow,
        borderColor,
        fillColor,
        isDashed,
        highlighted: zone.box_id === highlightedBoxId,
        s1, s2,
        startIndex:  lo,
        endIndex:    hi - 1,
        autoLabel:   al,
        type:        zone.type,
        score:       zone.score
      };

      if (isHTF) parsedHtf.push(boxDef);
      else parsedCurr.push(boxDef);
    });

    rawParsedZonesRef.current = { curr: parsedCurr, htf: parsedHtf };

    // --- Dynamic Windowing Handler ---
    const updateVisibleBoxes = () => {
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range) return;

      const limitTarget = (arr, maxCount) => {
        if (arr.length <= maxCount) return arr;
        // logical range typically maps to indices in the candle array
        const startIdx = Math.max(0, Math.floor(range.from));
        const endIdx   = Math.min(candles.length - 1, Math.ceil(range.to));
        
        const visStartUnix = getUnix(candles[startIdx]?.time || candles[0].time);
        const visEndUnix   = getUnix(candles[endIdx]?.time || candles[candles.length - 1].time);

        // Filter boxes that intersect with the visible range
        let visible = arr.filter(b => b.s1 <= visEndUnix && b.s2 >= visStartUnix);
        
        // If there are more visible than the max, slice the most recent
        if (visible.length > maxCount) {
          visible = visible.slice(visible.length - maxCount);
        } else if (visible.length < maxCount) {
          // If we have budget left, fill with adjacent closest chronological boxes
          const result = [...visible];
          let remainder = maxCount - visible.length;
          // grab boxes immediately to the left of the screen, working backwards
          const idxBefore = arr.findIndex(b => b === visible[0]);
          if (idxBefore > 0) {
            const takeLeft = Math.min(remainder, idxBefore);
            result.unshift(...arr.slice(idxBefore - takeLeft, idxBefore));
          }
          return result;
        }
        return visible;
      };

      const finalCurr = limitTarget(rawParsedZonesRef.current.curr, 30);
      const finalHtf  = limitTarget(rawParsedZonesRef.current.htf, 30);
      const finalSet = [...finalCurr, ...finalHtf];

      const withHighlights = finalSet.map(b => ({
        ...b,
        highlighted: b.box_id === highlightedBoxId
      }));
      
      // If we have a special highlight from Monitor, ensure it's in the list even if not from server
      if (specialHighlightedBox && !withHighlights.some(b => b.box_id === specialHighlightedBox.box_id)) {
          const tStart = specialHighlightedBox.time_start_ms || specialHighlightedBox.timeStart;
          const tEnd   = specialHighlightedBox.time_end_ms   || specialHighlightedBox.timeEnd;
          const tStartSec = tStart / 1000;
          const tEndSec   = tEnd / 1000;
          withHighlights.push({
              ...specialHighlightedBox,
              t1: mapOverlayTime(tStartSec, timeframe),
              t2: mapOverlayTime(tEndSec, timeframe),
              drawT1: tStartSec,
              drawT2: tEndSec,
              priceHigh: specialHighlightedBox.price_high || specialHighlightedBox.priceHigh,
              priceLow:  specialHighlightedBox.price_low  || specialHighlightedBox.priceLow,
              borderColor: '#2962FF',
              fillColor: '#2962FF10',
              highlighted: true
          });
      }

      consolidationPrimitiveRef.current.setData(withHighlights);
      
      const nextActive = withHighlights.filter(b => b.box_id);
      activeBoxesRef.current = nextActive;
      
      // Update DOM components strictly only when the identity of active boxes changes
      // to avoid 60fps React rendering loops
      const currentIds = domZonesRef.current.map(b => b.box_id).join(',');
      const nextIds = nextActive.map(b => b.box_id).join(',');
      
      if (currentIds !== nextIds) {
        domZonesRef.current = nextActive;
        setDomZones(nextActive);
      }
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(updateVisibleBoxes);
    updateVisibleBoxes(); // initial run

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(updateVisibleBoxes);
      activeBoxesRef.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consolidations, timeframe, chartKey, consolidationSettings?.enabled, consolidationSettings?.settings?.showHTF, highlightedBoxId, specialHighlightedBox]);

  // ── AI Mode: Separate overlay (does NOT interfere with indicator boxes) ──────
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !chartDataRef.current?.candleData?.length) return;

    if (!aiMode) {
      // Remove AI layer if toggled off
      if (aiPrimitiveRef.current) {
        try { series.detachPrimitive(aiPrimitiveRef.current); } catch (_) {}
        aiPrimitiveRef.current = null;
      }
      return;
    }

    // Build the AI-filtered zone list from ALL consolidations (ignoring indicator settings)
    const chartTf    = timeframe.toLowerCase();
    const chartTfIdx = ALL_TFS.indexOf(chartTf);

    const aiZones = consolidations.filter(z => {
      const ztf = (z.timeframe || '').toLowerCase();
      const ztfIdx = ALL_TFS.indexOf(ztf);
      if (ztfIdx === -1 || ztfIdx > chartTfIdx) return false;
      if (!z.score || z.score.is_fallback) return false;
      const p = z.score.probabilities || {};
      const maxScore = Math.max(p.very_good || 0, p.good || 0, p.bad || 0, p.very_bad || 0);
      return (maxScore === p.very_good || maxScore === p.good) && maxScore >= 0.6;
    });

    if (!aiPrimitiveRef.current) {
      aiPrimitiveRef.current = new ConsolidationBoxesPrimitive();
      series.attachPrimitive(aiPrimitiveRef.current);
    }

    const candles  = chartDataRef.current.candleData;
    const getUnix  = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);
    const lastUnix = getUnix(candles[candles.length - 1].time);
    const unixArr  = candles.map(c => getUnix(c.time));
    const bisectLeft = (arr, target) => {
      let lo = 0, hi = arr.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (arr[mid] < target) lo = mid + 1; else hi = mid; }
      return lo;
    };
    const snapToChart = (unixSec) => {
      if (!unixArr.length) return null;
      const idx = bisectLeft(unixArr, unixSec);
      if (idx === 0) return candles[0].time;
      if (idx >= unixArr.length) return candles[candles.length - 1].time;
      const before = unixArr[idx - 1], after = unixArr[idx];
      return (unixSec - before <= after - unixSec) ? candles[idx - 1].time : candles[idx].time;
    };

    const aiBoxDefs = [];
    aiZones.forEach(zone => {
      const startUnix = Math.floor(zone.timeStart / 1000);
      const endUnix   = Math.floor(zone.timeEnd   / 1000);
      const t1 = snapToChart(startUnix);
      const t2 = endUnix >= lastUnix ? candles[candles.length - 1].time : snapToChart(endUnix);
      if (!t1 || !t2 || t1 === t2) return;

      const s1 = Math.min(getUnix(t1), getUnix(t2));
      const s2 = Math.max(getUnix(t1), getUnix(t2));
      const lo = bisectLeft(unixArr, s1);
      const hi = bisectLeft(unixArr, s2 + 1);
      const points = candles.slice(lo, hi).map(c => c.time);
      if (points.length < 2) return;

      const p  = zone.score.probabilities || {};
      const vg = (p.very_good || 0);
      const g  = (p.good      || 0);
      const maxPClass = vg > g ? 'very_good' : 'good';
      const borderColor = maxPClass === 'very_good'
        ? 'rgba(0,230,180,0.95)'
        : 'rgba(41,182,246,0.95)';
      const fillColor = maxPClass === 'very_good'
        ? 'rgba(0,230,180,0.08)'
        : 'rgba(41,182,246,0.08)';

      aiBoxDefs.push({
        box_id:      `ai_${zone.box_id}`,
        t1:          points[0],
        t2:          points[points.length - 1],
        drawT1:      points[0],
        drawT2:      points[points.length - 1],
        priceHigh:   zone.priceHigh,
        priceLow:    zone.priceLow,
        borderColor,
        fillColor,
        isDashed:    false,
        s1, s2,
      });
    });

    aiPrimitiveRef.current.setData(aiBoxDefs);

    return () => {
      if (aiPrimitiveRef.current) {
        try { series.detachPrimitive(aiPrimitiveRef.current); } catch (_) {}
        aiPrimitiveRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consolidations, timeframe, chartKey, aiMode]);

  // ── NN Mode: Specialized refined boxes ─────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !chartDataRef.current?.candleData?.length) return;

    console.log('[NN] Effect triggered', { nnMode, nnEnabled: neuralSettings?.enabled, zoneCount: nnZones.length });

    if (!nnMode && !neuralSettings?.enabled) {
      if (nnPrimitiveRef.current) {
        try { series.detachPrimitive(nnPrimitiveRef.current); } catch (_) {}
        nnPrimitiveRef.current = null;
      }
      return;
    }

    if (!nnPrimitiveRef.current) {
      nnPrimitiveRef.current = new ConsolidationBoxesPrimitive();
      series.attachPrimitive(nnPrimitiveRef.current);
    }

    const candles  = chartDataRef.current.candleData;
    const getUnix  = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);
    const lastUnix = getUnix(candles[candles.length - 1].time);
    const unixArr  = candles.map(c => getUnix(c.time));
    const bisectLeft = (arr, target) => {
      let lo = 0, hi = arr.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (arr[mid] < target) lo = mid + 1; else hi = mid; }
      return lo;
    };
    const snapToChart = (unixSec) => {
      if (!unixArr.length) return null;
      const idx = bisectLeft(unixArr, unixSec);
      if (idx === 0) return candles[0].time;
      if (idx >= unixArr.length) return candles[candles.length - 1].time;
      const before = unixArr[idx - 1], after = unixArr[idx];
      return (unixSec - before <= after - unixSec) ? candles[idx - 1].time : candles[idx].time;
    };

    const nnBoxDefs = [];
    nnZones.forEach(zone => {
      if (!zone.nn_box) return;
      
      const box = zone.nn_box;
      // Handle seconds vs milliseconds
      const parseT = (t) => {
        let val = Number(t);
        if (val < 1e11) val *= 1000;
        return Math.floor(val / 1000);
      };
      const startUnix = parseT(box.timeStart);
      const endUnix   = parseT(box.timeEnd);
      const t1 = snapToChart(startUnix);
      const t2 = endUnix >= lastUnix ? candles[candles.length - 1].time : snapToChart(endUnix);
      if (!t1 || !t2 || t1 === t2) return;

      const s1 = Math.min(getUnix(t1), getUnix(t2));
      const s2 = Math.max(getUnix(t1), getUnix(t2));
      const lo = bisectLeft(unixArr, s1);
      const hi = bisectLeft(unixArr, s2 + 1);
      const points = candles.slice(lo, hi).map(c => c.time);
      if (points.length < 2) return;

      nnBoxDefs.push({
        box_id:      `nn_${zone.box_id}`,
        t1:          points[0],
        t2:          points[points.length - 1],
        drawT1:      points[0],
        drawT2:      points[points.length - 1],
        priceHigh:   box.priceHigh,
        priceLow:    box.priceLow,
        borderColor: '#29B6F6',
        fillColor:   'rgba(41, 182, 246, 0.15)',
        isDashed:    true,
        s1, s2,
      });
    });

    nnPrimitiveRef.current.setData(nnBoxDefs);

    return () => {
      if (nnPrimitiveRef.current) {
        try { series.detachPrimitive(nnPrimitiveRef.current); } catch (_) {}
        nnPrimitiveRef.current = null;
      }
    };
  }, [nnZones, timeframe, chartKey, nnMode, neuralSettings]);

  // ── Pattern Memory (PM) Mode: Render saved patterns from DB ─────────────────
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !chartDataRef.current?.candleData?.length) return;

    if (!pmMode) {
      if (pmPrimitiveRef.current) {
        try { series.detachPrimitive(pmPrimitiveRef.current); } catch (_) {}
        pmPrimitiveRef.current = null;
      }
      return;
    }

    if (!pmPrimitiveRef.current) {
      pmPrimitiveRef.current = new ConsolidationBoxesPrimitive();
      series.attachPrimitive(pmPrimitiveRef.current);
    }

    const candles  = chartDataRef.current.candleData;
    const getUnix  = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);
    const lastUnix = getUnix(candles[candles.length - 1].time);
    const unixArr  = candles.map(c => getUnix(c.time));
    const bisectLeft = (arr, target) => {
      let lo = 0, hi = arr.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (arr[mid] < target) lo = mid + 1; else hi = mid; }
      return lo;
    };
    const snapToChart = (unixSec) => {
      if (!unixArr.length) return null;
      const idx = bisectLeft(unixArr, unixSec);
      if (idx === 0) return candles[0].time;
      if (idx >= unixArr.length) return candles[candles.length - 1].time;
      const before = unixArr[idx - 1], after = unixArr[idx];
      return (unixSec - before <= after - unixSec) ? candles[idx - 1].time : candles[idx].time;
    };

    const pmBoxDefs = [];
    pmZones.forEach(zone => {
      const startUnix = Math.floor(zone.box_time_start / 1000);
      const endUnix   = Math.floor(zone.box_time_end   / 1000);
      const t1 = snapToChart(startUnix);
      const t2 = endUnix >= lastUnix ? candles[candles.length - 1].time : snapToChart(endUnix);
      if (!t1 || !t2 || t1 === t2) return;

      const s1 = Math.min(getUnix(t1), getUnix(t2));
      const s2 = Math.max(getUnix(t1), getUnix(t2));
      const lo = bisectLeft(unixArr, s1);
      const hi = bisectLeft(unixArr, s2 + 1);
      const points = candles.slice(lo, hi).map(c => c.time);
      if (points.length < 2) return;

      pmBoxDefs.push({
        box_id:      `pm_${zone.box_id}`,
        t1:          points[0],
        t2:          points[points.length - 1],
        drawT1:      points[0],
        drawT2:      points[points.length - 1],
        priceHigh:   zone.price_high || zone.priceHigh,
        priceLow:    zone.price_low  || zone.priceLow,
        borderColor: '#AB47BC', // Purple
        fillColor:   'rgba(171, 71, 188, 0.15)',
        isDashed:    true,
        s1, s2,
        highlighted: zone.box_id === highlightedBoxId
      });
    });

    pmPrimitiveRef.current.setData(pmBoxDefs);

    return () => {
      if (pmPrimitiveRef.current) {
        try { series.detachPrimitive(pmPrimitiveRef.current); } catch (_) {}
        pmPrimitiveRef.current = null;
      }
    };
  }, [pmZones, timeframe, chartKey, pmMode, highlightedBoxId]);

  // ── Sync HTML Overlays to Chart Coordinates ────────────────────────────────
  useEffect(() => {
    let handle;
    const syncOverlays = () => {
      const chart = chartRef.current;
      const series = seriesRef.current;
      if (!chart || !series) {
        handle = requestAnimationFrame(syncOverlays);
        return;
      }

      const timeScale   = chart.timeScale();
      const chartWidth  = chart.timeScale().width();   // visible chart pixel width

      activeBoxesRef.current.forEach(box => {
        const el = document.getElementById(`mlbox-${box.box_id}`);
        if (!el) return;

        try {
          const mappedT1 = mapOverlayTime(box.drawT1, timeframe);
          const mappedT2 = mapOverlayTime(box.drawT2, timeframe);
          let x1 = timeScale.timeToCoordinate(mappedT1);
          let x2 = timeScale.timeToCoordinate(mappedT2);

          // Clamp off-screen edges to viewport boundaries so the label
          // remains visible as long as any part of the box is on screen.
          const LEFT_EDGE  = 0;
          const RIGHT_EDGE = chartWidth;

          // Both edges off the same side → box entirely off-screen → hide
          if (
            (x1 !== null && x2 !== null && x1 < LEFT_EDGE  && x2 < LEFT_EDGE) ||
            (x1 !== null && x2 !== null && x1 > RIGHT_EDGE && x2 > RIGHT_EDGE)
          ) {
            if (el.dataset.lastDisplay !== 'none') {
              el.style.display = 'none';
              el.dataset.lastDisplay = 'none';
            }
            return;
          }

          // Clamp nulls and out-of-bounds edges
          if (x1 === null) x1 = LEFT_EDGE;
          if (x2 === null) x2 = RIGHT_EDGE;
          x1 = Math.max(LEFT_EDGE,  Math.min(RIGHT_EDGE, x1));
          x2 = Math.max(LEFT_EDGE,  Math.min(RIGHT_EDGE, x2));

          const midX = (x1 + x2) / 2;
          const topY = series.priceToCoordinate(box.priceHigh);

          if (topY !== null) {
            if (el.dataset.lastDisplay !== 'block') {
              el.style.display = 'block';
              el.dataset.lastDisplay = 'block';
            }
            
            // Anchor neatly above the box center, shifted further up to prevent blocking candles
            const newTransform = `translate(calc(${midX}px - 50%), calc(${topY}px - 100% - 20px))`;
            if (el.dataset.lastTransform !== newTransform) {
              el.style.transform = newTransform;
              el.dataset.lastTransform = newTransform;
            }
          } else {
            if (el.dataset.lastDisplay !== 'none') {
              el.style.display = 'none';
              el.dataset.lastDisplay = 'none';
            }
          }
        } catch (_) {
          if (el.dataset.lastDisplay !== 'none') {
            el.style.display = 'none';
            el.dataset.lastDisplay = 'none';
          }
        }
      });
      handle = requestAnimationFrame(syncOverlays);
    };
    handle = requestAnimationFrame(syncOverlays);
    return () => cancelAnimationFrame(handle);
  }, []);




  // ── Swing Levels Drawing ──────────────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    swingSeriesRef.current.forEach(s => { try { chart?.removeSeries(s); } catch {} });
    swingSeriesRef.current = [];

    if (!chart || !chartDataRef.current?.candleData?.length || !swingSettings?.enabled) return;

    const candles    = chartDataRef.current.candleData;
    const settings   = swingSettings.settings || {};
    const tfSettings = settings.tfs || {};
    const getUnix    = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);
    const normTf     = (tf) => tf.toLowerCase();

    // Pre-build sorted unix array for O(log N) binary search
    const unixArr    = candles.map(c => getUnix(c.time));
    const bisectLeft = (arr, target) => {
      let lo = 0, hi = arr.length;
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (arr[mid] < target) lo = mid + 1; else hi = mid; }
      return lo;
    };

    // RULE 1: only show swing if its TF <= chart TF (same or higher timeframe, not lower)
    const chartTfIdx = ALL_TFS.indexOf(normTf(timeframe));
    const enabledTfs = Object.entries(tfSettings)
      .filter(([, cfg]) => cfg.enabled !== false)
      .map(([tf]) => tf);

    const relevantSwings = swingLevels.filter(sw => {
      const swTf = normTf(sw.timeframe);
      if (enabledTfs.length > 0 && !enabledTfs.includes(swTf)) return false;
      
      const chartTf = normTf(timeframe);
      if (chartTf === '5m' && swTf === '15m') return false;
      if (chartTf === '1m' && swTf === '5m') return false;
      
      const swTfIdx = ALL_TFS.indexOf(swTf);
      // swTfIdx <= chartTfIdx: 1h(3) on 15m(4) → 3<=4 ✓ | 1h(3) on 4h(2) → 3<=2 ✗
      return swTfIdx !== -1 && swTfIdx <= chartTfIdx;
    });

    // RULE 2 – HTF DOMINANCE: if an LTF swing is within 0.02% of an HTF swing price,
    // suppress the LTF swing entirely (HTF line wins at that level).
    // HTF = lower ALL_TFS index (e.g. '1h' idx=3 beats '5m' idx=5).
    const PROX_PCT = 0.0002; // 0.02% proximity threshold
    // Build set of HTF prices per type (type → array of prices)
    const htfPrices = { high: [], low: [] };
    for (const sw of relevantSwings) {
      const idx = ALL_TFS.indexOf(normTf(sw.timeframe));
      if (idx < chartTfIdx) {              // strictly higher TF than chart
        htfPrices[sw.type]?.push(sw.price);
      }
    }
    const isNearHTF = (price, type) =>
      (htfPrices[type] || []).some(p => Math.abs(price - p) / p < PROX_PCT);

    const dedupedSwings = relevantSwings.filter(sw => {
      const idx = ALL_TFS.indexOf(normTf(sw.timeframe));
      if (idx === chartTfIdx) return true;
      if (idx < chartTfIdx) return true;
      return !isNearHTF(sw.price, sw.type);
    });

    // Backend already computed 3+3 per TF. Just render active unmitigated + mitigated.
    dedupedSwings.forEach(sw => {
      // Skip unmitigated non-active swings (backend omits them, but guard here too)
      // active → extend to latest | inactive unmitigated → 5-bar stub | mitigated → showMitigated toggle
      if (sw.mitigated && !(settings.showMitigated ?? false)) return;

      const color     = tfSettings[normTf(sw.timeframe)]?.color || TF_COLORS[normTf(sw.timeframe)] || '#888';
      const swUnixSec = Math.floor(sw.time_ms / 1000);

      const startIdx = bisectLeft(unixArr, swUnixSec);
      if (startIdx >= candles.length) return;

      // 3-state line length:
      // active unmitigated   → extend to latest candle
      // inactive unmitigated → short 5-bar stub at pivot
      // mitigated            → terminate at mitigation candle
      let endIdx;
      if (sw.active) {
        endIdx = candles.length - 1;
      } else if (!sw.mitigated) {
        // short stub: pivot candle + next 5 bars
        endIdx = Math.min(startIdx + 5, candles.length - 1);
      } else {
        // mitigated: scan for fill candle
        endIdx = candles.length - 1;
        let movedAway = false;
        for (let i = startIdx + 1; i < candles.length; i++) {
          const c = candles[i];
          if (sw.type === 'high') {
            if (!movedAway && c.low  < sw.price)  movedAway = true;
            if ( movedAway && c.high >= sw.price) { endIdx = i; break; }
          } else {
            if (!movedAway && c.high > sw.price)   movedAway = true;
            if ( movedAway && c.low  <= sw.price)  { endIdx = i; break; }
          }
        }
      }

      const pts = candles.slice(startIdx, endIdx + 1).map(c => ({
        time:  mapOverlayTime(normalizeTimeForChart(getUnix(c.time), timeframe), timeframe),
        value: sw.price,
      }));
      if (pts.length < 2) return;

      try {
        const s = chart.addSeries(LineSeries, {
          color, lineWidth: 1, lineStyle: 0,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          autoscaleInfoProvider: () => null,
        });
        s.setData(pts);
        swingSeriesRef.current.push(s);
      } catch (_) {}
    });

    return () => {
      swingSeriesRef.current.forEach(s => { try { chartRef.current?.removeSeries(s); } catch {} });
      swingSeriesRef.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [swingLevels, timeframe, chartKey, swingSettings?.enabled, swingSettings?.settings, swingSettings?.settings?.showMitigated]);


  // Seamless Data Updates
  useEffect(() => {
    if (!chartData || chartData.candleData.length === 0 || !seriesRef.current) return;
    
    const chart = chartRef.current;
    if (!chart) return;

    // Determine if series is empty prior to adding data
    const isFirstLoad = seriesRef.current.data().length === 0;

    const candleData = prepareChartData(chartData.candleData, timeframe);

    if (!Array.isArray(candleData)) return;
    if (candleData.length === 0) {
      seriesRef.current.setData([]);
      return;
    }

    if (chartType === 'line' || chartType === 'area') {
      seriesRef.current.setData(candleData.map(d => ({ time: d.time, value: d.close })));
    } else {
      seriesRef.current.setData(candleData);
    }

    // --- Update EMA Channel Data ---
    if (emaHighSeriesRef.current) {
      emaHighSeriesRef.current.setData(
        candleData
          .filter(d => typeof d.emaHigh === 'number')
          .map(d => ({ time: d.time, value: d.emaHigh }))
      );
    }
    if (emaLowSeriesRef.current) {
      emaLowSeriesRef.current.setData(
        candleData
          .filter(d => typeof d.emaLow === 'number')
          .map(d => ({ time: d.time, value: d.emaLow }))
      );
    }

    onPriceUpdate?.(candleData[candleData.length - 1]);

    if (isFirstLoad) {
      if (pendingScrollBoxRef.current || isFetchingOlderRef.current) {
        // Skip default zoom reset to let the pending scroll hook handle the zoom/scroll
        console.log('[ChartWidget] Skipping default zoom reset because a pending scroll or fetch is active');
      } else if (initialBars) {
        // Explicit override (e.g. canvas charts)
        chart.timeScale().setVisibleLogicalRange({
          from: candleData.length - initialBars,
          to: candleData.length + 3
        });
      } else if (isSubchart) {
        chart.timeScale().setVisibleLogicalRange({ 
          from: candleData.length - 45, 
          to: candleData.length + 3 
        });
      } else {
        // if (globalLastBarSpacing && globalLastCenterTime) {
        //   chart.timeScale().applyOptions({ barSpacing: globalLastBarSpacing });
        //   ...
        if (false) { // Disabled global restoration to prevent zoom fighting
          
          let centerIdx = candleData.length - 1;
          let lo = 0, hi = candleData.length - 1;
          
          const gt = typeof globalLastCenterTime === 'string' ? new Date(globalLastCenterTime).getTime()/1000 : globalLastCenterTime;
          
          while (lo <= hi) {
            const mid = (lo + hi) >>> 1;
            const ct = typeof candleData[mid].time === 'string' ? new Date(candleData[mid].time).getTime()/1000 : candleData[mid].time;
            if (ct < gt) lo = mid + 1;
            else if (ct > gt) hi = mid - 1;
            else { centerIdx = mid; break; }
          }
          if (lo > hi) centerIdx = Math.min(candleData.length - 1, lo);
          
          const containerWidth = chartContainerRef.current?.clientWidth || 800;
          const logicalWidth = containerWidth / globalLastBarSpacing;
          
          chart.timeScale().setVisibleLogicalRange({
            from: centerIdx - (logicalWidth / 2),
            to: centerIdx + (logicalWidth / 2)
          });

        } else {
          const initBars = 300;
          if (candleData.length > initBars) {
            chart.timeScale().setVisibleLogicalRange({ from: candleData.length - initBars, to: candleData.length + 3 });
          } else {
            chart.timeScale().fitContent();
          }
        }
      }
    }
  // chartKey is incremented by initChart after each canvas rebuild — adding it here
  // ensures data is re-applied to the new seriesRef whenever the canvas is recreated
  // (e.g. after a pair switch stagger fires for panes 1/2/3).
  }, [chartData, chartKey, chartType, timeframe, onPriceUpdate]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-Sampler: Capture Focused Canvas Screenshots for Refinement Training ──
  useEffect(() => {
    if (loading || error || !chartRef.current || !['5m', '15m', '1h'].includes(timeframe)) return;

    const captureInterval = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/training/needs_screenshot?symbol=${symbol}&timeframe=${timeframe}`);
        const data = await res.json();
        if (data.status === 'ok' && data.boxes?.length > 0) {
          const chart = chartRef.current;
          const timeScale = chart.timeScale();
          
          for (const box of data.boxes) {
            // Find this box in our local activeBoxes state (mapped by indicator)
            const localBox = activeBoxesRef.current.find(b => b.box_id === box.box_id);
            if (localBox) {
              // 1. Determine if the box is actually visible on screen right now
              const range = timeScale.getVisibleLogicalRange();
              if (!range) continue;
              if (localBox.startIndex > range.to || localBox.endIndex < range.from) continue;

              console.log(`[AutoSampler] Background capture for box: ${box.box_id}`);

              // 2. Background Capture Logic
              const offscreenCapture = async () => {
                const container = document.createElement('div');
                container.style.width = '1200px';
                container.style.height = '600px';
                container.style.position = 'absolute';
                container.style.top = '-9999px';
                document.body.appendChild(container);

                let offChart = null;
                try {
                  offChart = createChart(container, {
                    width: 1200, height: 600,
                    layout: { background: { color: '#000000' }, textColor: '#D1D4DC' },
                    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
                    timeScale: { visible: false, borderVisible: false },
                    priceScale: { borderVisible: false },
                    handleScroll: false, handleScale: false,
                  });

                  const offSeries = offChart.addCandlestickSeries({
                    upColor: '#26A69A', downColor: '#EF5350',
                    borderVisible: false, wickVisible: true,
                  });

                  const candles = chartDataRef.current?.candleData;
                  if (!candles) throw new Error('No candles');

                  const cleaned = prepareChartData(candles, timeframe);
                  offSeries.setData(cleaned);

                  const offPrimitive = new ConsolidationBoxesPrimitive();
                  offSeries.attachPrimitive(offPrimitive);
                  offPrimitive.setData([{
                    ...localBox,
                    borderColor: 'rgba(255, 235, 59, 0.9)',
                    fillColor: 'rgba(255, 235, 59, 0.1)',
                    highlighted: true
                  }]);

                  const fromIdx = Math.max(0, localBox.startIndex - 5);
                  const toIdx = Math.min(cleaned.length - 1, localBox.endIndex + 5);
                  
                  offChart.timeScale().setVisibleRange({
                    from: cleaned[fromIdx].time,
                    to: cleaned[toIdx].time
                  });

                  // Force auto-scale for vertical fit
                  offChart.priceScale().applyOptions({ autoScale: true });

                  await new Promise(r => setTimeout(r, 600)); // Buffer for layout

                  const canvas = offChart.takeScreenshot();
                  const b64 = canvas.toDataURL('image/png');

                  await fetch('http://localhost:8000/api/training/upload_screenshot', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ box_id: box.box_id, screenshot_b64: b64 })
                  });

                  console.log(`[AutoSampler] Background capture uploaded: ${box.box_id}`);
                } catch (err) {
                  console.warn(`[AutoSampler] Background capture failed for ${box.box_id}:`, err);
                } finally {
                  if (offChart) {
                    try {
                      offChart.remove();
                    } catch (e) {
                      console.warn('Error removing offscreen chart:', e);
                    }
                  }
                  if (document.body.contains(container)) {
                    document.body.removeChild(container);
                  }
                }
              };

              offscreenCapture();
              break; 
            }
          }
        }
      } catch (err) {
        console.warn('[AutoSampler] Focused capture failed:', err);
      }
    }, 12000); // Check every 12s

    return () => clearInterval(captureInterval);
  }, [symbol, timeframe, loading, error]);

  const handleResetView = useCallback(() => { chartRef.current?.timeScale().scrollToRealTime(); }, []);

  useEffect(() => {
    const handleResize = () => {
      try {
        if (chartRef.current && chartContainerRef.current) {
          chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth, height: chartContainerRef.current.clientHeight });
        }
      } catch (err) {
        console.warn('[ChartWidget] resize error:', err);
      }
    };
    window.addEventListener('resize', handleResize);
    const ro = new ResizeObserver(handleResize);
    if (chartContainerRef.current) ro.observe(chartContainerRef.current);
    return () => {
      window.removeEventListener('resize', handleResize);
      ro.disconnect();
      if (chartRef.current) {
        try {
          chartRef.current.remove();
        } catch (e) {
          console.warn('[ChartWidget] error removing chart on unmount:', e);
        }
        chartRef.current = null;
      }
    };
  }, []);

  return (
    <div className="w-full h-full relative">
      {loading && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#000000]">
          <div className="w-8 h-8 border-2 border-[#2962FF] border-t-transparent rounded-full animate-spin mb-3" />
          <span className="text-[#787B86] text-[12px]">Loading live data…</span>
        </div>
      )}
      {error && !loading && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#000000]">
          <span className="text-[#EF5350] text-[13px] mb-1">{error}</span>
          <span className="text-[#787B86] text-[11px]">Make sure the backend is running on port 8000</span>
        </div>
      )}
      <div ref={chartContainerRef} className="w-full h-full" />
      
      {/* Absolute Box Label Overlays */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden z-30">
        {domZones.map(zone => {
          if (!zone.box_id) return null;
          return (
            <div 
              key={zone.box_id} 
              id={`mlbox-${zone.box_id}`}
              className={`absolute top-0 left-0 transition-opacity duration-200 ${zone.highlighted ? 'opacity-100' : 'opacity-60'} hover:opacity-100 focus-within:opacity-100`}
              style={{ display: 'none', pointerEvents: 'auto', transformOrigin: 'bottom center' }}
            >
              <LabelDialog 
                zone={globalZoneMap[zone.box_id] || zone} 
                onLabeled={({ label, comment }) => {
                  setConsolidations(prev => prev.map(z => 
                    z.box_id === zone.box_id 
                      ? { ...z, label, comment } 
                      : z
                  ));
                }}
              />
            </div>
          );
        })}
      </div>

      {!loading && !error && (
        <button
          onClick={handleResetView}
          className={`absolute ${isSubchart ? 'bottom-2 right-2' : 'bottom-6 left-1/2 -translate-x-1/2'} z-20 flex items-center gap-1.5 ${isSubchart ? 'px-2 py-1' : 'px-3 py-1.5'} bg-[#1E222D] hover:bg-[#2A2E39] text-[#D1D4DC] hover:text-white border border-[#363A45] rounded-full shadow-lg transition-all active:scale-95 group`}
          title="Back to Latest"
        >
          <ChevronsRight size={isSubchart ? 10 : 14} className="group-hover:translate-x-0.5 transition-transform" />
        </button>
      )}
    </div>
  );
});

ChartWidget.displayName = 'ChartWidget';
export default ChartWidget;
