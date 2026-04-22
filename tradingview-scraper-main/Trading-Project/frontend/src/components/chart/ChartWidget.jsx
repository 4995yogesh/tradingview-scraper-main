import React, { useEffect, useRef, useCallback, useState, forwardRef, useImperativeHandle } from 'react';
import { createChart, CandlestickSeries, LineSeries, AreaSeries, BarSeries, BaselineSeries } from 'lightweight-charts';
import { fetchLiveCandles } from '../../data/chartData';
import { ChevronsRight } from 'lucide-react';
import {
  aggregateCandles, detectSwings, getHigherTfs, ALL_TFS,
  normalizeTimeForChart, TF_COLORS, FILLED_COLOR,
} from '../../lib/swingLevels';
import LabelDialog from './LabelDialog';


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
    .filter(c => Number.isFinite(c.time));

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




const ChartWidget = forwardRef(({ symbol, timeframe, chartType, onPriceUpdate, logScale, chartSettings, refreshKey, symbolPrecision = 4, swingSettings, consolidationSettings, liveTickKey, isSubchart, initialBars }, ref) => {
  const chartContainerRef      = useRef(null);
  const chartRef               = useRef(null);
  const seriesRef              = useRef(null);
  const isLoadingMoreRef       = useRef(false);
  const swingSeriesRef         = useRef([]); // swing level LineSeries
  const consolidationSeriesRef = useRef([]); // consolidation box series
  const [chartKey, setChartKey] = useState(0); // increments when chart is re-initialised

  const [chartData, setChartData] = useState(null);
  const chartDataRef = useRef(null);
  chartDataRef.current = chartData;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  // ML label dialog state
  const [activeLabelZone, setActiveLabelZone] = useState(null);
  const [hoveredBoxId, setHoveredBoxId] = useState(null);
  // Store zone data keyed by box_id for overlay rendering
  const zoneMapRef = useRef({});
  const activeBoxesRef = useRef([]);


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
    if (loading || error || !chartData || typeof liveTickKey === 'undefined' || liveTickKey === 0) return;

    (async () => {
      try {
        const latest = await fetchLiveCandles(symbol, timeframe, 50);
        if (latest && latest.candleData.length > 0) {
          setChartData(prev => {
            if (!prev) return latest;
            
            const combinedCandles = prev.candleData.concat(latest.candleData);
            const combinedVolume  = prev.volumeData.concat(latest.volumeData);

            return {
              candleData: prepareChartData(combinedCandles, timeframe),
              volumeData: prepareChartData(combinedVolume, timeframe)
            };
          });
        }
      } catch (err) {
        console.warn('Live fetch failed:', err?.message);
      }
    })();
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
            setChartData(prev => {
              const combinedCandles = prev.candleData.concat(newData.candleData);
              const combinedVolume  = prev.volumeData.concat(newData.volumeData);

              return {
                candleData: prepareChartData(combinedCandles, timeframe),
                volumeData: prepareChartData(combinedVolume, timeframe)
              };
            });
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
            setConsolidations(prev => JSON.stringify(prev) === JSON.stringify(d.zones) ? prev : (d.zones || []));
          }
        }
        if (sRes.ok) {
          const d = await sRes.json();
          if (d.status === 'ok') {
            setSwingLevels(prev => JSON.stringify(prev) === JSON.stringify(d.swings) ? prev : (d.swings || []));
          }
        }
      } catch (_) {}
    };
    poll();
    iv = setInterval(poll, 10000);
    return () => clearInterval(iv);
  }, []);

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

      return true;
    });
  }, [consolidations, timeframe, consolidationSettings?.enabled, consolidationSettings?.settings?.showHTF]);


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

    // Same TF filter logic as swing indicator:
    // Show consolidation zones from same TF or any higher TF, except:
    //   - Skip 15m zones on 5m chart
    //   - Skip 5m zones on 1m chart
    const chartTfIdx = ALL_TFS.indexOf(chartTf);
    const zones = visibleZones;
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

    zones.forEach(zone => {
      const startUnix = Math.floor(zone.timeStart / 1000);
      const endUnix   = Math.floor(zone.timeEnd   / 1000);


      const t1 = snapToChart(startUnix);
      // Extend to current bar if zone is still active
      const t2 = endUnix >= lastUnix ? candles[candles.length - 1].time : snapToChart(endUnix);
      if (!t1 || !t2 || t1 === t2) return;

      const s1 = Math.min(getUnix(t1), getUnix(t2));
      const s2 = Math.max(getUnix(t1), getUnix(t2));

      const lo     = bisectLeft(unixArr, s1);
      const hi     = bisectLeft(unixArr, s2 + 1);
      const points = candles.slice(lo, hi).map(c => c.time);
      if (points.length < 2) return;

      // Store zone for overlay rendering
      if (zone.box_id) zoneMapRef.current[zone.box_id] = zone;

      try {
        // Determine color based on label / score
        const hasLabel  = zone.label != null;
        const score     = zone.score || {};
        const isFb      = score.is_fallback !== false;
        const pGood     = !isFb ? (score.probabilities?.good || 0) : null;

        let borderColor, fillColor;
        if (hasLabel) {
          if (zone.label === 'good')    { borderColor = 'rgba(38,166,154,0.85)'; fillColor = 'rgba(38,166,154,0.12)'; }
          else if (zone.label === 'bad') { borderColor = 'rgba(239,83,80,0.85)';  fillColor = 'rgba(239,83,80,0.12)'; }
          else                           { borderColor = 'rgba(255,167,38,0.85)'; fillColor = 'rgba(255,167,38,0.12)'; }
        } else if (!isFb && pGood != null) {
          // Color-code by P(good): green if high, red if low
          const r = Math.round(239 - pGood * (239 - 38));
          const g = Math.round(83  + pGood * (166 - 83));
          const b = Math.round(80  + pGood * (154 - 80));
          borderColor = `rgba(${r},${g},${b},0.85)`;
          fillColor   = `rgba(${r},${g},${b},0.10)`;
        } else {
          borderColor = 'rgba(144, 202, 249, 0.85)';
          fillColor   = 'rgba(144, 202, 249, 0.15)';
        }

        const topLine = chart.addSeries(LineSeries, {
          color: borderColor, lineWidth: 1, lineStyle: 0,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        const botLine = chart.addSeries(LineSeries, {
          color: borderColor, lineWidth: 1, lineStyle: 0,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });

        topLine.setData(points.map(t => ({ time: t, value: zone.priceHigh })));
        botLine.setData(points.map(t => ({ time: t, value: zone.priceLow  })));

        const fillArea = chart.addSeries(BaselineSeries, {
          baseValue:        { type: 'price', price: zone.priceLow },
          topLineColor:     'transparent',
          topFillColor1:    fillColor,
          topFillColor2:    fillColor,
          bottomLineColor:  'transparent',
          bottomFillColor1: 'transparent',
          bottomFillColor2: 'transparent',
          lineWidth: 0,
          priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        fillArea.setData(points.map(t => ({ time: t, value: zone.priceHigh })));

        consolidationSeriesRef.current.push(topLine, botLine, fillArea);
        
        if (zone.box_id) {
          activeBoxesRef.current.push({
            box_id: zone.box_id,
            drawT1: points[0],
            drawT2: points[points.length - 1],
            priceHigh: zone.priceHigh
          });
        }
      } catch (e) {
        console.warn('Consolidation box draw error:', e);
      }
    });

    return () => {
      consolidationSeriesRef.current.forEach(s => { try { chartRef.current?.removeSeries(s); } catch {} });
      consolidationSeriesRef.current = [];
      activeBoxesRef.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consolidations, timeframe, chartKey, consolidationSettings?.enabled, consolidationSettings?.settings?.showHTF]);

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
      
      const timeScale = chart.timeScale();
      
      activeBoxesRef.current.forEach(box => {
        const el = document.getElementById(`mlbox-${box.box_id}`);
        if (!el) return;
        
        try {
          const mappedT1 = mapOverlayTime(box.drawT1, timeframe);
          const mappedT2 = mapOverlayTime(box.drawT2, timeframe);
          const x1 = timeScale.timeToCoordinate(mappedT1);
          const x2 = timeScale.timeToCoordinate(mappedT2);
          if (x1 === null || x2 === null) {
            el.style.display = 'none';
            return;
          }
          
          const midX = (x1 + x2) / 2;
          const topY = series.priceToCoordinate(box.priceHigh);
          
          if (topY !== null) {
            el.style.display = 'block';
            // Anchor neatly above the box center
            el.style.transform = `translate(calc(${midX}px - 50%), calc(${topY}px - 100% - 6px))`;
          } else {
            el.style.display = 'none';
          }
        } catch (_) {
          el.style.display = 'none';
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

    if (!Array.isArray(candleData) || candleData.length < 2) return;

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
      
      {/* Absolute Box Label Overlays */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden z-30">
        {visibleZones.map(zone => {
          if (!zone.box_id) return null;
          return (
            <div 
              key={zone.box_id} 
              id={`mlbox-${zone.box_id}`}
              className="absolute top-0 left-0"
              style={{ display: 'none', pointerEvents: 'auto', transformOrigin: 'bottom center' }}
            >
              <LabelDialog zone={zone} />
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
          <span className={`${isSubchart ? 'text-[9px]' : 'text-[11px]'} font-medium`}>Latest</span>
          <ChevronsRight size={isSubchart ? 10 : 14} className="group-hover:translate-x-0.5 transition-transform" />
        </button>
      )}
    </div>
  );
});

ChartWidget.displayName = 'ChartWidget';
export default ChartWidget;
