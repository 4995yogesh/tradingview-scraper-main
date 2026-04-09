import React, { useEffect, useRef, useCallback } from 'react';
import { buildViewport, TF_CONFIG } from './canvasUtils';
import {
  drawGrid,
  drawCandles,
  drawConsolidations,
  drawScenarios,
  drawNowLine,
  drawCrosshair,
} from './renderers';

/**
 * ChartCanvas — infinite canvas rendering surface.
 *
 * Performance changes:
 *  - panX / panY / zoom stored in REFS (not state) → zero React re-renders during drag
 *  - PointerEvent API replaces separate Mouse + Touch handlers
 *  - buildViewport only called when a dirty flag is set (not every RAF tick)
 *  - ResizeObserver correctly cleans up on unmount
 *  - activeTimeframes ref to avoid stale closure in RAF loop
 */
export default function ChartCanvas({
  candles = [],
  scenarios = {},
  consolidations = [],
  activeTimeframes = ['4H', '1H', '15m', '5m', '1m'],
}) {
  const containerRef = useRef(null);
  const canvasRef    = useRef(null);
  const rafRef       = useRef(null);
  const ctxRef       = useRef(null);

  // ── Viewport state stored in refs (no React re-renders on pan/zoom) ────────
  const panXRef  = useRef(0);      // ms time offset
  const panYRef  = useRef(0);      // price offset
  const zoomRef  = useRef(1);

  // Dirty flag: rebuild viewport on next frame
  const dirtyRef = useRef(true);
  const vpRef    = useRef(null);

  // Pointer interaction
  const dragging  = useRef(false);
  const lastPtr   = useRef({ x: 0, y: 0 });
  const pinchDist = useRef(null);
  const mouseRef  = useRef({ x: null, y: null });

  // Latest data refs (avoid stale closures in RAF)
  const candlesRef     = useRef(candles);
  const scenariosRef   = useRef(scenarios);
  const consolidRef    = useRef(consolidations);
  const activeRef      = useRef(activeTimeframes);

  useEffect(() => { candlesRef.current   = candles;          dirtyRef.current = true; }, [candles]);
  useEffect(() => { scenariosRef.current = scenarios;        dirtyRef.current = true; }, [scenarios]);
  useEffect(() => { consolidRef.current  = consolidations;   dirtyRef.current = true; }, [consolidations]);
  useEffect(() => { activeRef.current    = activeTimeframes; dirtyRef.current = true; }, [activeTimeframes]);

  // ── Render loop ─────────────────────────────────────────────────────────────
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx    = ctxRef.current;
    if (!canvas || !ctx) {
      rafRef.current = requestAnimationFrame(render);
      return;
    }

    const w = canvas.width;
    const h = canvas.height;

    // Rebuild viewport only when dirty
    if (dirtyRef.current || !vpRef.current) {
      vpRef.current    = buildViewport(
        candlesRef.current, scenariosRef.current,
        panXRef.current, panYRef.current, zoomRef.current,
        w, h
      );
      dirtyRef.current = false;
    }

    const vp = vpRef.current;

    // Full redraw (single canvas — no offscreen layers needed for this density)
    ctx.clearRect(0, 0, w, h);
    drawGrid(ctx, vp);
    drawCandles(ctx, candlesRef.current, vp);
    drawConsolidations(ctx, consolidRef.current, vp, activeRef.current);
    drawScenarios(ctx, scenariosRef.current, vp, activeRef.current, TF_CONFIG);
    drawNowLine(ctx, vp);
    drawCrosshair(ctx, mouseRef.current.x, mouseRef.current.y, vp);

    rafRef.current = requestAnimationFrame(render);
  }, []);

  // ── Canvas resize ───────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas    = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    ctxRef.current = canvas.getContext('2d', { alpha: false });

    const resize = () => {
      const dpr     = window.devicePixelRatio || 1;
      const w       = container.clientWidth;
      const h       = container.clientHeight;
      canvas.width  = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width  = w + 'px';
      canvas.style.height = h + 'px';
      ctxRef.current.scale(dpr, dpr);
      dirtyRef.current = true;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    rafRef.current = requestAnimationFrame(render);

    return () => {
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
    };
  }, [render]);

  // ── Pointer (Mouse + Touch unified) ────────────────────────────────────────
  const onPointerDown = useCallback((e) => {
    if (e.pointerType === 'touch' && e.isPrimary === false) return; // handled by pinch
    dragging.current = true;
    lastPtr.current  = { x: e.clientX, y: e.clientY };
    canvasRef.current?.setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (rect) {
      mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    if (!dragging.current || !vpRef.current) return;

    const dx = e.clientX - lastPtr.current.x;
    const dy = e.clientY - lastPtr.current.y;
    lastPtr.current = { x: e.clientX, y: e.clientY };

    const vp = vpRef.current;
    panXRef.current += -(dx / vp.width)  * (vp.timeMax  - vp.timeMin);
    panYRef.current += (dy / vp.height) * (vp.priceMax - vp.priceMin);
    dirtyRef.current = true;
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  const onPointerLeave = useCallback(() => {
    dragging.current     = false;
    mouseRef.current     = { x: null, y: null };
  }, []);

  const onWheel = useCallback((e) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.88 : 1.12;
    zoomRef.current  = Math.max(0.1, Math.min(12, zoomRef.current * factor));
    dirtyRef.current = true;
  }, []);

  // Pinch-zoom via touch events (two-finger)
  const onTouchStart = useCallback((e) => {
    if (e.touches.length === 2) {
      pinchDist.current = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
    }
  }, []);

  const onTouchMove = useCallback((e) => {
    if (e.touches.length === 2 && pinchDist.current) {
      e.preventDefault();
      const dist   = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      );
      const factor = dist / pinchDist.current;
      pinchDist.current = dist;
      zoomRef.current   = Math.max(0.1, Math.min(12, zoomRef.current * factor));
      dirtyRef.current  = true;
    }
  }, []);

  const onTouchEnd = useCallback(() => {
    pinchDist.current = null;
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', overflow: 'hidden', cursor: 'crosshair', touchAction: 'none' }}
    >
      <canvas
        ref={canvasRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerLeave}
        onWheel={onWheel}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        style={{ display: 'block', width: '100%', height: '100%' }}
      />
    </div>
  );
}
