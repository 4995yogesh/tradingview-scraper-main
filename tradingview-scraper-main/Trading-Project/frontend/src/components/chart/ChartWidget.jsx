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

const ChartWidget = forwardRef(({ symbol, timeframe, chartType, onPriceUpdate, logScale, chartSettings, refreshKey, symbolPrecision = 5, swingSettings }, ref) => {
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

  // ── Live Polling: Fetch latest candles every 60 seconds ──
  useEffect(() => {
    if (loading || error || !chartData) return;

    const pollInterval = setInterval(async () => {
      try {
        const latest = await fetchLiveCandles(symbol, timeframe, 5);
        if (latest && latest.candleData.length > 0 && seriesRef.current) {
          latest.candleData.forEach(candle => {
            if (chartType === 'line' || chartType === 'area') {
              seriesRef.current.update({ time: candle.time, value: candle.close });
            } else {
              seriesRef.current.update(candle);
            }
          });
          const lastCandle = latest.candleData[latest.candleData.length - 1];
          onPriceUpdate?.(lastCandle);
        }
      } catch (err) {
        console.warn('Scroll-back fetch failed:', err?.message);
      }
    }, 60000);

    return () => clearInterval(pollInterval);
  }, [symbol, timeframe, loading, error, chartData, chartType, onPriceUpdate]);

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
      localization: { locale: 'en-US' },
      layout: { background: { type: 'solid', color: bg }, textColor: chartSettings?.priceScaleColor || '#787B86', fontSize: 11, fontFamily: 'Inter, -apple-system, sans-serif' },
      grid: { vertLines: { color: gridColor, style: 1 }, horzLines: { color: gridColor, style: 1 } },
      crosshair: { mode: crosshairMode, vertLine: { width: 1, color: '#787B8650', style: 2, labelBackgroundColor: '#2962FF' }, horzLine: { width: 1, color: '#787B8650', style: 2, labelBackgroundColor: '#2962FF' } },
      timeScale: {
        borderColor: chartSettings?.priceScaleColor || '#2A2E39', timeVisible: ['1m', '5m', '15m', '30m', '1h', '4h'].includes(timeframe),
        secondsVisible: false, rightOffset: 10, barSpacing: TF_BAR_SPACING[timeframe] || 8, minBarSpacing: 1,
      },
      rightPriceScale: { borderColor: chartSettings?.priceScaleColor || '#2A2E39', scaleMargins: { top: 0.05, bottom: 0.05 }, mode: logScale ? 1 : 0, visible: true, borderVisible: true, autoScale: true, entireTextOnly: false },
      handleScroll: { vertTouchDrag: false },
    });

    chartRef.current = chart;

    const upColor = chartSettings?.upColor || '#26A69A';
    const downColor = chartSettings?.downColor || '#EF5350';
    const borderUp = chartSettings?.borderUpColor || upColor;
    const borderDown = chartSettings?.borderDownColor || downColor;
    const wickUp = chartSettings?.wickUpColor || upColor;
    const wickDown = chartSettings?.wickDownColor || downColor;

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
      mainSeries = chart.addSeries(CandlestickSeries, { upColor: 'transparent', downColor, borderUpColor: borderUp, borderDownColor: borderDown, wickUpColor: wickUp, wickDownColor: wickDown, priceFormat });
    } else {
      mainSeries = chart.addSeries(CandlestickSeries, { upColor, downColor, borderUpColor: borderUp, borderDownColor: borderDown, wickUpColor: wickUp, wickDownColor: wickDown, priceFormat });
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

  // ── Swing Levels drawing (finite segments, stop at mitigation time) ─────────────
  useEffect(() => {
    const chart = chartRef.current;

    // Guard: need chart, candles, and swing indicator enabled
    if (!swingSettings?.enabled || !chart || !chartData?.candleData?.length) {
      // Cleanup on disable
      if (swingSeriesRef.current.length > 0 && chartRef.current) {
        swingSeriesRef.current.forEach(s => {
          try { chartRef.current.removeSeries(s); } catch { /* already removed */ }
        });
        swingSeriesRef.current = [];
      }
      return;
    }

    const candles  = chartData.candleData;
    const settings = swingSettings.settings || {};

    // Remove previous swing segments before redrawing
    swingSeriesRef.current.forEach(s => {
      try { chart.removeSeries(s); } catch { /* stale */ }
    });
    swingSeriesRef.current = [];

    const hideFilled     = settings.hideFilled ?? true;
    const showHighs      = settings.showHighs  !== false;
    const showLows       = settings.showLows   !== false;
    const lastCandleTime = candles[candles.length - 1].time;

    // ── Snap a unix-second HTF time to the nearest real LTF candle ─────────────
    const snapToLtf = (unixSec) => {
      const norm = normalizeTimeForChart(unixSec, timeframe);
      for (const c of candles) {
        if (c.time >= norm) return c.time;
      }
      return norm;
    };

    /**
     * processTf — detect swings for one TF and draw finite segments.
     *
     * isCurrentTf = true  → htfCandles IS the chart candles; times already in
     *                        chart-native format, so no snapToLtf needed.
     * isCurrentTf = false → htfCandles is aggregated; need snapToLtf for start
     *                        and scan LTF candles for exact mitigation end.
     */
    const processTf = (tf, htfCandles, isCurrentTf) => {
      const tfCfg  = settings.tfs?.[tf];
      if (tfCfg?.enabled === false) return;

      const color    = tfCfg?.color    ?? '#ffffff';
      const lookback = tfCfg?.lookback ?? 50;

      const { highs, lows } = detectSwings(htfCandles, lookback);
      saveSwingsToMemory(symbol, tf, highs, lows);

      const drawSegment = (swingTime, price, isHigh) => {
        let startTs, endTs, isMitigated = false;

        if (isCurrentTf) {
          // Current TF: times already in chart format — scan directly from pivot
          const swingIdx = candles.findIndex(c => c.time === swingTime);
          startTs = swingTime;
          endTs   = lastCandleTime;
          for (let i = (swingIdx >= 0 ? swingIdx + 1 : 0); i < candles.length; i++) {
            const c = candles[i];
            if (isHigh ? c.high >= price : c.low <= price) {
              endTs = c.time; isMitigated = true; break;
            }
          }
        } else {
          // HTF: snap start to nearest LTF candle; scan LTF from next HTF boundary
          const swingIdx    = htfCandles.findIndex(c => c.time === swingTime);
          const nextHtfStart = (swingIdx >= 0 && swingIdx < htfCandles.length - 1)
            ? htfCandles[swingIdx + 1].time : null;
          startTs = snapToLtf(swingTime);
          endTs   = lastCandleTime;
          if (nextHtfStart !== null) {
            const boundary = snapToLtf(nextHtfStart);
            const ltfIdx   = candles.findIndex(c => c.time === boundary);
            if (ltfIdx >= 0) {
              for (let i = ltfIdx; i < candles.length; i++) {
                const c = candles[i];
                if (isHigh ? c.high >= price : c.low <= price) {
                  endTs = c.time; isMitigated = true; break;
                }
              }
            }
          }
        }

        if (isMitigated && hideFilled) return;
        if (startTs === endTs) return;

        const [t1, t2] = startTs <= endTs ? [startTs, endTs] : [endTs, startTs];

        try {
          const seg = chart.addSeries(LineSeries, {
            color,
            lineWidth:              1,
            lineStyle:              0, // Solid for all
            priceLineVisible:       false,
            lastValueVisible:       false,
            crosshairMarkerVisible: false,
          });
          seg.setData([
            { time: t1, value: price },
            { time: t2, value: price },
          ]);
          swingSeriesRef.current.push(seg);
        } catch { /* chart torn down */ }
      };

      if (showHighs) highs.forEach(s => drawSegment(s.time, s.price, true));
      if (showLows)  lows.forEach(s  => drawSegment(s.time, s.price, false));
    };

    // Draw current TF first (bottom z-layer), then higher TFs in ascending order
    // so the highest TF lines render last and appear visually on top.
    processTf(timeframe, candles, true);

    const higherTfs = [...getHigherTfs(timeframe)].reverse(); // LTF→HTF order
    for (const tf of higherTfs) {
      const htfCandles = aggregateCandles(candles, tf);
      if (htfCandles.length >= 3) processTf(tf, htfCandles, false);
    }

    return () => {
      swingSeriesRef.current.forEach(s => {
        try { chartRef.current?.removeSeries(s); } catch { /* ignore */ }
      });
      swingSeriesRef.current = [];
    };
  }, [chartData, swingSettings, timeframe, symbol, chartKey]);

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
