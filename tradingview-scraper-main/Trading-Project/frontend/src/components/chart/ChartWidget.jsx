import React, { useEffect, useRef, useCallback, useState, forwardRef, useImperativeHandle } from 'react';
import { createChart, CandlestickSeries, LineSeries, AreaSeries, BarSeries, BaselineSeries } from 'lightweight-charts';
import { fetchLiveCandles } from '../../data/chartData';
import { ChevronsRight } from 'lucide-react';
import {
  aggregateCandles, detectSwings, getHigherTfs, ALL_TFS,
  normalizeTimeForChart, TF_COLORS, FILLED_COLOR,
} from '../../lib/swingLevels';

// Sensible number of bars to fetch per timeframe so candles are visible at the initial zoom
const TF_CANDLE_COUNT = {
  '1m':  300,
  '5m':  600,  // 600 × 5m = 50h — covers full overnight + weekend gaps
  '15m': 400,
  '30m': 400,
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
  '30m': 7,
  '1h':  8,
  '4h':  8,
  '1d':  8,
  '1w':  10,
  '1M':  14,
};

const sortAndDedupe = (data) => {
  if (!data || data.length === 0) return [];
  const sorted = [...data].sort((a, b) => {
    const ta = typeof a.time === 'string' ? a.time : Number(a.time);
    const tb = typeof b.time === 'string' ? b.time : Number(b.time);
    if (ta < tb) return -1;
    if (ta > tb) return 1;
    return 0;
  });
  const result = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i].time !== sorted[i - 1].time) result.push(sorted[i]);
  }
  return result;
};

// Fast O(1) merge for live tick appending (skips sorting entirely if strictly newer)
const fastMergeSort = (older, newer) => {
  if (!older?.length) return newer;
  if (!newer?.length) return older;

  const lastOld = older[older.length - 1].time;
  const firstNew = newer[0].time;

  // Optimized append-only
  if (firstNew > lastOld) return older.concat(newer);
  
  // Optimized single-item overwrite
  if (newer.length === 1 && newer[0].time === lastOld) {
    const copy = [...older];
    copy[copy.length - 1] = newer[0];
    return copy;
  }

  // Fallback map + sort for messy overlap (scroll loading)
  const map = new Map();
  for (let i = 0; i < older.length; i++) map.set(older[i].time, older[i]);
  for (let i = 0; i < newer.length; i++) map.set(newer[i].time, newer[i]);
  
  const merged = Array.from(map.values());
  merged.sort((a, b) => {
    const ta = typeof a.time === 'string' ? a.time : Number(a.time);
    const tb = typeof b.time === 'string' ? b.time : Number(b.time);
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });
  return merged;
};

const ChartWidget = forwardRef(({ symbol, timeframe, chartType, onPriceUpdate, logScale, chartSettings, refreshKey, symbolPrecision = 4, swingSettings, consolidationSettings, liveTickKey, isSubchart, initialBars, showMLDebug, onMLDebugZones, minMLScore = 0, drawBoxMode = false, showModelBoxes = false }, ref) => {
  const chartContainerRef      = useRef(null);
  const chartRef               = useRef(null);
  const seriesRef              = useRef(null);
  const isLoadingMoreRef       = useRef(false);
  const swingSeriesRef         = useRef([]); // swing level LineSeries
  const consolidationSeriesRef = useRef([]); // consolidation box series
  const [chartKey, setChartKey] = useState(0); // increments when chart is re-initialised

  // ML overlay refs
  const mlOverlayRef          = useRef(null);  // DOM div for score labels
  const mlTooltipRef          = useRef(null);  // DOM div for hover tooltip
  const mlZonesRef            = useRef([]);     // active zone data for current TF

  // User feedback state — keyed by box_id (persisted to localStorage)
  const [userFeedback, setUserFeedback]   = useState(() => {
    try { return JSON.parse(localStorage.getItem('ml_user_feedback')) || {}; }
    catch (_) { return {}; }
  });
  const userFeedbackRef                   = useRef({});
  userFeedbackRef.current                 = userFeedback;
  
  const [patternFeedback, setPatternFeedback] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('ml_pattern_feedback')) || {};
    } catch (_) { return {}; }
  });
  const patternFeedbackRef                = useRef({});
  patternFeedbackRef.current              = patternFeedback;
  
  const pendingRatings                    = useRef(new Set()); // guard against duplicate POSTs
  const [ratingPopup, setRatingPopup]     = useState(null); // {box_id, x, y, zone}
  const ratingPopupTimer                  = useRef(null);
  
  // Track last active / hovering box for keyboard shortcuts
  const activeBoxRef                      = useRef(null);
  const activeZoneRef                     = useRef(null);

  // ── Detection system state ──────────────────────────────────────────────
  const [detectionPopup, setDetectionPopup]     = useState(null); // {box_id, x, y, zone, source}
  const [detectionFeedback, setDetectionFeedback] = useState({});  // keyed by box_id
  const modelBoxSeriesRef                       = useRef([]);       // lightweight-charts series for model boxes
  const [modelBoxes, setModelBoxes]             = useState([]);
  // draw tool
  const drawStartRef                            = useRef(null);     // {price, time, x, y}
  const drawPreviewRef                          = useRef(null);     // DOM div for preview rectangle
  const drawOverlayRef                          = useRef(null);     // transparent capture layer
  const detectionPopupTimerRef                  = useRef(null);
  const pendingDetectionRef                     = useRef(new Set());

  const [chartData, setChartData] = useState(null);
  const chartDataRef = useRef(null);
  chartDataRef.current = chartData;

  const chartTypeRef = useRef(chartType);
  chartTypeRef.current = chartType;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useImperativeHandle(ref, () => ({
    getChart: () => chartRef.current,
    getSeries: () => seriesRef.current,
    getContainer: () => chartContainerRef.current,
    getChartContainer: () => chartContainerRef.current,
    getConsolidations: () => mlZonesRef.current,
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

  // ── Fetch live candles whenever symbol, timeframe, or refreshKey changes ─
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

    fetchLiveCandles(symbol, timeframe, TF_CANDLE_COUNT[timeframe] || 500)
      .then((data) => {
        if (!cancelled) {
          setChartData(data);
          setLoading(false);
          hasDataRef.current = true;
        }
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
  }, [symbol, timeframe, refreshKey, retryCount]);

  useEffect(() => {
    if (!error) return;
    const retryDelay = error.includes('Fetching initial') ? 8000 : null;
    if (!retryDelay) return;
    const t = setTimeout(() => setRetryCount(c => c + 1), retryDelay);
    return () => clearTimeout(t);
  }, [error]);

  // ── Live Polling: Fetch latest candles synchronized by ChartPage ──
  useEffect(() => {
    // Skip if chart or data isn't ready yet; liveTickKey=0 means no tick fired yet
    if (loading || error || !chartData || typeof liveTickKey === 'undefined') return;

    (async () => {
      try {
        const latest = await fetchLiveCandles(symbol, timeframe, 50);
        if (!latest || latest.candleData.length === 0) return;

        const newCandles = latest.candleData;

        // Fast path: if only the last candle changed, update in-place (no flicker)
        if (seriesRef.current && chartDataRef.current?.candleData?.length > 0) {
          const prevLast = chartDataRef.current.candleData[chartDataRef.current.candleData.length - 1];
          const isSimpleUpdate = newCandles.length <= 3 &&
            newCandles.every(c => c.time >= prevLast.time);

          if (isSimpleUpdate) {
            // Update series in-place — no full setData, no flicker
            try {
              newCandles.forEach(c => {
                const point = (chartTypeRef.current === 'line' || chartTypeRef.current === 'area')
                  ? { time: c.time, value: c.close }
                  : c;
                seriesRef.current.update(point);
              });
            } catch (_) {}
            // Merge into state so scroll-back history stays consistent
            setChartData(prev => {
              if (!prev) return latest;
              return {
                candleData: fastMergeSort(prev.candleData, newCandles),
                volumeData: fastMergeSort(prev.volumeData, latest.volumeData),
              };
            });
            return;
          }
        }

        // Slow path: full merge + setData (catches overnight gaps, new candles, etc.)
        setChartData(prev => {
          if (!prev) return latest;
          return {
            candleData: fastMergeSort(prev.candleData, newCandles),
            volumeData: fastMergeSort(prev.volumeData, latest.volumeData),
          };
        });
      } catch (err) {
        console.warn('Live fetch failed:', err?.message);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveTickKey]);

  // Structural Initialization of HTML Canvas ONLY
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    // Clear indicator series refs since the chart (and all its series) is destroyed
    swingSeriesRef.current = [];
    consolidationSeriesRef.current = [];

    const container = chartContainerRef.current;
    const bg = chartSettings?.background || '#131722';
    const gridColor = chartSettings?.showGrid !== false ? (chartSettings?.gridColor || '#1E222D') : 'transparent';
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
      grid: { vertLines: { color: gridColor, style: 1 }, horzLines: { color: gridColor, style: 1 } },
      crosshair: { mode: crosshairMode, vertLine: { width: 1, color: '#787B8650', style: 2, labelBackgroundColor: '#2962FF' }, horzLine: { width: 1, color: '#787B8650', style: 2, labelBackgroundColor: '#2962FF' } },
      timeScale: {
        borderColor: chartSettings?.priceScaleColor || '#2A2E39', 
        timeVisible: ['1m', '5m', '15m', '30m', '1h', '4h'].includes(timeframe),
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

    let upColor = showBody ? baseUpColor : 'transparent';
    let downColor = showBody ? baseDownColor : 'transparent';
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
        upColor: 'transparent', downColor, 
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
      if (logicalRange.from < -5 && !isLoadingMoreRef.current) {
        const currentData = chartDataRef.current;
        if (!currentData || currentData.candleData.length === 0) return;
        
        isLoadingMoreRef.current = true;
        try {
          const oldestTime = currentData.candleData[0].time;
          const newData = await fetchLiveCandles(symbol, timeframe, TF_CANDLE_COUNT[timeframe] || 500, oldestTime);
          if (newData.candleData.length > 0) {
            setChartData(prev => ({ 
              candleData: fastMergeSort(newData.candleData, prev.candleData), 
              volumeData: fastMergeSort(newData.volumeData, prev.volumeData) 
            }));
          }
        } finally {
          setTimeout(() => { isLoadingMoreRef.current = false; }, 500);
        }
      }
    });
  }, [chartType, logScale, chartSettings, timeframe, symbol, symbolPrecision, onPriceUpdate]);

  useEffect(() => { initChart(); }, [initChart]);

  // ── Fetch Consolidation Zones + Swing Levels from backend ─────────────────
  const [consolidations, setConsolidations] = useState([]);
  const [mlHealth, setMlHealth]             = useState(null);
  const [swingLevels, setSwingLevels]       = useState([]);

  useEffect(() => {
    let iv;
    const poll = async () => {
      try {
        const [cRes, sRes] = await Promise.all([
          fetch('http://localhost:8000/consolidations'),
          fetch('http://localhost:8000/swings'),
        ]);
        if (cRes.ok) {
          const d = await cRes.json();
          if (d.status === 'ok') {
            const incoming = d.zones || [];
            if (d.ml_health) setMlHealth(d.ml_health);
            setConsolidations(prev => {
              if (prev.length === incoming.length &&
                  (incoming.length === 0 || prev[0]?.box_id === incoming[0]?.box_id)) return prev;
              return incoming;
            });
          }
        }
        if (sRes.ok) {
          const d = await sRes.json();
          if (d.status === 'ok') {
            const incoming = d.swings || [];
            setSwingLevels(prev => {
              if (prev.length === incoming.length &&
                  (incoming.length === 0 || prev[0]?.id === incoming[0]?.id)) return prev;
              return incoming;
            });
          }
        }
      } catch (_) {}
    };
    poll();
    iv = setInterval(poll, 15000);
    return () => clearInterval(iv);
  }, []);

  // ── Consolidation Boxes Drawing ───────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    consolidationSeriesRef.current.forEach(s => { try { chart?.removeSeries(s); } catch {} });
    consolidationSeriesRef.current = [];

    if (!chart || !chartDataRef.current?.candleData?.length || !consolidationSettings?.enabled) return;

    const candles  = chartDataRef.current.candleData;
    const getUnix  = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);
    const normTf   = (tf) => tf.toLowerCase();
    const lastUnix = getUnix(candles[candles.length - 1].time);
    const chartTf  = normTf(timeframe);

    // ── Settings-driven multi-TF filter ─────────────────────────────────────────
    // ALL_TFS = ['1w','1d','4h','1h','15m','5m','1m']
    // → lower index = HIGHER timeframe, higher index = LOWER timeframe
    const cbSettings = consolidationSettings?.settings || {};
    const showSameTF   = cbSettings.showSameTF   !== false;  // default true
    const showHigherTF = cbSettings.showHigherTF  !== false;  // default true
    const tfOverrides  = cbSettings.tfOverrides  || {};

    const chartTfIdx = ALL_TFS.indexOf(chartTf);
    const zones = consolidations.filter(z => {
      const ztf    = normTf(z.timeframe);
      const ztfIdx = ALL_TFS.indexOf(ztf);
      if (ztfIdx === -1) return false;

      // LTF boxes NEVER shown on HTF charts (hard-locked)
      // LTF = higher index than chart TF
      if (ztfIdx > chartTfIdx) return false;

      // Per-TF override wins over group setting
      if (ztf in tfOverrides) return !!tfOverrides[ztf];

      // Group logic
      // Same TF = same index
      if (ztfIdx === chartTfIdx) return showSameTF;
      // HTF = lower index (e.g. 1d idx=1 < 1h idx=3)
      return showHigherTF;
    });
    if (!zones.length) return;

    // Pre-build sorted unix-second array once — reused for all O(log N) lookups
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

    // Store active zones for this TF in ref (for overlay + debug panel)
    // Apply minMLScore filter (only affects rendering — backend sends all zones)
    const filteredZones = minMLScore > 0
      ? zones.filter(z => {
          const ML_ACTIVE = new Set(['active', 'degraded', 'invalid_model']);
          if (!ML_ACTIVE.has((z.ml_status || 'inactive'))) return true; // show inactive zones always
          return (z.ml_score || 0) >= minMLScore;
        })
      : zones;

    mlZonesRef.current = filteredZones;
    if (onMLDebugZones) onMLDebugZones(filteredZones);

    filteredZones.forEach(zone => {
      const startUnix = Math.floor(zone.timeStart / 1000);
      const endUnix   = Math.floor(zone.timeEnd   / 1000);

      const t1 = snapToChart(startUnix);
      const t2 = endUnix >= lastUnix ? candles[candles.length - 1].time : snapToChart(endUnix);
      if (!t1 || !t2 || t1 === t2) return;

      // ── Use just 2 anchor points per box instead of full candle slice ──
      // This cuts the data-points-per-series from O(N) to O(1)
      const pts = [t1, t2];

      try {
        const ML_ACTIVE   = new Set(['active', 'degraded', 'feature_drift', 'invalid_input']);
        const mlStatus    = zone.ml_status || 'inactive';
        
        let customBorder = zone.ml_border;
        let customFill = zone.ml_fill;
        if (mlStatus === 'invalid_input') { customBorder = '#9e9e9e'; customFill = 'rgba(158,158,158,0.1)' }
        else if (mlStatus === 'feature_drift') { customBorder = '#bd93f9'; customFill = 'rgba(189,147,249,0.15)' }
        else if (mlStatus === 'version_mismatch' || mlStatus === 'degraded') { customBorder = '#FFB86C'; customFill = 'rgba(255,184,108,0.1)' }

        const borderColor = (ML_ACTIVE.has(mlStatus) && customBorder)
          ? customBorder : 'rgba(144,202,249,0.85)';
        const fillColor   = (ML_ACTIVE.has(mlStatus) && customFill)
          ? customFill  : 'rgba(144,202,249,0.06)';
        const lineStyle   = mlStatus === 'invalid_input' ? 2 : 0; // Dashed for invalid

        // Top border
        const topLine = chart.addSeries(LineSeries, {
          color: borderColor, lineWidth: 1, lineStyle,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        topLine.setData(pts.map(t => ({ time: t, value: zone.priceHigh })));

        // Bottom border
        const botLine = chart.addSeries(LineSeries, {
          color: borderColor, lineWidth: 1, lineStyle,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        botLine.setData(pts.map(t => ({ time: t, value: zone.priceLow })));

        // Fill between priceHigh and priceLow using BaselineSeries
        // baseValue = priceLow  →  data value = priceHigh
        // topFill covers the entire zone from top to bottom, no bottomFill
        const fillArea = chart.addSeries(BaselineSeries, {
          baseValue:         { type: 'price', price: zone.priceLow },
          topLineColor:      'transparent',
          topFillColor1:     fillColor,
          topFillColor2:     fillColor,
          bottomLineColor:   'transparent',
          bottomFillColor1:  'transparent',
          bottomFillColor2:  'transparent',
          lineWidth:         0,
          priceLineVisible:  false,
          lastValueVisible:  false,
          crosshairMarkerVisible: false,
        });
        fillArea.setData(pts.map(t => ({ time: t, value: zone.priceHigh })));

        consolidationSeriesRef.current.push(topLine, botLine, fillArea);
      } catch (e) {
        // ignore per-box errors silently
      }
    });

    return () => {
      consolidationSeriesRef.current.forEach(s => { try { chartRef.current?.removeSeries(s); } catch {} });
      consolidationSeriesRef.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consolidations, timeframe, chartKey, consolidationSettings?.enabled]);


  // ── ML Score Label Overlay (DOM chips, positioned in screen space) ──────────
  // Re-renders only when consolidations or chart zoom changes — NOT per tick
  useEffect(() => {
    const chart   = chartRef.current;
    const overlay = mlOverlayRef.current;
    if (!overlay) return;

    const renderChips = () => {
      if (!chart || !consolidationSettings?.enabled) {
        overlay.innerHTML = '';
        return;
      }
      const ts = chart.timeScale();
      const zones = mlZonesRef.current;
      const series = seriesRef.current;
      if (!zones.length || !series) return;

      const candles = chartDataRef.current?.candleData;
      if (!candles?.length) return;

      const getUnix = (t) => typeof t === 'string' ? new Date(t).getTime() / 1000 : Number(t);

      let html = '';
      zones.forEach((zone, i) => {
        // Only render chip when scorer is fully active
        // invalid_model / inactive / feature_error → no chip, no score shown
        const ML_ACTIVE = new Set(['active', 'degraded', 'invalid_model']);
        const mlStatus = zone.ml_status || 'inactive';
        if (!ML_ACTIVE.has(mlStatus)) return;
        if (zone.ml_score == null) return;

        // Map the zone's end-time to an x-pixel, priceHigh to a y-pixel
        try {
          const endUnix = Math.floor(zone.timeEnd / 1000);
          const lastUnix = getUnix(candles[candles.length - 1].time);
          const chartEndUnix = endUnix >= lastUnix ? lastUnix : endUnix;

          const xCoord = ts.timeToCoordinate(chartEndUnix);
          const yCoord = series.priceToCoordinate(zone.priceHigh);
          if (xCoord == null || yCoord == null) return;

          const label  = zone.ml_label || 'NEUTRAL';
          const score  = (zone.ml_score * 100).toFixed(0);
          const bgMap  = { GOOD: '#0d3730', BAD: '#3b0d0d', NEUTRAL: '#1a2035' };
          const txMap  = { GOOD: '#26A69A', BAD: '#EF5350', NEUTRAL: '#90CAF9' };
          
          let bg = bgMap[label] || bgMap.NEUTRAL;
          let tx = txMap[label] || txMap.NEUTRAL;
          if (mlStatus === 'invalid_input') { bg = '#333333'; tx = '#9e9e9e'; }
          else if (mlStatus === 'feature_drift') { bg = '#2d1b4d'; tx = '#bd93f9'; }
          else if (mlStatus === 'version_mismatch' || mlStatus === 'degraded') { bg = '#332b00'; tx = '#FFB86C'; }

          // Agreement icon suffix (✓ / ⚠) or unrated dot (•)
          const storedFb = userFeedbackRef.current[zone.box_id] || zone.user_label;
          let agreementSuffix = `<span style="color:#787B86;margin-left:3px;font-size:12px;line-height:0.8">•</span>`;
          if (storedFb) {
            agreementSuffix = storedFb === label
              ? `<span style="color:#26A69A;margin-left:3px">✓</span>`
              : `<span style="color:#FFB86C;margin-left:3px">⚠</span>`;
          }

          // Pattern: prefer ML classifier prediction, fall back to user-labeled pattern_type
          const resolvedPattern = zone.pattern_prediction || zone.pattern_type || null;
          let patternSuffix = '';
          if (resolvedPattern === 'CONTINUATION') patternSuffix = ' <span style="margin-left:2px">➡️</span>';
          else if (resolvedPattern === 'LIQUIDITY_GRAB') patternSuffix = ' <span style="margin-left:2px">🎯</span>';

          html += `<div data-zone="${i}" style="
            position:absolute;
            left:${xCoord - 2}px;
            top:${yCoord - 18}px;
            transform:translateX(-100%);
            display:flex;gap:3px;align-items:center;
            background:${bg};border:1px solid ${tx}40;
            border-radius:4px;padding:1px 5px;
            font-size:9px;font-family:Inter,sans-serif;
            color:${tx};pointer-events:auto;cursor:default;
            white-space:nowrap;z-index:30;
            ">${score}% <span style="opacity:0.8">${label}</span>${agreementSuffix}${patternSuffix}</div>`;
        } catch (_) {}
      });
      overlay.innerHTML = html;
    };

    // Render once immediately
    renderChips();

    // Throttle pan/zoom re-renders with rAF to avoid layout thrashing
    const chart2 = chartRef.current;
    if (!chart2) return;
    let rafId = null;
    const throttled = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => { rafId = null; renderChips(); });
    };
    const unsub = chart2.timeScale().subscribeVisibleLogicalRangeChange(throttled);
    return () => {
      try { chart2.timeScale().unsubscribeVisibleLogicalRangeChange(throttled); } catch (_) {}
      if (rafId) cancelAnimationFrame(rafId);
      if (overlay) overlay.innerHTML = '';
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consolidations, chartKey, consolidationSettings?.enabled, showMLDebug, minMLScore]);


  // ── ML Hover Tooltip (crosshair-driven) ───────────────────────────────────
  useEffect(() => {
    const chart  = chartRef.current;
    const tooltip = mlTooltipRef.current;
    if (!chart || !tooltip) return;

    const handler = (param) => {
      if (!param?.point || !param.time) {
        tooltip.style.display = 'none';
        return;
      }

      const zones  = mlZonesRef.current;
      const series = seriesRef.current;
      if (!zones.length || !series) return;

      const priceAtCursor = series.coordinateToPrice(param.point.y);
      if (!priceAtCursor) { tooltip.style.display = 'none'; return; }

      const cursorUnix = typeof param.time === 'number' ? param.time : 0;

      const hit = zones.find(zone => {
        // Only hit-test zones where ML is active — invalid/inactive show no tooltip features
        const ML_ACTIVE = new Set(['active', 'degraded', 'invalid_model']);
        const mlStatus = zone.ml_status || 'inactive';
        if (!ML_ACTIVE.has(mlStatus)) return false;
        const startUnix = Math.floor(zone.timeStart / 1000);
        const endUnix   = Math.floor(zone.timeEnd   / 1000);
        return priceAtCursor >= zone.priceLow
          && priceAtCursor <= zone.priceHigh
          && cursorUnix    >= startUnix
          && cursorUnix    <= endUnix;
      });

      if (!hit) { tooltip.style.display = 'none'; return; }

      const label  = hit.ml_label || 'NEUTRAL';
      const score  = ((hit.ml_score || 0.5) * 100).toFixed(1);
      const conf   = ((hit.ml_confidence || 0) * 100).toFixed(0);
      const txMap  = { GOOD: '#26A69A', BAD: '#EF5350', NEUTRAL: '#90CAF9' };
      const mlStatus = hit.ml_status || 'inactive';
      let tx     = txMap[label] || txMap.NEUTRAL;
      if (mlStatus === 'invalid_input') tx = '#9e9e9e';
      else if (mlStatus === 'feature_drift') tx = '#bd93f9';
      else if (mlStatus === 'version_mismatch' || mlStatus === 'degraded') tx = '#FFB86C';

      // ── Top-3 feature contributions (v4 pred_contribs) ──────────────────
      const topFeats = (hit.ml_top_features || []).slice(0, 3);
      const maxImpact = topFeats.reduce((m, f) => Math.max(m, Math.abs(f.impact)), 0) || 1;

      const featHtml = topFeats.length > 0
        ? `<div style="border-top:1px solid #2A2E39;padding-top:6px;margin-top:4px">
            <div style="font-size:8px;color:#4A4E59;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px">Why</div>
            ${topFeats.map(f => {
              const isPos  = f.impact >= 0;
              const color  = isPos ? '#26A69A' : '#EF5350';
              const sign   = isPos ? '+' : '';
              const barPct = Math.round(Math.abs(f.impact) / maxImpact * 80);
              return `<div style="margin-bottom:4px">
                <div style="display:flex;justify-content:space-between;font-size:9px;margin-bottom:2px">
                  <span style="color:#A0A4B0">${f.name}</span>
                  <span style="color:${color};font-family:monospace">${sign}${f.impact.toFixed(4)}</span>
                </div>
                <div style="height:2px;background:#2A2E39;border-radius:1px">
                  <div style="width:${barPct}%;height:100%;background:${color};border-radius:1px"></div>
                </div>
              </div>`;
            }).join('')}
          </div>`
        : '';

      // Pattern: prefer ML classifier, fall back to deterministic suggestion
      const resolvedHitPattern = hit.pattern_prediction || hit.pattern_suggestion || null;
      const patternConfPct = hit.pattern_confidence ? Math.round(hit.pattern_confidence * 100) : null;
      const isMLPatternHit = !!hit.pattern_prediction;
      const patternEmoji = resolvedHitPattern === 'CONTINUATION' ? '➡️' : resolvedHitPattern === 'LIQUIDITY_GRAB' ? '🎯' : '';
      const patternColor = resolvedHitPattern === 'CONTINUATION' ? '#26A69A' : '#FFB86C';

      const dirEmoji = hit.breakout_direction === 'bullish' ? '↑' : hit.breakout_direction === 'bearish' ? '↓' : '';
      const structBg  = { 'HH-HL':'#26A69A22','LL-LH':'#EF535022','HH-LH':'#FFB86C22','LL-HL':'#FFB86C22' }[hit.structure_type] || 'transparent';
      const structClr = { 'HH-HL':'#26A69A','LL-LH':'#EF5350','HH-LH':'#FFB86C','LL-HL':'#FFB86C' }[hit.structure_type] || '#787B86';

      tooltip.innerHTML = `
        <div style="font-weight:700;color:${tx};margin-bottom:3px;font-size:11px">${mlStatus !== 'active' ? mlStatus.toUpperCase() : label} — ${score}%</div>
        <div style="color:#787B86;font-size:9px;margin-bottom:2px">Confidence: ${conf}%</div>
        ${hit.ml_debug?.imputation ? `<div style="color:#FFB86C;font-size:9px;margin-bottom:4px">Imputed: ${hit.ml_debug.imputation.count} feats (${hit.ml_debug.imputation.features.join(', ')})</div>` : ''}
        ${hit.ml_debug?.missing_features?.length ? `<div style="color:#EF5350;font-size:9px;margin-bottom:4px">Missing: ${hit.ml_debug.missing_features.join(', ')}</div>` : ''}
        ${hit.structure_type ? `<div style="display:inline-flex;align-items:center;gap:4px;font-size:8px;padding:1px 5px;border-radius:3px;background:${structBg};color:${structClr};margin-bottom:4px;font-weight:600">${dirEmoji} ${hit.structure_type}${hit.swing_count ? ` · ${hit.swing_count} swings` : ''}</div>` : ''}
        ${resolvedHitPattern ? `<div style="color:${patternColor};font-size:9px;margin-bottom:4px;font-weight:600">${patternEmoji} ${resolvedHitPattern}${isMLPatternHit && patternConfPct ? ` <span style="opacity:0.6;font-size:8px">(ML ${patternConfPct}%)</span>` : !isMLPatternHit ? ` <span style="opacity:0.5;font-size:8px">(structural)</span>` : ''}</div>` : ''}
        ${featHtml}
      `;

      // Keep track of hover for keyboard shortcuts
      activeBoxRef.current = hit.box_id;
      activeZoneRef.current = hit;

      const container = chart.chartElement ? chart.chartElement() : null;
      const cw = container?.clientWidth || 9999;
      const ch = container?.clientHeight || 9999;
      const tipW = 200, tipH = 120;
      const x = (param.point.x + 14 + tipW > cw) ? param.point.x - tipW - 6 : param.point.x + 14;
      const y = (param.point.y + 14 + tipH > ch) ? param.point.y - tipH - 6 : param.point.y + 14;
      tooltip.style.left    = `${x}px`;
      tooltip.style.top     = `${y}px`;
      tooltip.style.display = 'block';
    };

    chart.subscribeCrosshairMove(handler);
    return () => {
      try { chart.unsubscribeCrosshairMove(handler); } catch (_) {}
      if (tooltip) tooltip.style.display = 'none';
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartKey, consolidationSettings?.enabled]);


  // ── User Rating Popup (subscribeClick) ────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;

    const handler = (param) => {
      if (!param?.point) return;

      const zones  = mlZonesRef.current;
      const priceAtCursor = series.coordinateToPrice(param.point.y);
      if (!priceAtCursor) return;
      const cursorUnix = typeof param.time === 'number' ? param.time : 0;

      const hit = zones.find(zone => {
        const ML_ACTIVE = new Set(['active', 'degraded', 'invalid_model']);
        const mlStatus = zone.ml_status || 'inactive';
        if (!ML_ACTIVE.has(mlStatus)) return false;
        if (!zone.box_id) return false;
        const startUnix = Math.floor(zone.timeStart / 1000);
        const endUnix   = Math.floor(zone.timeEnd   / 1000);
        return priceAtCursor >= zone.priceLow
          && priceAtCursor <= zone.priceHigh
          && cursorUnix    >= startUnix
          && cursorUnix    <= endUnix;
      });

      if (!hit) {
        setRatingPopup(null);
        return;
      }

      // Position popup near cursor within the container
      setRatingPopup({
        box_id: hit.box_id,
        zone:   hit,
        x: param.point.x + 16,
        y: param.point.y - 28,
      });

      // Popup stays open until user acts — no auto-dismiss
      clearTimeout(ratingPopupTimer.current);
    };

    chart.subscribeClick(handler);
    return () => { try { chart.unsubscribeClick(handler); } catch (_) {} };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartKey, consolidationSettings?.enabled]);

  const handleUserRating = useCallback(async (box_id, user_label, zone) => {
    if (pendingRatings.current.has(box_id)) return; // prevent duplicate clicks

    // 1) Update local state + localStorage immediately (optimistic)
    const next = { ...userFeedbackRef.current, [box_id]: user_label };
    setUserFeedback(next);
    try { localStorage.setItem('ml_user_feedback', JSON.stringify(next)); } catch (_) {}

    // 2) Dismiss popup
    setRatingPopup(null);
    clearTimeout(ratingPopupTimer.current);

    // 3) Send to backend — include timeframe so DB row is TF-aware
    const tf = zone?.timeframe || ratingPopup?.zone?.timeframe || activeZoneRef.current?.timeframe || null;
    pendingRatings.current.add(box_id);
    try {
      const res = await fetch('http://localhost:8000/api/ml/feedback/user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ box_id, user_label, timeframe: tf }),
      });
      if (res.ok) {
        window.dispatchEvent(new CustomEvent('mlDebugRefresh'));
      }
    } catch (_) { // backend offline ok
    } finally {
      pendingRatings.current.delete(box_id);
    }
  }, [ratingPopup]);

  const handlePatternRating = useCallback(async (box_id, ptype) => {
    if (pendingRatings.current.has(`${box_id}_pattern`)) return;

    // 1) Update local state + localStorage immediately (optimistic)
    const next = { ...patternFeedbackRef.current, [box_id]: ptype };
    setPatternFeedback(next);
    try { localStorage.setItem('ml_pattern_feedback', JSON.stringify(next)); } catch (_) {}

    // 2) Dismiss popup
    setRatingPopup(null);
    clearTimeout(ratingPopupTimer.current);

    // 3) Send to backend
    pendingRatings.current.add(`${box_id}_pattern`);
    try {
      const res = await fetch('http://localhost:8000/api/ml/feedback/pattern', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ box_id, pattern_type: ptype }),
      });
      if (res.ok) {
        window.dispatchEvent(new CustomEvent('mlDebugRefresh'));
      }
    } catch (_) {
    } finally {
      pendingRatings.current.delete(`${box_id}_pattern`);
    }
  }, []);

  // ── Keyboard shortcuts for rating (G / B / N) ────────────────────────
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Don't trigger if user is typing in an input
      if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;
      
      const key = e.key.toLowerCase();
      // Use either the popup's box_id or the last hovered box_id
      const targetBoxId = ratingPopup?.box_id || activeBoxRef.current;
      
      if (!targetBoxId) return;

      if (key === 'g') handleUserRating(targetBoxId, 'GOOD');
      if (key === 'b') handleUserRating(targetBoxId, 'BAD');
      if (key === 'n') handleUserRating(targetBoxId, 'NEUTRAL');
      if (key === 'c') handlePatternRating(targetBoxId, 'CONTINUATION');
      if (key === 'l') handlePatternRating(targetBoxId, 'LIQUIDITY_GRAB');
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleUserRating, ratingPopup]);


  // ── Detection Feedback Handler ──────────────────────────────────────────
  const handleDetectionFeedback = useCallback(async (box_id, label) => {
    if (pendingDetectionRef.current.has(box_id)) return;
    setDetectionFeedback(prev => ({ ...prev, [box_id]: label }));
    setDetectionPopup(null);
    clearTimeout(detectionPopupTimerRef.current);
    pendingDetectionRef.current.add(box_id);
    try {
      await fetch('http://localhost:8000/api/detection/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ box_id, detection_label: label }),
      });
    } catch (_) {}
    finally { pendingDetectionRef.current.delete(box_id); }
  }, []);

  // ── Detection keyboard shortcuts (R / W / I) ───────────────────────────
  useEffect(() => {
    const handleKD = (e) => {
      if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;
      const key = e.key.toLowerCase();
      const bid = detectionPopup?.box_id || activeBoxRef.current;
      if (!bid) return;
      if (key === 'r') handleDetectionFeedback(bid, 'RIGHT');
      if (key === 'w') handleDetectionFeedback(bid, 'WRONG');
      if (key === 'i') handleDetectionFeedback(bid, 'IGNORE');
    };
    window.addEventListener('keydown', handleKD);
    return () => window.removeEventListener('keydown', handleKD);
  }, [handleDetectionFeedback, detectionPopup]);

  // ── Model Boxes: fetch + draw on DOM overlay ─────────────────────────────
  useEffect(() => {
    if (!showModelBoxes || !chartRef.current) return;
    let cancelled = false;
    fetch(`http://localhost:8000/api/detection/model_boxes?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&candles=500`)
      .then(r => r.json())
      .then(data => {
        if (cancelled) return;
        if (data.status === 'ok' && Array.isArray(data.boxes)) setModelBoxes(data.boxes);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showModelBoxes, chartKey, symbol, timeframe]);

  // ── Draw Box Tool ────────────────────────────────────────────────────
  useEffect(() => {
    const overlay = drawOverlayRef.current;
    if (!overlay) return;

    if (!drawBoxMode) {
      if (drawPreviewRef.current) { drawPreviewRef.current.remove(); drawPreviewRef.current = null; }
      drawStartRef.current = null;
      return;
    }

    const onMouseDown = (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const rect  = overlay.getBoundingClientRect();
      const x     = e.clientX - rect.left;
      const y     = e.clientY - rect.top;
      const series = seriesRef.current;
      const chart  = chartRef.current;
      if (!series || !chart) return;
      const price = series.coordinateToPrice(y);
      drawStartRef.current = { x, y, price };
      if (drawPreviewRef.current) drawPreviewRef.current.remove();
      const preview = document.createElement('div');
      preview.style.cssText = [
        'position:absolute', 'pointer-events:none', 'z-index:5',
        'border:2px dashed rgba(41,98,255,0.9)',
        'background:rgba(41,98,255,0.07)',
        `left:${x}px`, `top:${y}px`, 'width:0', 'height:0',
      ].join(';');
      overlay.appendChild(preview);
      drawPreviewRef.current = preview;
    };

    const onMouseMove = (e) => {
      const start   = drawStartRef.current;
      const preview = drawPreviewRef.current;
      if (!start || !preview) return;
      const rect = overlay.getBoundingClientRect();
      const x    = e.clientX - rect.left;
      const y    = e.clientY - rect.top;
      preview.style.left   = `${Math.min(start.x, x)}px`;
      preview.style.top    = `${Math.min(start.y, y)}px`;
      preview.style.width  = `${Math.abs(x - start.x)}px`;
      preview.style.height = `${Math.abs(y - start.y)}px`;
    };

    const onMouseUp = async (e) => {
      const start = drawStartRef.current;
      if (!start) return;
      drawStartRef.current = null;
      if (drawPreviewRef.current) { drawPreviewRef.current.remove(); drawPreviewRef.current = null; }
      const rect     = overlay.getBoundingClientRect();
      const x        = e.clientX - rect.left;
      const y        = e.clientY - rect.top;
      if (Math.abs(x - start.x) < 10 || Math.abs(y - start.y) < 10) return;
      const series = seriesRef.current;
      const chart  = chartRef.current;
      if (!series || !chart) return;
      const endPrice = series.coordinateToPrice(y);
      if (!endPrice || !start.price) return;
      const priceHigh = Math.max(start.price, endPrice);
      const priceLow  = Math.min(start.price, endPrice);
      const ts = chart.timeScale();
      const t1 = ts.coordinateToTime(start.x);
      const t2 = ts.coordinateToTime(x);
      if (!t1 || !t2) return;
      const timeStart = Math.min(t1, t2) * 1000;
      const timeEnd   = Math.max(t1, t2) * 1000;
      try {
        const res = await fetch('http://localhost:8000/api/detection/manual_box', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol, timeframe, timeStart, timeEnd, priceHigh, priceLow }),
        });
        const d = await res.json();
        if (d.status === 'ok') {
          // Flash green to confirm save
          overlay.style.background = 'rgba(38,166,154,0.06)';
          setTimeout(() => { if (overlay) overlay.style.background = 'transparent'; }, 500);
        }
      } catch (_) {}
    };

    overlay.addEventListener('mousedown', onMouseDown);
    overlay.addEventListener('mousemove', onMouseMove);
    overlay.addEventListener('mouseup',   onMouseUp);
    return () => {
      overlay.removeEventListener('mousedown', onMouseDown);
      overlay.removeEventListener('mousemove', onMouseMove);
      overlay.removeEventListener('mouseup',   onMouseUp);
      if (drawPreviewRef.current) { drawPreviewRef.current.remove(); drawPreviewRef.current = null; }
      drawStartRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawBoxMode, chartKey, symbol, timeframe]);


  // ── Swing Levels Drawing ──────────────────────────────────────────────
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

    // ── Batch same-color swings into ONE LineSeries per color ──────────────────
    // This reduces addSeries() from O(N_swings) → O(N_colors) = ~3-7 series total
    const colorMap = new Map(); // color → [{time, value}]

    dedupedSwings.forEach(sw => {
      if (sw.mitigated && !(settings.showMitigated ?? false)) return;

      const color     = tfSettings[normTf(sw.timeframe)]?.color || TF_COLORS[normTf(sw.timeframe)] || '#888';
      const swUnixSec = Math.floor(sw.time_ms / 1000);

      const startIdx = bisectLeft(unixArr, swUnixSec);
      if (startIdx >= candles.length) return;

      let endIdx;
      if (sw.active) {
        endIdx = candles.length - 1;
      } else if (!sw.mitigated) {
        endIdx = Math.min(startIdx + 5, candles.length - 1);
      } else {
        // mitigated: scan for fill candle (capped at 200 bars for performance)
        endIdx = Math.min(startIdx + 200, candles.length - 1);
        let movedAway = false;
        for (let i = startIdx + 1; i <= endIdx; i++) {
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

      // Just 2 anchor time-points per swing — lightweight-charts will draw straight line
      const tStart = normalizeTimeForChart(unixArr[startIdx], timeframe);
      const tEnd   = normalizeTimeForChart(unixArr[endIdx],   timeframe);
      if (!tStart || !tEnd || tStart === tEnd) return;

      if (!colorMap.has(color)) colorMap.set(color, []);
      const pts = colorMap.get(color);
      // Append segment; use NaN gap to separate from previous segment
      if (pts.length > 0) pts.push({ time: tStart, value: NaN });
      pts.push({ time: tStart, value: sw.price });
      pts.push({ time: tEnd,   value: sw.price });
    });

    // Create one LineSeries per unique color
    colorMap.forEach((pts, color) => {
      if (pts.length < 2) return;

      // Sort by time (lw-charts requires ascending order)
      pts.sort((a, b) => {
        const at = typeof a.time === 'number' ? a.time : new Date(a.time).getTime() / 1000;
        const bt = typeof b.time === 'number' ? b.time : new Date(b.time).getTime() / 1000;
        return at - bt;
      });
      // Drop duplicate time+value pairs
      const deduped = pts.filter((p, i) =>
        i === 0 || !(p.time === pts[i - 1].time && p.value === pts[i - 1].value)
      );

      try {
        const s = chart.addSeries(LineSeries, {
          color, lineWidth: 1, lineStyle: 0,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        s.setData(deduped);
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

    const candleData = sortAndDedupe(chartData.candleData);
    if (chartType === 'line' || chartType === 'area') {
      seriesRef.current.setData(candleData.map(d => ({ time: d.time, value: d.close })));
    } else {
      seriesRef.current.setData(candleData);
    }

    onPriceUpdate?.(candleData[candleData.length - 1]);

    if (isFirstLoad) {
      if (initialBars) {
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
        const initBars = 100;
        if (candleData.length > initBars) {
          chart.timeScale().setVisibleLogicalRange({ from: candleData.length - initBars, to: candleData.length + 3 });
        } else {
          chart.timeScale().fitContent();
        }
      }
    }
  }, [chartData, chartType, timeframe, onPriceUpdate]);

  const handleResetView = useCallback(() => { chartRef.current?.timeScale().scrollToRealTime(); }, []);

  useEffect(() => {
    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth, height: chartContainerRef.current.clientHeight });
      }
    };
    window.addEventListener('resize', handleResize);
    const ro = new ResizeObserver(handleResize);
    if (chartContainerRef.current) ro.observe(chartContainerRef.current);
    return () => { window.removeEventListener('resize', handleResize); ro.disconnect(); if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; } };
  }, []);

  return (
    <div className="w-full h-full relative">
      {loading && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#131722]">
          <div className="w-8 h-8 border-2 border-[#2962FF] border-t-transparent rounded-full animate-spin mb-3" />
          <span className="text-[#787B86] text-[12px]">Loading live data…</span>
        </div>
      )}
      {error && !loading && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#131722]">
          <span className="text-[#EF5350] text-[13px] mb-1">{error}</span>
          <span className="text-[#787B86] text-[11px]">Make sure the backend is running on port 8000</span>
        </div>
      )}
      <div ref={chartContainerRef} className="w-full h-full" />
      {/* Draw tool overlay — sits above LW-charts canvas, captures mouse events */}
      <div
        ref={drawOverlayRef}
        style={{
          position: 'absolute',
          inset: 0,
          zIndex: 25,
          cursor:        drawBoxMode ? 'crosshair' : 'default',
          pointerEvents: drawBoxMode ? 'all' : 'none',
          background:    'transparent',
        }}
      />
      {/* ML Score label chips — positioned in chart pixel space */}
      <div ref={mlOverlayRef} style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 20 }} />
      {/* ML Hover Tooltip */}
      <div
        ref={mlTooltipRef}
        style={{
          display: 'none',
          position: 'absolute',
          background: '#1A1D2E',
          border: '1px solid #2A2E39',
          borderRadius: '6px',
          padding: '8px 10px',
          fontSize: '10px',
          color: '#D1D4DC',
          fontFamily: 'Inter, sans-serif',
          pointerEvents: 'none',
          zIndex: 50,
          minWidth: '140px',
          maxWidth: '220px',
          boxShadow: '0 4px 20px rgba(0,0,0,0.6)',
          lineHeight: '1.5',
        }}
      />
      {/* User Rating Popup — shown on box click */}
      {ratingPopup && (() => {
        // If already labeled → show permanent badge, not a dismissable popup
        const existingLabel = userFeedback[ratingPopup.box_id] || ratingPopup.zone?.user_label;
        const existingPattern = patternFeedback[ratingPopup.box_id] || ratingPopup.zone?.pattern_type;
        return (
        <div style={{
          position:   'absolute',
          left:       `${ratingPopup.x}px`,
          top:        `${ratingPopup.y}px`,
          zIndex:     60,
          display:    'flex',
          flexDirection: 'column',
          gap:        '4px',
          background: 'rgba(20,24,36,0.97)',
          border:     existingLabel ? '1px solid #26A69A55' : '1px solid #363A45',
          borderRadius: '12px',
          padding:    '5px 8px',
          backdropFilter: 'blur(8px)',
          boxShadow:  existingLabel ? '0 4px 16px rgba(38,166,154,0.2)' : '0 4px 16px rgba(0,0,0,0.6)',
          fontFamily: 'Inter, sans-serif',
          fontSize:   '13px',
          userSelect: 'none',
        }}>
          {/* ── Existing label banner (permanent after first rating) ── */}
          {existingLabel && (() => {
            const labelColor = { GOOD: '#26A69A', BAD: '#EF5350', NEUTRAL: '#90CAF9' }[existingLabel] || '#90CAF9';
            return (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '5px',
                fontSize: '9px', color: labelColor, fontWeight: 700,
                background: `${labelColor}15`, border: `1px solid ${labelColor}40`,
                borderRadius: '6px', padding: '2px 7px',
              }}>
                <span>✓ Labeled:</span>
                <span>{existingLabel}</span>
                {existingPattern && <span style={{ opacity: 0.7, fontSize: '8px', color: '#FFB86C' }}>· {existingPattern.replace('_', ' ')}</span>}
              </div>
            );
          })()}

          {/* ── Rating row: GOOD / BAD / NEUTRAL + close ── */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            {[
              { label: 'GOOD',    emoji: '✓', color: '#26A69A' },
              { label: 'BAD',     emoji: '✗', color: '#EF5350' },
              { label: 'NEUTRAL', emoji: '–', color: '#90CAF9' },
            ].map(({ label, emoji, color }) => {
              const active = (userFeedback[ratingPopup.box_id] || ratingPopup.zone?.user_label) === label;
              return (
                <button
                  key={label}
                  onClick={() => handleUserRating(ratingPopup.box_id, label)}
                  title={`${label} (${label[0].toLowerCase()})`}
                  style={{
                    background: active ? `${color}22` : 'transparent',
                    border:     active ? `1px solid ${color}70` : '1px solid transparent',
                    borderRadius: '10px', padding: '2px 8px', height: '24px',
                    cursor: 'pointer', fontSize: '11px', color: active ? color : '#D1D4DC',
                    display: 'flex', alignItems: 'center', gap: '3px',
                    transition: 'all 0.12s', outline: 'none',
                  }}
                >
                  <span>{emoji}</span><span>{label}</span>
                </button>
              );
            })}

            {/* Pattern toggle pill */}
            <button
              onClick={() => {
                const next = !JSON.parse(localStorage.getItem('ml_show_pattern_ui') || 'false');
                localStorage.setItem('ml_show_pattern_ui', JSON.stringify(next));
                setRatingPopup(p => p ? { ...p } : p);
              }}
              title="Toggle pattern-type training (Continuation / Liquidity Grab)"
              style={{
                background: JSON.parse(localStorage.getItem('ml_show_pattern_ui') || 'false')
                  ? 'rgba(144,202,249,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${JSON.parse(localStorage.getItem('ml_show_pattern_ui') || 'false') ? '#90CAF960' : '#363A45'}`,
                borderRadius: '10px', padding: '2px 7px', height: '22px',
                cursor: 'pointer', fontSize: '9px',
                color: JSON.parse(localStorage.getItem('ml_show_pattern_ui') || 'false') ? '#90CAF9' : '#555A68',
                display: 'flex', alignItems: 'center', gap: '3px',
                transition: 'all 0.12s', outline: 'none', marginLeft: '2px',
              }}
            >
              Pattern {JSON.parse(localStorage.getItem('ml_show_pattern_ui') || 'false') ? '▾' : '▸'}
            </button>

            <button
              onClick={() => setRatingPopup(null)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: '#787B86', fontSize: '9px', marginLeft: '2px',
                padding: '0 2px', lineHeight: 1,
              }}
            >✕</button>
          </div>


          {/* ── Pattern row — hidden unless toggled ── */}
          {JSON.parse(localStorage.getItem('ml_show_pattern_ui') || 'false') && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '4px',
              borderTop: '1px solid #252836', paddingTop: '4px',
            }}>
              <span style={{ fontSize: '8px', color: '#555A68', marginRight: '2px' }}>Pattern:</span>
              {[
                { label: 'CONTINUATION',   emoji: '➡️', color: '#90CAF9' },
                { label: 'LIQUIDITY_GRAB', emoji: '🎯', color: '#FFB86C' },
              ].map(({ label, emoji, color }) => {
                const current = patternFeedback[ratingPopup.box_id] || ratingPopup.zone?.pattern_type;
                const active  = current === label;
                return (
                  <button
                    key={label}
                    onClick={() => handlePatternRating(ratingPopup.box_id, label)}
                    title={label}
                    style={{
                      background: active ? `${color}25` : 'transparent',
                      border:     active ? `1px solid ${color}60` : '1px solid transparent',
                      borderRadius: '10px', padding: '0 7px', height: '22px',
                      cursor: 'pointer', fontSize: '10px',
                      display: 'flex', alignItems: 'center', gap: '3px',
                      transition: 'all 0.12s', outline: 'none',
                      color: active ? '#fff' : '#A0A4B0',
                    }}
                  >
                    {emoji} <span style={{ fontSize: '9px' }}>{label.replace('_', ' ')}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        );
      })()}

      {!loading && !error && (
        <button
          onClick={handleResetView}
          className={`absolute ${isSubchart ? 'bottom-2 right-2' : 'bottom-6 left-1/2 -translate-x-1/2'} z-20 flex items-center gap-1.5 ${isSubchart ? 'px-2 py-1' : 'px-3 py-1.5'} bg-[#1E222D] hover:bg-[#2A2E39] text-[#D1D4DC] hover:text-white border border-[#363A45] rounded-full shadow-lg transition-all active:scale-95 group`}
          title="Back to Latest"
        >
          <span className={`${isSubchart ? 'text-[9px]' : 'text-[11px]'} font-medium`}>Latest</span>
          <ChevronsRight size={isSubchart ? 10 : 14} className="group-hover:translate-x-0.5 transition-transform" />
        </button>
      )}

      {/* ── Detection Feedback Popup ────────────────────────────────────── */}
      {detectionPopup && (
        <div style={{
          position: 'absolute',
          left: `${Math.min(detectionPopup.x, 300)}px`,
          top:  `${Math.max(detectionPopup.y - 10, 4)}px`,
          zIndex: 70,
          display: 'flex', flexDirection: 'column', gap: '6px',
          background: 'rgba(17,20,31,0.97)',
          border: '1px solid #363A45',
          borderRadius: '10px',
          padding: '8px 10px',
          backdropFilter: 'blur(10px)',
          boxShadow: '0 6px 24px rgba(0,0,0,0.7)',
          fontFamily: 'Inter, sans-serif',
          userSelect: 'none',
          minWidth: '180px',
        }}>
          {/* Score badge */}
          {detectionPopup.zone && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
              <span style={{ fontSize: '10px', color: '#787B86' }}>Model score</span>
              <span style={{
                fontSize: '11px', fontWeight: 700, fontFamily: 'monospace',
                color: (detectionPopup.zone.detection_score || 0) >= 0.55 ? '#26A69A' :
                       (detectionPopup.zone.detection_score || 0) >= 0.45 ? '#FFB86C' : '#EF5350',
              }}>
                {((detectionPopup.zone.detection_score || 0) * 100).toFixed(1)}%
              </span>
              {detectionPopup.zone.is_uncertain && (
                <span style={{
                  fontSize: '8px', background: 'rgba(255,184,0,0.18)', color: '#FFB86C',
                  border: '1px dashed #FFB86C60', borderRadius: '4px', padding: '1px 4px',
                }}>uncertain</span>
              )}
            </div>
          )}
          {/* Action buttons */}
          <div style={{ display: 'flex', gap: '4px' }}>
            {[
              { label: 'RIGHT',  key: 'R', bg: '#26A69A', emoji: '✓' },
              { label: 'WRONG',  key: 'W', bg: '#EF5350', emoji: '✗' },
              { label: 'IGNORE', key: 'I', bg: '#787B86', emoji: '–' },
            ].map(({ label, key, bg, emoji }) => {
              const current = detectionFeedback[detectionPopup.box_id];
              const active  = current === label;
              return (
                <button
                  key={label}
                  onClick={() => handleDetectionFeedback(detectionPopup.box_id, label)}
                  title={`${label} (key: ${key})`}
                  style={{
                    flex: 1,
                    background: active ? `${bg}30` : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${active ? bg : '#363A45'}`,
                    borderRadius: '6px', padding: '3px 0',
                    cursor: 'pointer', fontSize: '11px', color: active ? '#fff' : '#A0A4B0',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '3px',
                    transition: 'all 0.15s',
                  }}
                >
                  <span>{emoji}</span>
                  <span style={{ fontSize: '9px', opacity: 0.7 }}>{key}</span>
                </button>
              );
            })}
            <button
              onClick={() => { setDetectionPopup(null); clearTimeout(detectionPopupTimerRef.current); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#787B86', fontSize: '9px', padding: '0 2px' }}
            >✕</button>
          </div>
        </div>
      )}

      {/* ── Draw mode cursor indicator ────────────────────────────────── */}
      {drawBoxMode && (
        <div style={{
          position: 'absolute', top: 4, left: '50%', transform: 'translateX(-50%)',
          zIndex: 50, background: 'rgba(41,98,255,0.15)', border: '1px dashed rgba(41,98,255,0.6)',
          borderRadius: '6px', padding: '2px 8px', fontSize: '9px', color: '#2962FF',
          pointerEvents: 'none', userSelect: 'none',
        }}>
          ✏ Click-drag to draw consolidation box
        </div>
      )}
    </div>
  );

});

ChartWidget.displayName = 'ChartWidget';
export default ChartWidget;
