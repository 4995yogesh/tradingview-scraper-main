import React, { useEffect, useRef, useCallback, useState, forwardRef, useImperativeHandle } from 'react';
import { createChart, CandlestickSeries, LineSeries, AreaSeries, BarSeries } from 'lightweight-charts';
import { fetchLiveCandles } from '../../data/chartData';
import { ChevronsRight } from 'lucide-react';
import {
  aggregateCandles, detectSwings, getHigherTfs, saveSwingsToMemory,
  normalizeTimeForChart,
} from '../../lib/swingLevels';

// Sensible number of bars to fetch per timeframe so candles are visible at the initial zoom
const TF_CANDLE_COUNT = {
  '1m':  200,
  '5m':  300,
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

// Sort ascending by time, then remove duplicates
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

const ChartWidget = forwardRef(({ symbol, timeframe, chartType, onPriceUpdate, logScale, chartSettings, refreshKey, symbolPrecision = 4, swingSettings, liveTickKey }, ref) => {
  const chartContainerRef = useRef(null);
  const chartRef          = useRef(null);
  const seriesRef         = useRef(null);
  const isLoadingMoreRef  = useRef(false);
  const swingSeriesRef    = useRef([]); // tracks active LineSeries swing segments for cleanup
  const [chartKey, setChartKey] = useState(0); // increments when chart is re-initialised

  const [chartData, setChartData] = useState(null);
  const chartDataRef = useRef(null);
  chartDataRef.current = chartData;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

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
            const mergeSort = (older, newer) => {
              const olderMap = new Map(older.map(c => [c.time, c]));
              newer.forEach(c => olderMap.set(c.time, c)); // overwrite or append
              const merged = Array.from(olderMap.values());
              merged.sort((a, b) => {
                const ta = typeof a.time === 'string' ? a.time : Number(a.time);
                const tb = typeof b.time === 'string' ? b.time : Number(b.time);
                return ta < tb ? -1 : ta > tb ? 1 : 0;
              });
              return merged;
            };
            return {
              candleData: mergeSort(prev.candleData, latest.candleData),
              volumeData: mergeSort(prev.volumeData, latest.volumeData)
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

    // Clear swing series reference since the chart (and all its series) is destroyed
    swingSeriesRef.current = [];

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
      rightPriceScale: { borderColor: chartSettings?.priceScaleColor || '#2A2E39', scaleMargins: { top: 0.05, bottom: 0.05 }, mode: logScale ? 1 : 0, visible: true, borderVisible: true, autoScale: true, entireTextOnly: false, minimumWidth: 25 },
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
            const mergeSort = (older, newer) => {
              const merged = [...older, ...newer];
              merged.sort((a, b) => {
                const ta = typeof a.time === 'string' ? a.time : Number(a.time);
                const tb = typeof b.time === 'string' ? b.time : Number(b.time);
                return ta < tb ? -1 : ta > tb ? 1 : 0;
              });
              return merged.filter((c, i, arr) => i === 0 || c.time !== arr[i - 1].time);
            };
            setChartData(prev => ({ candleData: mergeSort(newData.candleData, prev.candleData), volumeData: mergeSort(newData.volumeData, prev.volumeData) }));
          }
        } finally {
          setTimeout(() => { isLoadingMoreRef.current = false; }, 500);
        }
      }
    });
  }, [chartType, logScale, chartSettings, timeframe, symbol, symbolPrecision, onPriceUpdate]);

  useEffect(() => { initChart(); }, [initChart]);

  // ── Consolidation Boxes Drawing ─────────────
  const [consolidations, setConsolidations] = useState([]);

  useEffect(() => {
    let interval;
    const fetchConsolidations = async () => {
      try {
        const res = await fetch('http://localhost:8001/consolidations');
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === 'ok') {
          // Deep compare to prevent infinite re-renders or state churn if needed,
          // but React will handle new state identities correctly with useEffect dependencies.
          setConsolidations(data.zones || []);
        }
      } catch (err) {}
    };

    fetchConsolidations();
    interval = setInterval(fetchConsolidations, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !chartData?.candleData?.length) return;

    // Remove previous boxes before redrawing
    swingSeriesRef.current.forEach(s => {
      try { chart.removeSeries(s); } catch { /* stale */ }
    });
    swingSeriesRef.current = [];

    const candles = chartData.candleData;
    const timeMap = new Set(candles.map(c => c.time));

    // Snap target ms to the nearest real chart Unix time
    const snapToLtf = (unixSec) => {
      let nearest = null;
      let minDiff = Infinity;
      for (const c of candles) {
        const diff = Math.abs(c.time - unixSec);
        if (diff < minDiff) { minDiff = diff; nearest = c.time; }
      }
      return nearest || unixSec;
    };

    // Normalize: backend uses "1H"/"4H", frontend uses "1h"/"4h"
    const normTf = (tf) => tf.toLowerCase();
    const zones = consolidations.filter(z => normTf(z.timeframe) === normTf(timeframe));

    zones.forEach(zone => {
      const startSec = Math.floor(zone.timeStart / 1000);
      const endSec = Math.floor(zone.timeEnd / 1000);

      const t1 = snapToLtf(startSec);
      const t2 = snapToLtf(endSec);
      if (t1 === t2) return;

      const s1 = Math.min(t1, t2);
      const s2 = Math.max(t1, t2);

      const validPoints = candles.filter(c => c.time >= s1 && c.time <= s2).map(c => c.time);
      if (validPoints.length < 2) return;

      try {
        // Top border line
        const topLine = chart.addSeries(LineSeries, {
          color: 'rgba(41, 98, 255, 0.9)',
          lineWidth: 2,
          lineStyle: 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        // Bottom border line
        const botLine = chart.addSeries(LineSeries, {
          color: 'rgba(41, 98, 255, 0.9)',
          lineWidth: 2,
          lineStyle: 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        // Fill line — horizontal line at mid, used with area fill trick
        // Draw mid-price flat line spanning zone width as shaded band
        const midFill = chart.addSeries(AreaSeries, {
          topColor: 'rgba(41, 98, 255, 0.12)',
          bottomColor: 'rgba(41, 98, 255, 0.03)',
          lineColor: 'transparent',
          lineWidth: 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        const topData = validPoints.map(t => ({ time: t, value: zone.priceHigh }));
        const botData = validPoints.map(t => ({ time: t, value: zone.priceLow }));

        topLine.setData(topData);
        botLine.setData(botData);
        midFill.setData(topData); // AreaSeries fills DOWN from priceHigh; gives a subtle shade

        swingSeriesRef.current.push(topLine, botLine, midFill);
      } catch (e) {
        console.warn('Failed drawing consolidation box:', e);
      }
    });

    return () => {
      swingSeriesRef.current.forEach(s => {
        try { chartRef.current?.removeSeries(s); } catch {}
      });
      swingSeriesRef.current = [];
    };
  }, [chartData, consolidations, timeframe, chartKey]);

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
      const INITIAL_BARS = { '1m': 100, '5m': 150, '15m': 200, '30m': 250 };
      const initBars = INITIAL_BARS[timeframe];
      if (initBars && candleData.length > initBars) {
        chart.timeScale().setVisibleLogicalRange({ from: candleData.length - initBars, to: candleData.length + 3 });
      } else {
        chart.timeScale().fitContent();
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
      {!loading && !error && (
        <button
          onClick={handleResetView}
          className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5 px-3 py-1.5 bg-[#1E222D] hover:bg-[#2A2E39] text-[#D1D4DC] hover:text-white border border-[#363A45] rounded-full shadow-lg transition-all active:scale-95 group"
          title="Back to Latest"
        >
          <span className="text-[11px] font-medium">Latest</span>
          <ChevronsRight size={14} className="group-hover:translate-x-0.5 transition-transform" />
        </button>
      )}
    </div>
  );
});

ChartWidget.displayName = 'ChartWidget';
export default ChartWidget;
