import React, { useState, useEffect, useRef, useCallback } from 'react';
import Navbar from '../Navbar';
import NNTrainingDashboard from './NNTrainingDashboard';

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





function detectImprovedBox(ohlc) {
  if (!ohlc || ohlc.length < 10) return null;
  
  let n = ohlc.length;
  let searchingSwings = true;
  let anchorIndex = 0;
  let gotSH = false, gotSL = false;
  let shVal = -1, slVal = -1;
  let firstSwingIdx = null;
  let active = false;
  let rangeTop = -1, rangeBottom = -1;
  let activeBox = null;

  for (let i = 2; i < n; i++) {
    const h = ohlc[i].high, l = ohlc[i].low;
    const c = ohlc[i].close;
    const h1 = ohlc[i-1].high, l1 = ohlc[i-1].low;
    const h2 = ohlc[i-2].high, l2 = ohlc[i-2].low;

    const isSH = h1 > h2 && h1 >= h;
    const isSL = l1 < l2 && l1 <= l;

    if (active) {
      const isBreakout = c > rangeTop || c < rangeBottom;
      if (isBreakout) {
        activeBox.end = i - 1;
        return activeBox;
      } else {
        const age = i - activeBox.start + 1;
        if (age <= 5) {
          if (h > rangeTop) rangeTop = h;
          if (l < rangeBottom) rangeBottom = l;
        }
        activeBox.end = i;
      }
    }

    if (searchingSwings && !active && i > anchorIndex) {
      const sbi = i - 1;
      if (sbi > anchorIndex) {
        if (!isSH && !isSL) continue;
        if (!gotSH && isSH) { gotSH = true; shVal = h1; if (firstSwingIdx === null) firstSwingIdx = sbi; }
        if (!gotSL && isSL) { gotSL = true; slVal = l1; if (firstSwingIdx === null) firstSwingIdx = sbi; }
      }

      if (gotSH && gotSL && firstSwingIdx !== null) {
        let allInside = true;
        let tH = shVal, tL = slVal;
        let count = 0;
        for (let j = firstSwingIdx; j <= i; j++) {
          const age = j - firstSwingIdx + 1;
          if (ohlc[j].close >= tL && ohlc[j].close <= tH) {
            if (age <= 5) {
              if (ohlc[j].high > tH) tH = ohlc[j].high;
              if (ohlc[j].low < tL) tL = ohlc[j].low;
            }
            count++;
          } else { allInside = false; break; }
        }
        if (allInside && count >= 6) {
          rangeTop = tH; rangeBottom = tL;
          active = true; searchingSwings = false;
          activeBox = { start: firstSwingIdx, end: i, top: rangeTop, bottom: rangeBottom };
        }
      }
    }
  }
  return activeBox;
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

  // ── 1. Find the "True" Box indices in the full filtered array ──────────
  const impFull = detectImprovedBox(allFiltered);
  let finalStart = 0, finalEnd = allFiltered.length - 1;

  if (impFull) {
    finalStart = impFull.start;
    finalEnd   = impFull.end;
  } else if (meta && meta.timeStart != null && meta.timeEnd != null) {
    const times   = allFiltered.map(c => new Date(c.time).getTime());
    const tsStart = typeof meta.timeStart === 'number' ? meta.timeStart : new Date(meta.timeStart).getTime();
    const tsEnd   = typeof meta.timeEnd   === 'number' ? meta.timeEnd   : new Date(meta.timeEnd).getTime();
    const findIdx = ts => {
      let best = 0, bestDiff = Infinity;
      times.forEach((t, i) => { const d = Math.abs(t - ts); if (d < bestDiff) { bestDiff = d; best = i; } });
      return best;
    };
    finalStart = findIdx(tsStart);
    finalEnd   = findIdx(tsEnd);
  }

  // ── 2. Apply 5+5 Context Windowing ───────────────────────────────────────
  const CONTEXT = 5;
  const winStart = Math.max(0, finalStart - CONTEXT);
  const winEnd   = Math.min(allFiltered.length - 1, finalEnd + CONTEXT);
  const ohlc     = allFiltered.slice(winStart, winEnd + 1);

  // Re-map indices to the new cropped window
  const relStart = finalStart - winStart;
  const relEnd   = finalEnd   - winStart;

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


  // ── Single Dashed Yellow Box System ──────────────────────────────────────
  let finalBox = null;

  if (meta || impFull) {
    finalBox = {
      x1: sx + relStart * (cw + cg) + (cw / 2),
      x2: sx + relEnd * (cw + cg) + (cw / 2) + cw,
      y1: toY(impFull ? impFull.top : meta.priceHigh),
      y2: toY(impFull ? impFull.bottom : meta.priceLow)
    };
  }

  if (finalBox) {
    const bx = Math.min(finalBox.x1, finalBox.x2);
    const bw = Math.abs(finalBox.x2 - finalBox.x1);
    const by = Math.min(finalBox.y1, finalBox.y2);
    const bh = Math.abs(finalBox.y2 - finalBox.y1);

    ctx.save();
    ctx.strokeStyle = '#F7C948'; ctx.lineWidth = 1.2;
    ctx.setLineDash([5, 3]);
    ctx.strokeRect(bx, by, bw, bh);
    ctx.fillStyle = 'rgba(247,201,72,0.02)';
    ctx.fillRect(bx, by, bw, bh);
    
    // Draw NN prediction if available
    if (meta && meta.nn_box) {
      const { nn_box } = meta;
      
      const tsStart = typeof nn_box.timeStart === 'number' ? nn_box.timeStart : new Date(nn_box.timeStart).getTime() / 1000;
      const tsEnd   = typeof nn_box.timeEnd   === 'number' ? nn_box.timeEnd   : new Date(nn_box.timeEnd).getTime() / 1000;
      
      const times = allFiltered.map(c => typeof c.time === 'number' ? c.time : new Date(c.time).getTime() / 1000);
      const findIdx = ts => {
        let best = 0, bestDiff = Infinity;
        times.forEach((t, i) => { const d = Math.abs(t - ts); if (d < bestDiff) { bestDiff = d; best = i; } });
        return best;
      };
      
      const nnStartRel = findIdx(tsStart) - winStart;
      const nnEndRel   = findIdx(tsEnd) - winStart;
      
      const nx1 = sx + nnStartRel * (cw + cg) + (cw / 2);
      const nx2 = sx + nnEndRel * (cw + cg) + (cw / 2) + cw;
      const ny1 = Math.max(0, Math.min(H, toY(nn_box.priceHigh)));
      const ny2 = Math.max(0, Math.min(H, toY(nn_box.priceLow)));
      
      const nbx = Math.max(0, Math.min(W, Math.min(nx1, nx2)));
      const nbw = Math.min(W - nbx, Math.abs(nx2 - nx1));
      const nby = Math.max(0, Math.min(H, Math.min(ny1, ny2)));
      const nbh = Math.min(H - nby, Math.abs(ny2 - ny1));

      ctx.strokeStyle = '#4A90D9';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      ctx.strokeRect(nbx, nby, nbw, nbh);
      ctx.fillStyle = 'rgba(74, 144, 217, 0.12)';
      ctx.fillRect(nbx, nby, nbw, nbh);
      
      // Confidence label
      ctx.font = '10px Inter, sans-serif';
      ctx.fillStyle = '#4A90D9';
      ctx.textAlign = 'right';
      ctx.fillText(`NN: ${Math.round((nn_box.confidence || 0) * 100)}%`, nbx + nbw - 2, nby - 4);
    }
    
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



// ── Caveman bullet compressor ────────────────────────────────────────────────
const FILLER = [
  /^(the lesson learned (from this (exercise|analysis|code) is( the importance of)?|here is that))/i,
  /^(this (suggests?|indicates?|shows?|means?|implies?|demonstrates?|highlights?|reveals?|confirms?|underscores?)( that| the)?)/i,
  /^(it is (important|essential|crucial|critical|key|vital|necessary) to)/i,
  /^(in (order|summary|conclusion|other words|this case),?)/i,
  /^(overall[,.]?|additionally[,.]?|furthermore[,.]?|moreover[,.]?|therefore[,.]?|thus[,.]?|hence[,.]?)/i,
  /^(by (doing so|analyzing|refining|adjusting|examining),?)/i,
  /^(the (key|main|primary|central|core) (takeaway|lesson|insight|point|idea|message) (is|here)?)/i,
  /^(this (is|can be) (a|an|the)?)/i,
];

function crushToBullets(raw) {
  if (!raw || typeof raw !== 'string') return [];
  // Split on sentence endings, numbered lists, or line breaks
  const sentences = raw
    .replace(/\n+/g, ' ')
    .split(/(?<=[.!?])\s+|(?=\d+\.\s)|(?=[-•*]\s)/)
    .map(s => s.replace(/^[\d.•*-]+\s*/, '').trim())
    .filter(s => s.length > 15 && s.length < 300);

  const bullets = [];
  for (const s of sentences) {
    if (bullets.length >= 5) break;
    let b = s;
    // Strip filler openers
    for (const re of FILLER) b = b.replace(re, '').trim();
    // Remove leading articles/pronouns
    b = b.replace(/^(The |A |An |It |This |These |That |Those )/i, '');
    // Capitalise first char
    b = b.charAt(0).toUpperCase() + b.slice(1);
    // Strip trailing period
    b = b.replace(/\.$/, '');
    if (b.length > 10) bullets.push(b);
  }
  return bullets;
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
  const [boxes,      setBoxes]      = useState([]);
  const [idx,        setIdx]        = useState(0);
  const [filter,     setFilter]     = useState('');
  const [stats,      setStats]      = useState({ total: 0, pending: 0, labeled: 0 });
  const [drawBoxes,  setDrawBoxes]  = useState([]);   // committed array — set on mouseUp only
  const [loading,    setLoading]    = useState(true);
  const [saving,     setSaving]     = useState(false);
  const [toast,      setToast]      = useState(null);
  const [zoom,       setZoom]       = useState(1.0);
  const [magnet,     setMagnet]     = useState(true);
  const [lessons,    setLessons]    = useState([]);
  const [seenHashes, setSeenHashes] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem('rf_seen_hashes') || '[]')); }
    catch { return new Set(); }
  });
  const [showAllInsights, setShowAllInsights] = useState(false);
  const [lastBox,    setLastBox]    = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const zoomRef               = useRef(1.0);
  const panYRef               = useRef(0);
  const priceZoomRef          = useRef(1.0);
  const mouseXRef             = useRef(0);
  const ohlcRef               = useRef(null);
  const metaRef               = useRef(null);

  // ── Multi-box drag engine ─────────────────────────────────────────────────
  const dragRef       = useRef(false);
  const modeRef       = useRef('NONE');
  const offRef        = useRef({ x: 0, y: 0 });
  const drawBoxesRef  = useRef([]);      // live boxes array during drag
  const activeIdxRef  = useRef(-1);
  const lastClickTimeRef = useRef(0);     // which box is being interacted
  const rafRef        = useRef(null);
  const magnetRef     = useRef(true);
  const priceRangeRef = useRef({ maxP: 0, minP: 0, rng: 0.0001 });

  const canvasRef     = useRef(null);
  const overlayRef    = useRef(null);
  const dragCanvasRef = useRef(null);
  const filteredOhlcRef = useRef(null);

  // ── Coordinate Conversion Helpers ─────────────────────────────────────────
  const getChartCoords = useCallback((mx, my) => {
    const W = canvasRef.current?.width || 900;
    const H = canvasRef.current?.height || 500;
    const ohlc = filteredOhlcRef.current || [];
    const zoom = zoomRef.current;
    const pz = priceZoomRef.current;
    const py = panYRef.current;

    const cw = Math.max(2, Math.round(CW * zoom));
    const cg = Math.max(1, Math.round(CG * zoom));
    const cW = W - PAD.l - PAD.r;
    const cH = H - PAD.t - PAD.b;
    const totW = ohlc.length * (cw + cg);
    const sx = PAD.l + Math.max(0, (cW - totW) / 2);

    const { maxP, minP, rng } = priceRangeRef.current;
    const midP = (maxP + minP) / 2 + py;
    const halfRng = (rng / 2) / pz;
    const adjMax = midP + halfRng;
    const adjRng = halfRng * 2;

    const idx = Math.round((mx - sx) / (cw + cg));
    const price = adjMax - (my - PAD.t) / cH * adjRng;

    return { idx, price };
  }, []);

  const getPixelCoords = useCallback((idx, price) => {
    const W = canvasRef.current?.width || 900;
    const H = canvasRef.current?.height || 500;
    const ohlc = filteredOhlcRef.current || [];
    const zoom = zoomRef.current;
    const pz = priceZoomRef.current;
    const py = panYRef.current;

    const cw = Math.max(2, Math.round(CW * zoom));
    const cg = Math.max(1, Math.round(CG * zoom));
    const cW = W - PAD.l - PAD.r;
    const cH = H - PAD.t - PAD.b;
    const totW = ohlc.length * (cw + cg);
    const sx = PAD.l + Math.max(0, (cW - totW) / 2);

    const { maxP, minP, rng } = priceRangeRef.current;
    const midP = (maxP + minP) / 2 + py;
    const halfRng = (rng / 2) / pz;
    const adjMax = midP + halfRng;
    const adjRng = halfRng * 2;

    const pxX = sx + idx * (cw + cg) + (cw / 2);
    const pxY = PAD.t + ((adjMax - price) / adjRng) * cH;

    return { pxX, pxY };
  }, []);


  const box = boxes[idx] || null;

  const showToast = (msg, type = 'ok') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2800);
  };

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchBoxes = useCallback(async () => {
    setLoading(true);
    try {
      const qs  = filter ? `?limit=5000&status=${filter}` : '?limit=5000';
      const res = await fetch(`http://localhost:8000/api/training/all_boxes${qs}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const txt  = await res.text();
      const data = JSON.parse(txt);
      if (data.status === 'ok') {
        const fetched = data.boxes || [];
        // Shuffle to intermix timeframes randomly
        const shuffled = [...fetched].sort(() => Math.random() - 0.5);
        setBoxes(shuffled);
        setIdx(0);
        setDrawBoxes([]);
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

  const handleSync = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/training/sync', { method: 'POST' });
      const d = await res.json();
      if (d.status === 'ok') {
        showToast(`Synced ${d.synced} live boxes`, 'ok');
        fetchBoxes();
      } else {
        showToast('Sync failed: ' + d.message, 'err');
      }
    } catch (e) {
      showToast('Sync error: ' + e.message, 'err');
    }
    setLoading(false);
  };

  const handleTrain = async () => {
    if (!stats || (stats.labeled || 0) < 500) return;
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/training/retrain_nn', { method: 'POST' });
      const d = await res.clone().json();
      if (d.status === 'triggered' || d.status === 'already_running') {
        showToast('NN Training started', 'ok');
      } else {
        showToast('Training failed', 'err');
      }
    } catch (e) {
      showToast('Training error: ' + e.message, 'err');
    }
    setLoading(false);
  };

  // Mark all currently visible lessons as seen
  const markAllSeen = useCallback((lessonList) => {
    const hashes = (lessonList || []).map(l => l.hash).filter(Boolean);
    if (!hashes.length) return;
    setSeenHashes(prev => {
      const next = new Set([...prev, ...hashes]);
      try { localStorage.setItem('rf_seen_hashes', JSON.stringify([...next])); } catch (_) {}
      return next;
    });
  }, []);

  useEffect(() => { 
    let active = true;
    fetchBoxes(); 
    fetchStats(); 
    fetchLessons(); 

    const poll = async () => {
      if (!active || saving) return;
      try {
        const qs  = filter ? `?limit=5000&status=${filter}` : '?limit=5000';
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

  // Ensure idx is always in bounds when boxes list changes
  useEffect(() => {
    if (boxes.length > 0 && idx >= boxes.length) {
      setIdx(boxes.length - 1);
    }
  }, [boxes.length, idx]);

  // sync magnetRef whenever magnet state changes
  useEffect(() => { magnetRef.current = magnet; }, [magnet]);

  const paintDragCanvasRef = useRef(null);

  // ── Draw chart on box or zoom change ─────────────────────────────────────
  const redraw = useCallback((z, py, pz) => {
    if (!canvasRef.current || !ohlcRef.current) return;
    const pY = py !== undefined ? py : panYRef.current;
    const pZ = pz !== undefined ? pz : priceZoomRef.current;
    const filtered = renderChart(canvasRef.current, ohlcRef.current, metaRef.current, z, pY, pZ);
    if (filtered) {
      filteredOhlcRef.current = filtered;
      if (paintDragCanvasRef.current) {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(paintDragCanvasRef.current);
      }
    }
  }, []);

  useEffect(() => {
    if (!box || !canvasRef.current) return;
    setDrawBoxes([]);
    drawBoxesRef.current = [];
    // Clear drag canvas
    if (dragCanvasRef.current) {
      const dc = dragCanvasRef.current.getContext('2d');
      dc.clearRect(0, 0, dragCanvasRef.current.width, dragCanvasRef.current.height);
    }
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
      panYRef.current      = 0;
      priceZoomRef.current = 1.0;
      const filtered = renderChart(canvasRef.current, ohlc, meta, zoomRef.current, 0, 1.0);
      if (filtered) {
        filteredOhlcRef.current = filtered;
        // Precompute price range for O(1) magnet snapping
        const highs = filtered.map(c => c.high);
        const lows  = filtered.map(c => c.low);
        const maxP  = Math.max(...highs);
        const minP  = Math.min(...lows);
        priceRangeRef.current = { maxP, minP, rng: maxP - minP || 0.0001 };
      }
    } catch (e) {
      console.error('Render error', e);
    }
  }, [box, refreshKey]);

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
      else if (e.key === 'Escape')                  { clearDrawing(); }
      else if (e.key === 'ArrowRight')              setIdx(i => Math.min(i + 1, boxes.length - 1));
      else if (e.key === 'ArrowLeft')               setIdx(i => Math.max(i - 1, 0));
      else if (e.key === 'v' || e.key === 'V')      { e.preventDefault(); handleValidate(); }
      else if (e.ctrlKey && e.key === 'z')          { e.preventDefault(); handleUndo(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawBoxes, box, boxes.length]);

  // ── Mouse interaction ──────────────────────────────────────────────────────
  // ── Paint live box on drag canvas (called inside RAF) ─────────────────────
  const paintDragCanvas = useCallback(() => {
    const dc = dragCanvasRef.current;
    if (!dc) return;
    const ctx = dc.getContext('2d');
    ctx.clearRect(0, 0, dc.width, dc.height);
    const bxs = drawBoxesRef.current;
    if (!bxs.length) return;
    const activeIdx = activeIdxRef.current;

    bxs.forEach((b, i) => {
      if (!b) return;
      const isActive = i === activeIdx;

      // Convert chart coords to pixels for rendering
      const p1 = getPixelCoords(b.i1, b.p1);
      const p2 = getPixelCoords(b.i2, b.p2);

      const lx = Math.min(p1.pxX, p2.pxX);
      const ly = Math.min(p1.pxY, p2.pxY);
      const lw = Math.abs(p2.pxX - p1.pxX);
      const lh = Math.abs(p2.pxY - p1.pxY);

      ctx.fillStyle = isActive ? 'rgba(41,98,255,0.10)' : 'rgba(41,98,255,0.04)';
      ctx.fillRect(lx, ly, lw, lh);
      ctx.strokeStyle = isActive ? '#2962FF' : '#2962FF88';
      ctx.lineWidth = isActive ? 1.5 : 1;
      ctx.strokeRect(lx + 0.5, ly + 0.5, lw - 1, lh - 1);
      
      ctx.fillStyle = isActive ? '#2962FF' : '#2962FF88';
      ctx.font = 'bold 10px monospace';
      ctx.fillText(`#${i + 1}`, lx + 4, ly + 12);

      if (isActive) {
        const hs = 5;
        const handles = [
          [p1.pxX, p1.pxY], [p2.pxX, p1.pxY], [p1.pxX, p2.pxY], [p2.pxX, p2.pxY],
          [(p1.pxX + p2.pxX) / 2, p1.pxY], [(p1.pxX + p2.pxX) / 2, p2.pxY],
          [p1.pxX, (p1.pxY + p2.pxY) / 2], [p2.pxX, (p1.pxY + p2.pxY) / 2],
        ];
        ctx.fillStyle = '#ffffff';
        ctx.strokeStyle = '#2962FF';
        ctx.lineWidth = 1;
        for (const [hx, hy] of handles) {
          ctx.beginPath();
          ctx.arc(hx, hy, hs, 0, Math.PI * 2);
          ctx.fill(); ctx.stroke();
        }
      }
    });
  }, [getPixelCoords]);
  paintDragCanvasRef.current = paintDragCanvas;


  // ── Snap mouse to candle grid (O(1) with precomputed range) ──────────────
  const snapToCandle = useCallback((mx, my, W, H) => {
    if (!magnetRef.current || !filteredOhlcRef.current) return { smx: mx, smy: my };
    const ohlc = filteredOhlcRef.current;
    const zoom = zoomRef.current;
    const cw = Math.max(2, Math.round(CW * zoom));
    const cg = Math.max(1, Math.round(CG * zoom));
    const cH = H - PAD.t - PAD.b;
    const cW = W - PAD.l - PAD.r;
    const totW = ohlc.length * (cw + cg);
    const sx = PAD.l + Math.max(0, (cW - totW) / 2);

    const cIdx = Math.max(0, Math.min(ohlc.length - 1, Math.round((mx - sx) / (cw + cg))));
    const smx = sx + cIdx * (cw + cg) + (cw / 2);

    const candle = ohlc[cIdx];
    let smy = my;
    if (candle) {
      const { maxP, minP, rng } = priceRangeRef.current;
      const midP    = (maxP + minP) / 2 + panYRef.current;
      const halfRng = (rng / 2) / priceZoomRef.current;
      const adjMax  = midP + halfRng;
      const adjRng  = halfRng * 2;
      const yH = PAD.t + ((adjMax - candle.high) / adjRng) * cH;
      const yL = PAD.t + ((adjMax - candle.low)  / adjRng) * cH;
      if (Math.abs(my - yH) < 30 || Math.abs(my - yL) < 30) {
        smy = Math.abs(my - yH) < Math.abs(my - yL) ? yH : yL;
      }
    }
    return { smx, smy };
  }, []);

  const onMouseDown = useCallback(e => {
    if (Date.now() - lastClickTimeRef.current < 300) return;
    const rect = overlayRef.current.getBoundingClientRect();
    const W = canvasRef.current?.width || 900;
    const H = canvasRef.current?.height || 500;
    const ratioX = W / rect.width;
    const ratioY = H / rect.height;
    const mx = (e.clientX - rect.left) * ratioX;
    const my = (e.clientY - rect.top)  * ratioY;
    if (mx > W - PAD.r) return;

    const hs = 10;
    const bxs = drawBoxesRef.current;

    for (let i = bxs.length - 1; i >= 0; i--) {
      const b = bxs[i];
      if (!b) continue;
      
      const p1 = getPixelCoords(b.i1, b.p1);
      const p2 = getPixelCoords(b.i2, b.p2);
      const { pxX: x1, pxY: y1 } = p1;
      const { pxX: x2, pxY: y2 } = p2;

      const checkHandle = (hx, hy, mode) => {
        if (Math.abs(mx - hx) < hs && Math.abs(my - hy) < hs) {
          activeIdxRef.current = i;
          modeRef.current = mode;
          dragRef.current = true;
          return true;
        }
        return false;
      };

      if (checkHandle(x1, y1, 'TL')) return;
      if (checkHandle(x2, y1, 'TR')) return;
      if (checkHandle(x1, y2, 'BL')) return;
      if (checkHandle(x2, y2, 'BR')) return;
      if (checkHandle((x1+x2)/2, y1, 'T')) return;
      if (checkHandle((x1+x2)/2, y2, 'B')) return;
      if (checkHandle(x1, (y1+y2)/2, 'L')) return;
      if (checkHandle(x2, (y1+y2)/2, 'R')) return;

      const mnX=Math.min(x1,x2), mxX=Math.max(x1,x2);
      const mnY=Math.min(y1,y2), mxY=Math.max(y1,y2);
      if (mx>mnX && mx<mxX && my>mnY && my<mxY) {
        activeIdxRef.current = i;
        modeRef.current = 'MOVE';
        offRef.current = { x: mx, y: my, i1: b.i1, p1: b.p1, i2: b.i2, p2: b.p2 };
        dragRef.current = true;
        paintDragCanvas();
        return;
      }
    }

    const { idx, price } = getChartCoords(mx, my);
    const newBox = { i1: idx, p1: price, i2: idx, p2: price };
    drawBoxesRef.current = [...bxs, newBox];
    activeIdxRef.current = drawBoxesRef.current.length - 1;
    modeRef.current = 'DRAW';
    dragRef.current = true;
    paintDragCanvas();
  }, [getPixelCoords, getChartCoords, paintDragCanvas]);


  useEffect(() => {
    const onMove = e => {
      if (!dragRef.current) return;
      const rect = overlayRef.current?.getBoundingClientRect();
      if (!rect) return;
      const W = canvasRef.current?.width  || 900;
      const H = canvasRef.current?.height || 500;
      const ratioX = W / rect.width;
      const ratioY = H / rect.height;
      const mx = (e.clientX - rect.left) * ratioX;
      const my = (e.clientY - rect.top)  * ratioY;

      const { smx, smy } = snapToCandle(mx, my, W, H);
      const { idx: sIdx, price: sPrice } = getChartCoords(smx, smy);
      const { idx: uIdx, price: uPrice } = getChartCoords(mx, my);

      const ai = activeIdxRef.current;
      const bxs = drawBoxesRef.current;
      if (ai < 0 || ai >= bxs.length) return;
      const b = bxs[ai];
      if (!b) return;

      const off = offRef.current;
      let updated;
      switch (modeRef.current) {
        case 'DRAW': updated = { ...b, i2: sIdx, p2: sPrice }; break;
        case 'MOVE': {
          const dIdx = uIdx - getChartCoords(off.x, off.y).idx;
          const dPrice = uPrice - getChartCoords(off.x, off.y).price;
          updated = { ...b, i1: off.i1 + dIdx, i2: off.i2 + dIdx, p1: off.p1 + dPrice, p2: off.p2 + dPrice };
          break;
        }
        case 'TL': updated = { ...b, i1: sIdx, p1: sPrice }; break;
        case 'TR': updated = { ...b, i2: sIdx, p1: sPrice }; break;
        case 'BL': updated = { ...b, i1: sIdx, p2: sPrice }; break;
        case 'BR': updated = { ...b, i2: sIdx, p2: sPrice }; break;
        case 'T':  updated = { ...b, p1: sPrice }; break;
        case 'B':  updated = { ...b, p2: sPrice }; break;
        case 'L':  updated = { ...b, i1: sIdx }; break;
        case 'R':  updated = { ...b, i2: sIdx }; break;
        default: return;
      }
      const next = [...bxs];
      next[ai] = updated;
      drawBoxesRef.current = next;

      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(paintDragCanvas);
    };

    const onUp = () => {
      lastClickTimeRef.current = Date.now();
      if (!dragRef.current) return;
      dragRef.current = false;
      modeRef.current = 'NONE';
      setDrawBoxes([...drawBoxesRef.current]);
    };

    window.addEventListener('mousemove', onMove, { passive: true });
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [snapToCandle, getChartCoords, paintDragCanvas]);


  // ── Save / Skip / Undo ───────────────────────────────────────────────────
  const advanceToNext = (removedBox) => {
    setLastBox(removedBox);
    setBoxes(prev => prev.filter(b => b.box_id !== removedBox.box_id));
    setRefreshKey(k => k + 1);
    setDrawBoxes([]);
    drawBoxesRef.current = [];
    if (dragCanvasRef.current) {
      dragCanvasRef.current.getContext('2d').clearRect(0,0,dragCanvasRef.current.width,dragCanvasRef.current.height);
    }
    fetchStats();
    fetchLessons();
  };

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
        advanceToNext(box);
      } else {
        showToast('Validation failed', 'err');
      }
    } catch (e) { showToast('Network error', 'err'); }
    setSaving(false);
  };



  const handleSave = async () => {
    const bxs = drawBoxes.length > 0 ? drawBoxes : drawBoxesRef.current;
    if (!bxs.length || !box) return;
    setSaving(true);
    try {
      const W = canvasRef.current.width, H = canvasRef.current.height;
      const ohlc = filteredOhlcRef.current || ohlcRef.current;
      const zoom = zoomRef.current;
      const { maxP, minP, rng } = priceRangeRef.current;

      const cw   = Math.max(2, Math.round(CW * zoom));
      const cg   = Math.max(1, Math.round(CG * zoom));
      const cH   = H - PAD.t - PAD.b;
      const cW   = W - PAD.l - PAD.r;
      const totW = ohlc.length * (cw + cg);
      const sx   = PAD.l + Math.max(0, (cW - totW) / 2);

      const midP    = (maxP + minP) / 2 + panYRef.current;
      const halfRng = (rng / 2) * 1.2 / priceZoomRef.current; // Synchronized 1.2x buffer
      const adjMax  = midP + halfRng;
      const adjRng  = halfRng * 2;

      const userBoxes = bxs.filter(Boolean).map(b => {
        const startIdx = Math.max(0, Math.min(ohlc.length - 1, Math.min(b.i1, b.i2)));
        const endIdx   = Math.min(ohlc.length - 1, Math.max(b.i1, b.i2));

        const timeStart = ohlc[startIdx]?.time || ohlc[0].time;
        const timeEnd   = ohlc[endIdx]?.time || ohlc[ohlc.length - 1].time;

        const priceHigh = Math.max(b.p1, b.p2);
        const priceLow  = Math.min(b.p1, b.p2);

        return { timeStart, timeEnd, priceHigh, priceLow };
      });

      const payload = {
        box_id: box.box_id,
        user_box: userBoxes.length === 1 ? userBoxes[0] : userBoxes
      };
      
      const res = await fetch('http://localhost:8000/api/training/label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('Labeled ✓');
        advanceToNext(box);
      } else {
        const d = JSON.parse(await res.text());
        showToast('Save failed: ' + (d.detail || '?'), 'err');
      }
    } catch (e) { showToast('Network error', 'err'); }
    setSaving(false);
  };

  const handleSkip = async () => {
    if (!box || saving) return;
    setSaving(true);
    try {
      const res = await fetch('http://localhost:8000/api/training/label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ box_id: box.box_id, is_skip: true }),
      });
      if (res.ok) {
        showToast('Skipped');
        advanceToNext(box);
      } else {
        showToast('Skip failed', 'err');
      }
    } catch (e) { showToast('Network error', 'err'); }
    setSaving(false);
  };

  const clearDrawing = useCallback(() => {
    drawBoxesRef.current = [];
    dragRef.current    = false;
    modeRef.current    = 'NONE';
    activeIdxRef.current = -1;
    setDrawBoxes([]);
    if (dragCanvasRef.current) {
      const dc = dragCanvasRef.current.getContext('2d');
      dc.clearRect(0, 0, dragCanvasRef.current.width, dragCanvasRef.current.height);
    }
  }, []);

  const nav = d => {
    setIdx(i => Math.max(0, Math.min(boxes.length-1, i+d)));
    clearDrawing();
  };

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
            {[['ALL',''],['LABELED','LABELED'],['SKIPPED','SKIPPED'],['NEEDS SHOT','PENDING_SCREENSHOT']].map(([lbl, val]) => (
              <button key={lbl} onClick={() => setFilter(val)}
                className={`text-[11px] font-bold px-3 py-1.5 rounded-lg border transition-all
                  ${filter===val ? 'border-[#2962FF] text-[#2962FF] bg-[#2962FF15]' : 'border-[#2A2E39] text-[#787B86] hover:text-white'}`}>
                {lbl}
              </button>
            ))}
            
            <div className="w-[1px] h-6 bg-[#2A2E39] mx-1 self-center" />
            
            <button onClick={handleSync}
              className="text-[11px] font-bold px-3 py-1.5 rounded-lg border border-[#2962FF30] text-[#2962FF] hover:bg-[#2962FF10] transition-all flex items-center gap-2">
              Sync Live
            </button>

            <button onClick={handleTrain}
              disabled={(stats.labeled || 0) < 500}
              className={`text-[11px] font-bold px-3 py-1.5 rounded-lg border transition-all flex items-center gap-2 ${(stats.labeled || 0) >= 500 ? 'border-[#00E67630] text-[#00E676] hover:bg-[#00E67610]' : 'border-[#363A45] text-[#787B86] opacity-50 cursor-not-allowed'}`}>
              Train Model
            </button>
          </div>

          {/* Stats */}
          <div className="flex gap-3">
            {[['Labeled', stats.labeled||0, '#26A69A']].map(([l,v,c]) => (
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
              <div key={box?.box_id || 'none'} className="relative bg-[#0B0E14] rounded-2xl border border-[#2A2E39] overflow-hidden shadow-2xl"
                style={{ height: '500px' }}>
                {/* Layer 1: OHLC chart */}
                {(!ohlcRef.current || ohlcRef.current.length === 0) && (
                  <div className="absolute inset-0 flex items-center justify-center bg-[#0B0E14] z-10">
                    <div className="text-center">
                      <p className="text-[#787B86] text-sm mb-2">No candle data available for this box</p>
                      <p className="text-[#434651] text-xs">Try skipping or syncing live data again</p>
                    </div>
                  </div>
                )}
                <canvas ref={canvasRef} width={900} height={500}
                  className="absolute inset-0 w-full h-full pointer-events-none" />
                {/* Layer 2: live drag box (canvas — no React re-renders) */}
                <canvas ref={dragCanvasRef} width={900} height={500}
                  className="absolute inset-0 w-full h-full pointer-events-none" />
                {/* Layer 3: transparent mouse overlay */}
                <div ref={overlayRef} onMouseDown={onMouseDown}
                  onMouseMove={e => {
                    const rect = overlayRef.current?.getBoundingClientRect();
                    if (rect) {
                      mouseXRef.current = (e.clientX - rect.left) * (canvasRef.current?.width / rect.width);
                      const W = canvasRef.current?.width || 900;
                      overlayRef.current.style.cursor = mouseXRef.current > W - PAD.r ? 'ns-resize' : 'crosshair';
                    }
                  }}
                  className="absolute inset-0 cursor-crosshair" />
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
                  <button onClick={handleSave} disabled={drawBoxes.length === 0 || saving}
                    className={`flex-1 h-12 rounded-xl font-bold text-sm uppercase tracking-widest transition-all
                      ${drawBoxes.length > 0 && !saving ? 'bg-[#26A69A] hover:bg-[#1E8A7E] text-white' : 'bg-[#1E222D] text-[#434651] cursor-not-allowed'}`}>
                    {saving ? 'Saving…' : 'Confirm & Next'}
                  </button>
                  <button onClick={clearDrawing} disabled={drawBoxes.length === 0}
                    title="Clear drawing (Esc)"
                    className={`px-4 h-12 rounded-xl font-bold border transition-all uppercase tracking-widest text-[11px]
                      ${drawBoxes.length > 0 ? 'bg-[#1E222D] border-[#F7C948] text-[#F7C948] hover:bg-[#F7C94815]' : 'bg-[#131722] border-[#2A2E39] text-[#434651] cursor-not-allowed'}`}>
                    ✕ Clear
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


              <NNTrainingDashboard />

              <div className="bg-[#131722] p-5 rounded-2xl border border-[#2A2E39]">
                <h3 className="text-[10px] font-bold text-[#787B86] uppercase tracking-widest mb-3">Box Details</h3>
                {(() => {
                  let metaRaw = {};
                  try { metaRaw = typeof box.original_meta === 'string' ? JSON.parse(box.original_meta) : (box.original_meta || {}); } catch(e){}
                  const startT = box.time_start_ms || box.timeStart || metaRaw.timeStart;
                  const endT = box.time_end_ms || box.timeEnd || metaRaw.timeEnd;
                  const fmt = t => t ? (new Date(t).toISOString().replace('T', ' ').slice(0,16)) : 'N/A';
                  return [
                    ['ID',      box.box_id],
                    ['Symbol',  box.symbol],
                    ['TF',      (box.timeframe||'').toUpperCase()],
                    ['Start',   fmt(startT)],
                    ['End',     fmt(endT)],
                    ['High',    box.price_high?.toFixed(5)],
                    ['Low',     box.price_low?.toFixed(5)],
                    ['Status',  box.status],
                    ['Created', (box.created_at||'').slice(0,16)],
                  ];
                })().map(([l,v]) => (
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
