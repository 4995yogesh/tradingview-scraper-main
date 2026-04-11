import React, { useEffect, useRef, useState } from 'react';
import { renderCandleChart } from '../rendering/CandleRenderer';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'];
const API = 'http://localhost:8000';

// ── Per-timeframe chart cell ─────────────────────────────────────────────────
const ChartCell = ({ timeframe }) => {
  const canvasRef = useRef(null);
  const [chartData, setChartData] = useState(null);
  const camera = useRef({ x: 0, zoom: 1 });
  const drag = useRef({ active: false, lastX: 0 });
  const animRef = useRef(null);

  // Fetch OHLC data for this timeframe
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(
          `${API}/api/chart-data?exchange=OANDA&symbol=EURUSD&timeframe=${timeframe}&candles=500`
        );
        if (!res.ok) return;
        const json = await res.json();
        if (!cancelled) setChartData(json);
      } catch (e) {
        console.warn(`[${timeframe}] fetch error`, e);
      }
    };
    load();
    const iv = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [timeframe]);

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const loop = () => {
      const ctx = canvas.getContext('2d');
      renderCandleChart(canvas, ctx, chartData, timeframe, camera.current);
      animRef.current = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      cancelAnimationFrame(animRef.current);
      ro.disconnect();
    };
  }, [chartData, timeframe]);

  // Drag / pan
  const onPointerDown = (e) => {
    drag.current = { active: true, lastX: e.clientX };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!drag.current.active) return;
    camera.current.x += e.clientX - drag.current.lastX;
    drag.current.lastX = e.clientX;
  };
  const onPointerUp = () => { drag.current.active = false; };

  // Zoom
  const onWheel = (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.08 : 0.93;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const oldZ = camera.current.zoom;
    const newZ = Math.max(0.1, Math.min(50, oldZ * factor));
    camera.current.x = mx - (mx - camera.current.x) * (newZ / oldZ);
    camera.current.zoom = newZ;
  };

  return (
    <div className="chart-cell">
      <canvas
        ref={canvasRef}
        className="chart-cell-canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onWheel={onWheel}
      />
    </div>
  );
};

// ── Infinite canvas page ─────────────────────────────────────────────────────
const InfiniteCanvas = () => (
  <div className="infinite-canvas-root">
    <div className="infinite-canvas-header">
      <a href="#main" className="nav-btn nav-btn--back">← Dashboard</a>
      <span className="infinite-canvas-title">⬡ EURUSD · Multi-Timeframe Canvas</span>
      <span className="infinite-canvas-meta">drag to pan · scroll to zoom</span>
    </div>
    <div className="infinite-canvas-grid">
      {TIMEFRAMES.map(tf => <ChartCell key={tf} timeframe={tf} />)}
    </div>
  </div>
);

export default InfiniteCanvas;
