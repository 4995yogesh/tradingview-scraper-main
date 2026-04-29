import React, { useState, useEffect, useRef, useCallback } from 'react';
import Navbar from '../Navbar';

// ── Canvas Chart Renderer constants ──────────────────────────────────────────
const CW = 10, CG = 2;
const PAD = { t: 24, b: 24, l: 8, r: 72 };

function isWeekendCandle(timeStr) {
  try {
    const d = new Date(timeStr);
    const dow = d.getUTCDay(); // 0=Sun, 6=Sat
    return dow === 0 || dow === 6;
  } catch { return false; }
}

function renderChart(canvas, ohlcRaw, meta, zoom = 1, panY = 0, priceZoom = 1) {
  if (!canvas || !ohlcRaw || ohlcRaw.length === 0) return;

  // Filter ghost candles and weekends
  const allFiltered = ohlcRaw.filter(c => {
    if (c.open === c.high && c.high === c.low && c.low === c.close) return false;
    if (isWeekendCandle(c.time)) return false;
    return true;
  });

  if (allFiltered.length === 0) return;

  // ── Find box boundaries in filtered array ─────────────────────────────────
  const CONTEXT = 5; // candles to show either side of box
  let startIdx = 0, endIdx = allFiltered.length - 1;

  if (meta && meta.timeStart != null && meta.timeEnd != null) {
    const times   = allFiltered.map(c => new Date(c.time).getTime());
    const tsStart = typeof meta.timeStart === 'number' ? meta.timeStart : new Date(meta.timeStart).getTime();
    const tsEnd   = typeof meta.timeEnd   === 'number' ? meta.timeEnd   : new Date(meta.timeEnd).getTime();
    const findIdx = ts => {
      let best = 0, bestDiff = Infinity;
      times.forEach((t, i) => { const d = Math.abs(t - ts); if (d < bestDiff) { bestDiff = d; best = i; } });
      return best;
    };
    startIdx = findIdx(tsStart);
    endIdx   = findIdx(tsEnd);
  }

  // Crop to [boxStart - CONTEXT .. boxEnd + CONTEXT]
  const winStart = Math.max(0, startIdx - CONTEXT);
  const winEnd   = Math.min(allFiltered.length - 1, endIdx + CONTEXT);
  const ohlc     = allFiltered.slice(winStart, winEnd + 1);

  // Box indices now relative to the cropped window
  const boxStartIdx = startIdx - winStart;
  const boxEndIdx   = endIdx   - winStart;

  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, W, H);

  const cw   = Math.max(2, Math.round(CW * zoom));
  const cg   = Math.max(1, Math.round(CG * zoom));
  const highs = ohlc.map(c => c.high);
  const lows  = ohlc.map(c => c.low);
  const maxP  = Math.max(...highs);
  const minP  = Math.min(...lows);
  const rng   = maxP - minP || 0.0001;
  const cH    = H - PAD.t - PAD.b;
  const cW    = W - PAD.l - PAD.r;
  // Vertical price zoom: shrink/expand visible range around midpoint
  const midP    = (maxP + minP) / 2 + panY;
  const halfRng = (rng / 2) / priceZoom;
  const adjMax  = midP + halfRng;
  const adjMin  = midP - halfRng;
  const adjRng  = adjMax - adjMin;
  const toY   = p => PAD.t + ((adjMax - p) / adjRng) * cH;
  const totW  = ohlc.length * (cw + cg);
  const sx    = PAD.l + Math.max(0, (cW - totW) / 2);

  // Grid
  for (let i = 0; i <= 5; i++) {
    const price = minP + (rng / 5) * i;
    const y = toY(price);
    ctx.strokeStyle = '#1a1a1a'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(W - PAD.r, y); ctx.stroke();
    ctx.fillStyle = '#999'; ctx.font = '10px monospace';
    ctx.fillText(price.toFixed(5), W - PAD.r + 4, y + 4);
  }

  // Consolidation box — centred using relative box indices
  if (meta && meta.priceHigh != null && meta.priceLow != null) {
    const bx = sx + boxStartIdx * (cw + cg) + (cw / 2);
    const bw = Math.max(1, (boxEndIdx - boxStartIdx + 1) * (cw + cg));
    const by = toY(meta.priceHigh);
    const bh = Math.max(2, toY(meta.priceLow) - by);

    ctx.save();
    ctx.strokeStyle = '#F7C948'; ctx.lineWidth = 1.0;
    ctx.setLineDash([5, 3]);
    ctx.strokeRect(bx, by, bw, bh);
    ctx.fillStyle = 'rgba(247,201,72,0.02)';
    ctx.fillRect(bx, by, bw, bh);
    ctx.restore();
  }

  // Candles — sequential index across windowed slice
  ohlc.forEach((c, i) => {
    const x   = sx + i * (cw + cg);
    const ok  = c.close >= c.open;
    const bt  = toY(Math.max(c.open, c.close));
    const bb  = toY(Math.min(c.open, c.close));
    const bh  = Math.max(1, bb - bt);
    const wx  = x + cw / 2;

    ctx.strokeStyle = '#D1D4DC'; ctx.lineWidth = 1;

    if (ok) {
      ctx.beginPath(); ctx.moveTo(wx, toY(c.high)); ctx.lineTo(wx, toY(c.low)); ctx.stroke();
      ctx.fillStyle = '#000000';
      ctx.fillRect(x, bt, cw, bh);
      ctx.strokeRect(x + 0.5, bt + 0.5, cw - 1, Math.max(1, bh - 1));
    } else {
      ctx.beginPath(); ctx.moveTo(wx, toY(c.high)); ctx.lineTo(wx, toY(c.low)); ctx.stroke();
      ctx.fillStyle = '#D1D4DC';
      ctx.fillRect(x, bt, cw, bh);
    }
  });

  // Return windowed (filtered + cropped) array so handleSave coordinates stay accurate
  return ohlc;
}



// ── Status colours ────────────────────────────────────────────────────────────
const SC = {
  PENDING_SCREENSHOT: '#F7C948',
  PENDING:            '#2962FF',
  LABELED:            '#26A69A',
  SKIPPED:            '#787B86',
  ANALYZED:           '#9C27B0',
};

// ── Component ─────────────────────────────────────────────────────────────────
const RefinementDashboard = () => {
  const [boxes,   setBoxes]   = useState([]);
  const [idx,     setIdx]     = useState(0);
  const [filter,  setFilter]  = useState('PENDING');
  const [stats,   setStats]   = useState({ total: 0, pending: 0, labeled: 0 });
  const [drawBox, setDrawBox] = useState(null);
  const [drag,    setDrag]    = useState(false);
  const [mode,    setMode]    = useState('NONE');
  const [off,     setOff]     = useState({ x: 0, y: 0 });
  const [loading, setLoading] = useState(true);
  const [saving,  setSaving]  = useState(false);
  const [toast,   setToast]   = useState(null);
  const [zoom,    setZoom]    = useState(1.0);
  const [magnet,  setMagnet]  = useState(true);
  const [lessons, setLessons] = useState([]);
  const [lastBox, setLastBox] = useState(null); // for Undo
  const zoomRef               = useRef(1.0);
  const panYRef               = useRef(0);      // price-axis pan offset
  const priceZoomRef          = useRef(1.0);    // vertical price scale zoom
  const mouseXRef             = useRef(0);      // last known mouse X on overlay
  const ohlcRef               = useRef(null);
  const metaRef               = useRef(null);

  const canvasRef    = useRef(null);
  const overlayRef   = useRef(null);
  const filteredOhlcRef = useRef(null); // filtered (no ghosts/weekends) — used for pixel↔OHLC mapping

  const box = boxes[idx] || null;

  const showToast = (msg, type = 'ok') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2800);
  };

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchBoxes = useCallback(async () => {
    setLoading(true);
    try {
      const qs  = filter ? `?limit=200&status=${filter}` : '?limit=200';
      const res = await fetch(`http://localhost:8000/api/training/all_boxes${qs}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const txt  = await res.text();
      const data = JSON.parse(txt);
      if (data.status === 'ok') {
        setBoxes(data.boxes || []);
        setIdx(0);
        setDrawBox(null);
      } else {
        showToast('API error', 'err');
      }
    } catch (e) {
      showToast('Fetch failed: ' + e.message, 'err');
    }
    setLoading(false);
  }, [filter]);

  const fetchStats = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/training/stats');
      const d   = await res.json();
      if (d.status === 'ok') setStats(d.stats);
    } catch (_) {}
  };

  const fetchLessons = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/training/lessons');
      const d   = await res.json();
      if (d.status === 'ok') setLessons(d.lessons || []);
    } catch (_) {}
  };

  useEffect(() => { 
    let active = true;
    fetchBoxes(); 
    fetchStats(); 
    fetchLessons(); 

    const poll = async () => {
      if (!active) return;
      try {
        const qs  = filter ? `?limit=200&status=${filter}` : '?limit=200';
        const res = await fetch(`http://localhost:8000/api/training/all_boxes${qs}`);
        if (!res.ok) return;
        const data = JSON.parse(await res.text());
        if (data.status === 'ok') {
          const newBoxes = data.boxes || [];
          setBoxes(prev => {
            // Full reconcile: keep local boxes only if they still exist in the server's fresh list
            const serverIds = new Set(newBoxes.map(b => b.box_id));
            const synced = prev.filter(b => serverIds.has(b.box_id));
            
            // Add any truly new boxes from server
            const localIds = new Set(synced.map(b => b.box_id));
            const novel = newBoxes.filter(b => !localIds.has(b.box_id));
            
            if (novel.length > 0 || synced.length !== prev.length) {
              return [...synced, ...novel];
            }
            return prev;
          });
          fetchStats();
          fetchLessons();
        }
      } catch (_) {}
    };

    const iv = setInterval(poll, 5000);
    return () => { active = false; clearInterval(iv); };
  }, [fetchBoxes, filter]);

  // ── Draw chart on box or zoom change ─────────────────────────────────────
  const redraw = useCallback((z, py, pz) => {
    if (!canvasRef.current || !ohlcRef.current) return;
    const pY = py !== undefined ? py : panYRef.current;
    const pZ = pz !== undefined ? pz : priceZoomRef.current;
    const filtered = renderChart(canvasRef.current, ohlcRef.current, metaRef.current, z, pY, pZ);
    if (filtered) filteredOhlcRef.current = filtered;
  }, []);

  useEffect(() => {
    if (!box || !canvasRef.current) return;
    setDrawBox(null);
    try {
      const ohlc = typeof box.ohlc_context === 'string'
        ? JSON.parse(box.ohlc_context)
        : (box.ohlc_context || []);
      const raw  = typeof box.original_meta === 'string'
        ? JSON.parse(box.original_meta)
        : (box.original_meta || {});
      const meta = {
        timeStart:  raw.timeStart  ?? null,
        timeEnd:    raw.timeEnd    ?? null,
        priceHigh:  raw.priceHigh  ?? box.price_high,
        priceLow:   raw.priceLow   ?? box.price_low,
      };
      ohlcRef.current      = ohlc;
      metaRef.current      = meta;
      panYRef.current      = 0; // reset pan on new box
      priceZoomRef.current = 1.0; // reset price zoom on new box
      const filtered = renderChart(canvasRef.current, ohlc, meta, zoomRef.current, 0, 1.0);
      if (filtered) filteredOhlcRef.current = filtered;
    } catch (e) {
      console.error('Render error', e);
    }
  }, [box]);

  useEffect(() => {
    zoomRef.current = zoom;
    redraw(zoom);
  }, [zoom, redraw]);

  // ── Wheel: chart body = horizontal zoom  |  price scale = vertical price zoom ────
  useEffect(() => {
    const el = overlayRef.current;
    if (!el) return;
    const onWheel = e => {
      e.preventDefault();
      e.stopPropagation();
      const W = canvasRef.current?.width || 900;
      const onPriceScale = mouseXRef.current > W - PAD.r;

      if (onPriceScale) {
        // Scroll on price scale → vertical price zoom
        priceZoomRef.current = Math.min(20, Math.max(0.2, priceZoomRef.current * (e.deltaY < 0 ? 1.12 : 0.89)));
        redraw(zoomRef.current, panYRef.current, priceZoomRef.current);
      } else {
        // Scroll on chart body → horizontal candle zoom
        setZoom(z => {
          const next = Math.min(6, Math.max(0.25, z * (e.deltaY < 0 ? 1.15 : 0.87)));
          return +next.toFixed(3);
        });
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [box, redraw]); // re-attach on new box

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = e => {
      if (e.key === 'Enter')                        { e.preventDefault(); handleSave(); }
      else if (e.key === 's' || e.key === 'S')      { e.preventDefault(); handleSkip(); }
      else if (e.key === 'Escape')                  { setDrawBox(null); setDrag(false); setMode('NONE'); }
      else if (e.key === 'ArrowRight')              setIdx(i => Math.min(i + 1, boxes.length - 1));
      else if (e.key === 'ArrowLeft')               setIdx(i => Math.max(i - 1, 0));
      else if (e.key === 'v' || e.key === 'V')      { e.preventDefault(); handleValidate(); }
      else if (e.ctrlKey && e.key === 'z')          { e.preventDefault(); handleUndo(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawBox, box, boxes.length]);

  // ── Mouse interaction ──────────────────────────────────────────────────────
  const onMouseDown = e => {
    const rect = overlayRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const W = canvasRef.current?.width || 900;
    // Block box drawing on the price scale (right side)
    if (mx > W - PAD.r) return;
    const hs = 10;
    if (drawBox) {
      const { x, y, w, h } = drawBox;
      if (Math.abs(mx-x)<hs && Math.abs(my-y)<hs)           { setMode('TL'); setDrag(true); return; }
      if (Math.abs(mx-(x+w))<hs && Math.abs(my-y)<hs)       { setMode('TR'); setDrag(true); return; }
      if (Math.abs(mx-x)<hs && Math.abs(my-(y+h))<hs)       { setMode('BL'); setDrag(true); return; }
      if (Math.abs(mx-(x+w))<hs && Math.abs(my-(y+h))<hs)   { setMode('BR'); setDrag(true); return; }
      if (Math.abs(mx-(x+w/2))<hs && Math.abs(my-y)<hs)     { setMode('T');  setDrag(true); return; }
      if (Math.abs(mx-(x+w/2))<hs && Math.abs(my-(y+h))<hs) { setMode('B');  setDrag(true); return; }
      if (Math.abs(mx-x)<hs && Math.abs(my-(y+h/2))<hs)     { setMode('L');  setDrag(true); return; }
      if (Math.abs(mx-(x+w))<hs && Math.abs(my-(y+h/2))<hs) { setMode('R');  setDrag(true); return; }
      const mnX=Math.min(x,x+w), mxX=Math.max(x,x+w), mnY=Math.min(y,y+h), mxY=Math.max(y,y+h);
      if (mx>mnX && mx<mxX && my>mnY && my<mxY) {
        setMode('MOVE'); setOff({ x: mx-x, y: my-y }); setDrag(true); return;
      }
    }
    setDrawBox({ x: mx, y: my, w: 0, h: 0 });
    setMode('DRAW'); setDrag(true);
  };

  useEffect(() => {
    if (!drag) return;
    const onMove = e => {
      const rect = overlayRef.current?.getBoundingClientRect();
      if (!rect) return;
      const W = canvasRef.current.width, H = canvasRef.current.height;
      const ratioX = W / rect.width;
      const ratioY = H / rect.height;
      const mx = (e.clientX - rect.left) * ratioX;
      const my = (e.clientY - rect.top) * ratioY;
      
      let smx = mx, smy = my;
      if (magnet && ohlcRef.current) {
        const ohlc = filteredOhlcRef.current || ohlcRef.current;
        const zoom = zoomRef.current;
        const cw = Math.max(2, Math.round(CW * zoom));
        const cg = Math.max(1, Math.round(CG * zoom));
        const cH = H - PAD.t - PAD.b;
        const cW = W - PAD.l - PAD.r;
        const totW = ohlc.length * (cw + cg);
        const sx = PAD.l + Math.max(0, (cW - totW) / 2);

        // Snap X to nearest candle center
        const cIdx = Math.max(0, Math.min(ohlc.length - 1, Math.round((mx - sx) / (cw + cg))));
        smx = sx + cIdx * (cw + cg) + (cw / 2);

        // Snap Y to nearest High/Low of that candle
        const candle = ohlc[cIdx];
        if (candle) {
          const highs = ohlc.map(c => c.high);
          const lows  = ohlc.map(c => c.low);
          const maxP  = Math.max(...highs);
          const minP  = Math.min(...lows);
          const rng   = (maxP - minP || 0.0001);
          const midP    = (maxP + minP) / 2 + panYRef.current;
          const halfRng = (rng / 2) / priceZoomRef.current;
          const adjMax  = midP + halfRng;
          const adjRng  = adjMax - (midP - halfRng);

          const yH = PAD.t + ((adjMax - candle.high) / adjRng) * cH;
          const yL = PAD.t + ((adjMax - candle.low) / adjRng) * cH;
          if (Math.abs(my - yH) < 30 || Math.abs(my - yL) < 30) {
            smy = Math.abs(my - yH) < Math.abs(my - yL) ? yH : yL;
          }
        }
      }

      // Convert back to screen-space for the DOM-based drawBox
      const finalX = smx / ratioX;
      const finalY = smy / ratioY;
      const rawMX  = mx / ratioX;
      const rawMY  = my / ratioY;

      setDrawBox(prev => {
        if (!prev) return prev;
        const { x, y, w, h } = prev;
        switch (mode) {
          case 'DRAW': return { ...prev, w: finalX-x, h: finalY-y };
          case 'MOVE': return { ...prev, x: rawMX-off.x, y: rawMY-off.y }; 
          case 'TL':   return { ...prev, x: finalX, y: finalY, w: w+(x-finalX), h: h+(y-finalY) };
          case 'TR':   return { ...prev, y: finalY, w: finalX-x, h: h+(y-finalY) };
          case 'BL':   return { ...prev, x: finalX, w: w+(x-finalX), h: finalY-y };
          case 'BR':   return { ...prev, w: finalX-x, h: finalY-y };
          case 'T':    return { ...prev, y: finalY, h: h+(y-finalY) };
          case 'B':    return { ...prev, h: finalY-y };
          case 'L':    return { ...prev, x: finalX, w: w+(x-finalX) };
          case 'R':    return { ...prev, w: finalX-x };
          default:     return prev;
        }
      });
    };
    const onUp = () => { setDrag(false); setMode('NONE'); };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [drag, mode, off, magnet]);

  // ── Save / Skip / Undo ───────────────────────────────────────────────────
  const handleUndo = async () => {
    if (!lastBox) return;
    try {
      const res = await fetch('http://localhost:8000/api/training/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ box_id: lastBox.box_id }),
      });
      if (res.ok) {
        showToast('Action Undone');
        setBoxes(prev => [lastBox, ...prev]);
        setIdx(0);
        setLastBox(null);
        fetchStats();
      }
    } catch (e) { showToast('Undo failed', 'err'); }
  };

  const handleValidate = async () => {
    if (!box) return;
    setSaving(true);
    try {
      const payload = {
        box_id: box.box_id,
        user_box: { 
          timeStart: box.time_start_ms || box.timeStart, 
          timeEnd: box.time_end_ms || box.timeEnd, 
          priceHigh: box.price_high || box.priceHigh, 
          priceLow: box.price_low || box.priceLow 
        }
      };
      const res = await fetch('http://localhost:8000/api/training/label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('Validated ✓');
        setLastBox(box);
        setBoxes(prev => {
          const next = prev.filter(b => b.box_id !== box.box_id);
          if (idx >= next.length && next.length > 0) setIdx(next.length - 1);
          return next;
        });
        setDrawBox(null); fetchStats(); fetchLessons();
      } else {
        showToast('Validation failed', 'err');
      }
    } catch (e) { showToast('Network error', 'err'); }
    setSaving(false);
  };

  const handleSave = async () => {
    if (!drawBox || !box) return;
    const rect = overlayRef.current.getBoundingClientRect();
    setSaving(true);
    try {
      // Convert pixels back to time/price — use filtered array to match what was actually rendered
      const W = canvasRef.current.width, H = canvasRef.current.height;
      const ohlc = filteredOhlcRef.current || ohlcRef.current;
      const zoom = zoomRef.current;
      
      const highs = ohlc.map(c => c.high);
      const lows  = ohlc.map(c => c.low);
      const maxP  = Math.max(...highs);
      const minP  = Math.min(...lows);
      const rng   = maxP - minP || 0.0001;
      
      const cw   = Math.max(2, Math.round(CW * zoom));
      const cg   = Math.max(1, Math.round(CG * zoom));
      const cH   = H - PAD.t - PAD.b;
      const cW   = W - PAD.l - PAD.r;
      const totW = ohlc.length * (cw + cg);
      const sx   = PAD.l + Math.max(0, (cW - totW) / 2);

      const realX = Math.min(drawBox.x, drawBox.x + drawBox.w);
      const realW = Math.abs(drawBox.w);
      const realY = Math.min(drawBox.y, drawBox.y + drawBox.h);
      const realH = Math.abs(drawBox.h);

      const startIdx = Math.max(0, Math.round((realX - sx) / (cw + cg)));
      const endIdx   = Math.min(ohlc.length - 1, Math.round((realX + realW - sx) / (cw + cg)));
      
      const timeStart = ohlc[startIdx]?.time || ohlc[0].time;
      const timeEnd   = ohlc[endIdx]?.time || ohlc[ohlc.length - 1].time;
      
      const priceHigh = maxP - ((realY - PAD.t) / cH) * rng;
      const priceLow  = maxP - ((realY + realH - PAD.t) / cH) * rng;

      const payload = {
        box_id: box.box_id,
        user_box: { timeStart, timeEnd, priceHigh, priceLow }
      };
      const res = await fetch('http://localhost:8000/api/training/label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('Labeled ✓');
        setLastBox(box);
        setBoxes(prev => {
          const next = prev.filter(b => b.box_id !== box.box_id);
          if (idx >= next.length && next.length > 0) setIdx(next.length - 1);
          return next;
        });
        setDrawBox(null); fetchStats(); fetchLessons();
      } else {
        const d = JSON.parse(await res.text());
        showToast('Save failed: ' + (d.detail || '?'), 'err');
      }
    } catch (e) { showToast('Network error', 'err'); }
    setSaving(false);
  };

  const handleSkip = async () => {
    if (!box) return;
    try {
      const res = await fetch('http://localhost:8000/api/training/label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ box_id: box.box_id, is_skip: true }),
      });
      if (res.ok) {
        showToast('Skipped');
        setLastBox(box);
        setBoxes(prev => {
          const next = prev.filter(b => b.box_id !== box.box_id);
          if (idx >= next.length && next.length > 0) setIdx(next.length - 1);
          return next;
        });
        setDrawBox(null); fetchStats(); fetchLessons();
      } else {
        showToast('Skip failed', 'err');
      }
    } catch (e) { showToast('Network error', 'err'); }
  };

  const nav = d => { setIdx(i => Math.max(0, Math.min(boxes.length-1, i+d))); setDrawBox(null); };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#0B0E14] text-[#D1D4DC] font-sans select-none">
      <Navbar />

      {/* Toast */}
      {toast && (
        <div className={`fixed top-20 right-6 z-50 px-5 py-3 rounded-xl font-bold shadow-2xl text-sm
          ${toast.type === 'err' ? 'bg-[#EF5350] text-white' : 'bg-[#26A69A] text-white'}`}>
          {toast.msg}
        </div>
      )}

      <div className="pt-20 px-6 pb-10 max-w-screen-xl mx-auto">

        {/* Header */}
        <div className="flex flex-wrap justify-between items-center mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Refine Studio</h1>
            <p className="text-xs text-[#787B86]">Canvas OHLC · 5+5 buffer · All DB boxes accessible</p>
          </div>

          {/* Filter pills */}
          <div className="flex gap-2 flex-wrap">
            {[['ALL',''],['PENDING','PENDING'],['LABELED','LABELED'],['SKIPPED','SKIPPED'],['NEEDS SHOT','PENDING_SCREENSHOT']].map(([lbl, val]) => (
              <button key={lbl} onClick={() => setFilter(val)}
                className={`text-[11px] font-bold px-3 py-1.5 rounded-lg border transition-all
                  ${filter===val ? 'border-[#2962FF] text-[#2962FF] bg-[#2962FF15]' : 'border-[#2A2E39] text-[#787B86] hover:text-white'}`}>
                {lbl}
              </button>
            ))}
          </div>

          {/* Stats */}
          <div className="flex gap-3">
            {[['Labeled', stats.labeled||0, '#26A69A'], ['Pending', stats.pending||0, '#2962FF']].map(([l,v,c]) => (
              <div key={l} className="bg-[#131722] px-4 py-2 rounded-xl border border-[#2A2E39] text-center">
                <div className="text-[10px] text-[#787B86] uppercase tracking-widest">{l}</div>
                <div className="text-xl font-bold" style={{ color: c }}>{v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Body */}
        {loading ? (
          <div className="h-[540px] flex items-center justify-center bg-[#131722] rounded-2xl border border-[#2A2E39]">
            <div className="w-10 h-10 border-4 border-[#2962FF] border-t-transparent rounded-full animate-spin" />
          </div>
        ) : !box ? (
          <div className="h-[400px] flex flex-col items-center justify-center bg-[#131722] rounded-2xl border border-[#2A2E39] border-dashed">
            <p className="text-xl text-[#787B86] mb-1">No boxes found</p>
            <p className="text-sm text-[#434651] mb-4">Change the filter or wait for chart detections.</p>
            <button onClick={fetchBoxes} className="text-[#2962FF] hover:underline font-medium">↺ Refresh</button>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

            {/* Chart Column */}
            <div className="lg:col-span-3 space-y-3">
              {/* Progress bar */}
              <div className="flex items-center justify-between text-xs text-[#787B86]">
                <span className="font-mono">{idx+1} / {boxes.length}</span>
                <div className="flex items-center gap-3">
                  <span style={{ color: SC[box.status] || '#fff' }}
                    className="font-bold uppercase text-[10px] bg-[#1E222D] px-2 py-1 rounded">
                    {box.status}
                  </span>
                  <span className="font-mono">{box.symbol} · {(box.timeframe||'').toUpperCase()}</span>
                </div>
              </div>

              {/* Canvas area */}
              <div className="relative bg-[#0B0E14] rounded-2xl border border-[#2A2E39] overflow-hidden shadow-2xl"
                style={{ height: '500px' }}>
                <canvas ref={canvasRef} width={900} height={500}
                  className="absolute inset-0 w-full h-full pointer-events-none" />
                {/* Mouse overlay */}
                <div ref={overlayRef} onMouseDown={onMouseDown}
                  onMouseMove={e => {
                    const rect = overlayRef.current?.getBoundingClientRect();
                    if (rect) {
                      mouseXRef.current = (e.clientX - rect.left) * (canvasRef.current?.width / rect.width);
                      // Update cursor based on zone
                      const W = canvasRef.current?.width || 900;
                      overlayRef.current.style.cursor = mouseXRef.current > W - PAD.r ? 'ns-resize' : 'crosshair';
                    }
                  }}
                  className="absolute inset-0 cursor-crosshair">
                  
                  {/* User drawn box handles */}
                  {drawBox && (() => {
                    const lx = drawBox.w < 0 ? drawBox.x + drawBox.w : drawBox.x;
                    const ly = drawBox.h < 0 ? drawBox.y + drawBox.h : drawBox.y;
                    const lw = Math.abs(drawBox.w);
                    const lh = Math.abs(drawBox.h);
                    return (
                      <div className="absolute border-2 border-[#2962FF] bg-[#2962FF15] pointer-events-none"
                        style={{ left: lx, top: ly, width: lw, height: lh }}>
                        {[
                          { s:'nw', c: 'nwse-resize', st:{top:'-4px',left:'-4px'} },
                          { s:'ne', c: 'nesw-resize', st:{top:'-4px',right:'-4px'} },
                          { s:'sw', c: 'nesw-resize', st:{bottom:'-4px',left:'-4px'} },
                          { s:'se', c: 'nwse-resize', st:{bottom:'-4px',right:'-4px'} },
                          { s:'t',  c: 'ns-resize',   st:{top:'-4px',left:'50%',marginLeft:'-4px'} },
                          { s:'b',  c: 'ns-resize',   st:{bottom:'-4px',left:'50%',marginLeft:'-4px'} },
                          { s:'l',  c: 'ew-resize',   st:{left:'-4px',top:'50%',marginTop:'-4px'} },
                          { s:'r',  c: 'ew-resize',   st:{right:'-4px',top:'50%',marginTop:'-4px'} },
                        ].map(h => (
                          <div key={h.s} className="absolute w-2.5 h-2.5 bg-white border border-[#2962FF] rounded-full pointer-events-auto shadow-lg"
                            style={{ ...h.st, cursor: h.c }} />
                        ))}
                      </div>
                    );
                  })()}
                </div>
              </div>

              {/* Zoom + Pan controls */}
              <div className="flex items-center justify-end gap-2 mb-1">
                <button onClick={() => setMagnet(!magnet)}
                  className={`flex items-center gap-1.5 px-2.5 h-7 rounded border transition-all font-mono text-[10px] ${magnet ? 'bg-[#2962FF20] border-[#2962FF] text-[#2962FF]' : 'bg-[#1E222D] border-[#363A45] text-[#787B86]'}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${magnet ? 'bg-[#2962FF] animate-pulse' : 'bg-[#787B86]'}`} />
                  MAGNET
                </button>
                <div className="w-px h-4 bg-[#363A45] mx-1" />
                <span className="text-[10px] text-[#434651] font-mono mr-1">SCROLL=pan · CTRL+SCROLL=zoom</span>
                <button onClick={() => setZoom(z => Math.max(0.25, +(z * 0.87).toFixed(3)))}
                  className="w-7 h-7 bg-[#1E222D] hover:bg-[#2A2E39] text-white rounded font-bold border border-[#363A45] transition-all text-sm flex items-center justify-center">−</button>
                <span className="text-xs font-mono text-[#787B86] w-12 text-center">{Math.round(zoom * 100)}%</span>
                <button onClick={() => setZoom(z => Math.min(6, +(z * 1.15).toFixed(3)))}
                  className="w-7 h-7 bg-[#1E222D] hover:bg-[#2A2E39] text-white rounded font-bold border border-[#363A45] transition-all text-sm flex items-center justify-center">+</button>
                <button onClick={() => { setZoom(1.0); panYRef.current = 0; priceZoomRef.current = 1.0; redraw(1.0, 0, 1.0); }}
                  className="text-[10px] px-2 h-7 bg-[#1E222D] hover:bg-[#2A2E39] text-[#787B86] hover:text-white rounded border border-[#363A45] transition-all font-mono">Reset</button>
              </div>

              {/* Action bar */}
              <div className="flex flex-wrap items-center justify-between gap-4">
                {/* Group 1: Navigation & Undo */}
                <div className="flex items-center gap-2">
                  <button onClick={() => nav(-1)} disabled={idx===0}
                    className="w-12 h-12 bg-[#1E222D] hover:bg-[#2A2E39] disabled:opacity-30 text-white rounded-xl font-bold border border-[#363A45] transition-all flex items-center justify-center">
                    ◀
                  </button>
                  <button onClick={handleUndo} disabled={!lastBox}
                    className={`flex items-center gap-2 px-4 h-12 rounded-xl font-bold border transition-all
                      ${lastBox ? 'bg-[#1E222D] border-[#363A45] text-[#787B86] hover:text-white hover:border-[#787B86]' : 'bg-[#131722] border-[#2A2E39] text-[#434651] cursor-not-allowed'}`}>
                    <span className="text-lg">↩</span>
                    <span className="text-[10px] uppercase tracking-wider">Undo</span>
                  </button>
                  <button onClick={() => nav(1)} disabled={idx===boxes.length-1}
                    className="w-12 h-12 bg-[#1E222D] hover:bg-[#2A2E39] disabled:opacity-30 text-white rounded-xl font-bold border border-[#363A45] transition-all flex items-center justify-center">
                    ▶
                  </button>
                </div>

                {/* Group 2: Labeling Actions */}
                <div className="flex-1 flex items-center gap-3">
                  <button onClick={handleValidate} disabled={saving}
                    className="px-5 h-12 bg-[#1E222D] hover:bg-[#2A2E39] text-[#2962FF] hover:text-white rounded-xl font-bold border border-[#2962FF30] transition-all uppercase tracking-widest text-[11px]">
                    Validate Original
                  </button>
                  <button onClick={handleSave} disabled={!drawBox || saving}
                    className={`flex-1 h-12 rounded-xl font-bold text-sm uppercase tracking-widest transition-all
                      ${drawBox && !saving ? 'bg-[#26A69A] hover:bg-[#1E8A7E] text-white' : 'bg-[#1E222D] text-[#434651] cursor-not-allowed'}`}>
                    {saving ? 'Saving…' : 'Confirm & Next'}
                  </button>
                  <button onClick={handleSkip}
                    className="px-5 h-12 bg-[#2D1E1E] hover:bg-[#3E2A2A] text-[#EF5350] hover:text-white rounded-xl font-bold border border-[#453636] transition-all uppercase tracking-widest text-[11px]">
                    Skip
                  </button>
                </div>
              </div>
            </div>

            {/* Info Panel */}
            <div className="space-y-4">
              <div className="bg-[#131722] p-5 rounded-2xl border border-[#2A2E39]">
                <h3 className="text-[10px] font-bold text-[#787B86] uppercase tracking-widest mb-3 flex items-center justify-between">
                  Gemini Insights
                  <span className="w-2 h-2 bg-[#9C27B0] rounded-full animate-pulse" />
                </h3>
                {lessons.length > 0 ? (
                  <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1 custom-scrollbar">
                    {lessons.map((l, i) => (
                      <div key={i} className="bg-[#1E222D50] p-3 rounded-lg border border-[#2A2E39] relative overflow-hidden">
                        <div className="absolute top-0 left-0 w-1 h-full bg-[#9C27B0]" />
                        <div className="text-[9px] text-[#9C27B0] font-bold uppercase mb-1">Observation {lessons.length - i}</div>
                        <p className="text-[11px] text-[#D1D4DC] leading-relaxed italic">"{l}"</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-6 border-2 border-dashed border-[#2A2E39] rounded-xl">
                    <div className="text-[#434651] text-[10px] uppercase font-bold mb-1">Learning...</div>
                    <div className="text-[10px] text-[#787B86]">Insights appear after AI analysis</div>
                  </div>
                )}
              </div>

              <div className="bg-[#131722] p-5 rounded-2xl border border-[#2A2E39]">
                <h3 className="text-[10px] font-bold text-[#787B86] uppercase tracking-widest mb-3">Box Details</h3>
                {[
                  ['ID',      box.box_id],
                  ['Symbol',  box.symbol],
                  ['TF',      (box.timeframe||'').toUpperCase()],
                  ['High',    box.price_high?.toFixed(5)],
                  ['Low',     box.price_low?.toFixed(5)],
                  ['Status',  box.status],
                  ['Created', (box.created_at||'').slice(0,16)],
                ].map(([l,v]) => (
                  <div key={l} className="mb-2">
                    <div className="text-[10px] text-[#434651] uppercase">{l}</div>
                    <div className="text-sm font-mono text-white truncate" title={v}>{v}</div>
                  </div>
                ))}
              </div>

              <div className="bg-[#131722] p-5 rounded-2xl border border-[#2A2E39]">
                <h3 className="text-[10px] font-bold text-[#787B86] uppercase tracking-widest mb-3">Shortcuts</h3>
                {[['Confirm','Enter'],['Skip','S'],['Clear','Esc'],['Navigate','← →']].map(([a,k]) => (
                  <div key={a} className="flex justify-between text-xs mb-2">
                    <span className="text-[#787B86]">{a}</span>
                    <span className="font-mono text-[#2962FF]">{k}</span>
                  </div>
                ))}
              </div>

              <div className="bg-[#131722] p-5 rounded-2xl border border-[#2A2E39]">
                <h3 className="text-[10px] font-bold text-[#787B86] uppercase tracking-widest mb-3">Legend</h3>
                <div className="space-y-2 text-xs">
                  <div className="flex items-center gap-2"><div className="w-8 h-0 border-t-2 border-dashed border-[#F7C948]"/><span>Machine box</span></div>
                  <div className="flex items-center gap-2"><div className="w-8 h-0 border-t-2 border-[#2962FF]"/><span>Your box</span></div>
                  <div className="flex items-center gap-2"><div className="w-3 h-3 rounded bg-[#2962FF] opacity-40"/><span>5-candle buffer</span></div>
                  <div className="flex items-center gap-2"><div className="w-3 h-3 rounded bg-[#26A69A]"/><span>Bull candle</span></div>
                  <div className="flex items-center gap-2"><div className="w-3 h-3 rounded bg-[#EF5350]"/><span>Bear candle</span></div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default RefinementDashboard;
