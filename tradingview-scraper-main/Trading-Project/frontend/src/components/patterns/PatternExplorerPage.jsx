import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, RefreshCw, TrendingUp, TrendingDown, Minus,
  ChevronLeft, ChevronRight, Search, Filter, Database,
  BarChart2, Activity, Brain
} from 'lucide-react';

const API = 'http://127.0.0.1:8000';

// ── Colour tokens ──────────────────────────────────────────────────────────────
const C = {
  bg:        '#000000',
  panel:     '#0D1117',
  card:      '#131722',
  border:    '#2A2E39',
  textPri:   '#D1D4DC',
  textSec:   '#787B86',
  blue:      '#2962FF',
  green:     '#26A69A',
  red:       '#EF5350',
  yellow:    '#F7D060',
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmt = (v, digits = 4) =>
  v == null ? '—' : Number(v).toFixed(digits);

const pct = (v) =>
  v == null ? '—' : `${(v * 100).toFixed(2)}%`;

const tsToDate = (ms) => {
  if (!ms) return '—';
  const d = new Date(ms);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' });
};

// ── Mini Candlestick Chart (Canvas) ───────────────────────────────────────────
const MiniChart = ({ pattern }) => {
  const canvasRef = useRef(null);
  const [candles, setCandles] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!pattern) return;
    setLoading(true);
    const { symbol, timeframe, box_time_start, box_time_end } = pattern;
    fetch(`${API}/api/pattern/candles?symbol=${symbol}&timeframe=${timeframe}&time_start=${box_time_start}&time_end=${box_time_end}&pre_candles=40&post_candles=30`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.candles?.length) {
          setCandles({ ohlcv: data.candles, boxStart: data.box_start_sec, boxEnd: data.box_end_sec });
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [pattern]);

  useEffect(() => {
    if (!candles || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    const { ohlcv, boxStart, boxEnd } = candles;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = C.card;
    ctx.fillRect(0, 0, W, H);

    if (!ohlcv.length) return;

    const prices = ohlcv.flatMap(c => [c.high, c.low]);
    const minP = Math.min(...prices);
    const maxP = Math.max(...prices);
    const range = maxP - minP || 1;

    const pad = { top: 8, bottom: 8, left: 4, right: 4 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;
    const n = ohlcv.length;
    const cw = Math.max(1, plotW / n);
    const bodyW = Math.max(1, cw * 0.6);

    const yScale = (p) => pad.top + plotH * (1 - (p - minP) / range);

    // Box overlay
    const boxStartPx = ohlcv.findIndex(c => c.time >= boxStart);
    const boxEndPx   = ohlcv.findLastIndex(c => c.time <= boxEnd);
    if (boxStartPx >= 0 && boxEndPx >= boxStartPx) {
      const x1 = pad.left + boxStartPx * cw;
      const x2 = pad.left + (boxEndPx + 1) * cw;
      const pH = yScale(pattern.price_low);
      const pHigh = yScale(pattern.price_high);
      ctx.fillStyle = 'rgba(41, 98, 255, 0.12)';
      ctx.fillRect(x1, pHigh, x2 - x1, pH - pHigh);
      ctx.strokeStyle = 'rgba(41, 98, 255, 0.5)';
      ctx.lineWidth = 1;
      ctx.strokeRect(x1, pHigh, x2 - x1, pH - pHigh);
    }

    // Candles
    ohlcv.forEach((c, i) => {
      const x = pad.left + i * cw;
      const xMid = x + cw / 2;
      const isUp = c.close >= c.open;
      const color = isUp ? C.green : C.red;

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(xMid, yScale(c.high));
      ctx.lineTo(xMid, yScale(c.low));
      ctx.stroke();

      const bodyTop = yScale(Math.max(c.open, c.close));
      const bodyBot = yScale(Math.min(c.open, c.close));
      const bH = Math.max(1, bodyBot - bodyTop);
      ctx.fillStyle = color;
      ctx.fillRect(x + (cw - bodyW) / 2, bodyTop, bodyW, bH);
    });

    // Direction arrow after box
    if (boxEndPx >= 0 && boxEndPx < n - 1) {
      const arrowX = pad.left + (boxEndPx + 1.5) * cw;
      const midY = H / 2;
      const dir = pattern.breakout_direction;
      ctx.strokeStyle = dir === 'UP' ? C.green : dir === 'DOWN' ? C.red : C.yellow;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      if (dir === 'UP') {
        ctx.moveTo(arrowX, midY + 6);
        ctx.lineTo(arrowX, midY - 6);
        ctx.moveTo(arrowX - 4, midY - 2);
        ctx.lineTo(arrowX, midY - 6);
        ctx.lineTo(arrowX + 4, midY - 2);
      } else if (dir === 'DOWN') {
        ctx.moveTo(arrowX, midY - 6);
        ctx.lineTo(arrowX, midY + 6);
        ctx.moveTo(arrowX - 4, midY + 2);
        ctx.lineTo(arrowX, midY + 6);
        ctx.lineTo(arrowX + 4, midY + 2);
      }
      ctx.stroke();
    }
  }, [candles, pattern]);

  if (loading) {
    return (
      <div style={{ width: 160, height: 64, background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 12, height: 12, border: `2px solid ${C.blue}`,
          borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
      </div>
    );
  }

  if (!candles) {
    return (
      <div style={{ width: 160, height: 64, background: C.card, border: `1px solid ${C.border}`,
        borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: C.textSec, fontSize: 10 }}>
        No data
      </div>
    );
  }

  return <canvas ref={canvasRef} width={160} height={64}
    style={{ display: 'block', borderRadius: 4, border: `1px solid ${C.border}` }} />;
};

// ── Direction Badge ───────────────────────────────────────────────────────────
const DirBadge = ({ dir }) => {
  const map = {
    UP:   { color: C.green,  icon: '▲', label: 'UP' },
    DOWN: { color: C.red,    icon: '▼', label: 'DOWN' },
    NONE: { color: C.yellow, icon: '—', label: 'NONE' },
  };
  const d = map[dir] || { color: C.textSec, icon: '?', label: dir || '—' };
  return (
    <span style={{ color: d.color, fontSize: 11, fontWeight: 700,
      background: `${d.color}18`, padding: '2px 6px', borderRadius: 4,
      border: `1px solid ${d.color}40`, whiteSpace: 'nowrap' }}>
      {d.icon} {d.label}
    </span>
  );
};

// ── Win/Loss Badge ────────────────────────────────────────────────────────────
const OutcomeBadge = ({ win, loss, value }) => {
  const color = win ? C.green : loss ? C.red : C.textSec;
  return (
    <span style={{ color, fontSize: 11, fontWeight: 600 }}>
      {pct(value)}
    </span>
  );
};

// ── Stat Card ────────────────────────────────────────────────────────────────
const StatCard = ({ label, value, sub, color }) => (
  <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
    padding: '12px 16px', minWidth: 120, flex: 1 }}>
    <div style={{ fontSize: 11, color: C.textSec, marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 700, color: color || C.textPri, lineHeight: 1 }}>{value}</div>
    {sub && <div style={{ fontSize: 10, color: C.textSec, marginTop: 3 }}>{sub}</div>}
  </div>
);

// ── Filter Bar ───────────────────────────────────────────────────────────────
const SYMBOLS = ['', 'EURUSD', 'XAUUSD'];
const TFS     = ['', '1m', '5m', '15m', '1h', '4h', '1d', '1w'];
const DIRS    = ['', 'UP', 'DOWN', 'NONE'];

const FilterBar = ({ filters, onChange }) => (
  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
    <Filter size={14} color={C.textSec} />

    {[
      { key: 'symbol',    label: 'Symbol',    options: SYMBOLS },
      { key: 'timeframe', label: 'TF',        options: TFS },
      { key: 'direction', label: 'Direction', options: DIRS },
    ].map(({ key, label, options }) => (
      <select
        key={key}
        value={filters[key]}
        onChange={e => onChange({ ...filters, [key]: e.target.value })}
        style={{
          background: C.card, color: C.textPri, border: `1px solid ${C.border}`,
          borderRadius: 6, padding: '4px 8px', fontSize: 12, cursor: 'pointer', outline: 'none'
        }}
      >
        <option value="">{label}: All</option>
        {options.filter(Boolean).map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    ))}

    <div style={{ display: 'flex', alignItems: 'center', gap: 4,
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: '2px 8px' }}>
      <span style={{ fontSize: 11, color: C.textSec }}>Min Quality</span>
      <input
        type="range" min={0} max={1} step={0.05}
        value={filters.min_quality}
        onChange={e => onChange({ ...filters, min_quality: parseFloat(e.target.value) })}
        style={{ width: 80, accentColor: C.blue }}
      />
      <span style={{ fontSize: 11, color: C.textPri, width: 28 }}>
        {(filters.min_quality * 100).toFixed(0)}%
      </span>
    </div>
  </div>
);

// ── Pattern Row ───────────────────────────────────────────────────────────────
const PatternRow = ({ p, onNavigate }) => (
  <tr style={{
    borderBottom: `1px solid ${C.border}`,
    transition: 'background 0.15s',
  }}
    onMouseEnter={e => e.currentTarget.style.background = '#1A1E2A'}
    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
  >
    <td style={{ padding: '8px 10px' }}>
      <MiniChart pattern={p} />
    </td>
    <td style={{ padding: '8px 10px' }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: C.blue }}>{p.symbol}</div>
      <div style={{ fontSize: 10, color: C.textSec, marginTop: 2 }}>
        {p.timeframe} · {tsToDate(p.box_time_end)}
      </div>
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'center' }}>
      <DirBadge dir={p.breakout_direction} />
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'right', fontFamily: 'monospace', fontSize: 11, color: C.textPri }}>
      {fmt(p.price_high, 5)}<br />
      <span style={{ color: C.textSec }}>—</span><br />
      {fmt(p.price_low, 5)}
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'right' }}>
      <OutcomeBadge win={p.win} loss={p.loss} value={p.future_return_20} />
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'right' }}>
      <span style={{ fontSize: 11, color: C.green }}>{pct(p.mfe)}</span><br />
      <span style={{ fontSize: 11, color: C.red }}>{pct(p.mae)}</span>
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'center' }}>
      <span style={{ fontSize: 11, color: p.quality_score >= 0.7 ? C.green : p.quality_score >= 0.4 ? C.yellow : C.red }}>
        {(p.quality_score * 100).toFixed(0)}%
      </span>
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'center' }}>
      <span style={{ fontSize: 10, color: C.textSec,
        background: `${C.border}80`, padding: '2px 6px', borderRadius: 4 }}>
        {p.box_width_candles}c
      </span>
    </td>
    <td style={{ padding: '8px 10px', textAlign: 'center' }}>
      <button
        id={`goto-${p.pattern_id?.slice(0, 8)}`}
        onClick={() => onNavigate(p)}
        style={{ background: `${C.blue}20`, color: C.blue, border: `1px solid ${C.blue}40`,
          borderRadius: 6, padding: '3px 8px', fontSize: 10, cursor: 'pointer',
          fontWeight: 600, transition: 'all 0.15s' }}
        onMouseEnter={e => { e.currentTarget.style.background = `${C.blue}40`; }}
        onMouseLeave={e => { e.currentTarget.style.background = `${C.blue}20`; }}
      >
        Chart →
      </button>
    </td>
  </tr>
);

// ── Main Page ─────────────────────────────────────────────────────────────────
const PatternExplorerPage = () => {
  const navigate = useNavigate();
  const [patterns, setPatterns] = useState([]);
  const [total, setTotal]       = useState(0);
  const [loading, setLoading]   = useState(false);
  const [stats, setStats]       = useState(null);
  const [page, setPage]         = useState(0);
  const PAGE_SIZE = 50;

  const [filters, setFilters] = useState({
    symbol: '', timeframe: '', direction: '', min_quality: 0
  });

  const fetchStats = useCallback(() => {
    fetch(`${API}/api/pattern/stats`)
      .then(r => r.ok ? r.json() : null)
      .then(d => d && setStats(d))
      .catch(() => {});
  }, []);

  const fetchPatterns = useCallback(() => {
    setLoading(true);
    const q = new URLSearchParams({ limit: PAGE_SIZE, offset: page * PAGE_SIZE });
    if (filters.symbol)       q.set('symbol',    filters.symbol);
    if (filters.timeframe)    q.set('timeframe', filters.timeframe);
    if (filters.direction)    q.set('direction', filters.direction);
    if (filters.min_quality > 0) q.set('min_quality', filters.min_quality);

    fetch(`${API}/api/patterns?${q}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          setPatterns(data.patterns || []);
          setTotal(data.total || 0);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [filters, page]);

  useEffect(() => { fetchStats(); }, [fetchStats]);
  useEffect(() => { fetchPatterns(); }, [fetchPatterns]);

  const handleNavigate = (p) => {
    const sym = p.symbol.split(':').pop();
    navigate(`/chart/${sym}`);
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent('ml-goto-box', {
        detail: {
          box_id: p.box_id,
          symbol: p.symbol,
          timeframe: p.timeframe,
          timeStart: p.box_time_start,
          timeEnd:   p.box_time_end,
          priceHigh: p.price_high,
          priceLow:  p.price_low,
        }
      }));
    }, 800);
  };

  const winCount  = patterns.filter(p => p.win).length;
  const lossCount = patterns.filter(p => p.loss).length;
  const winRate   = patterns.length ? winCount / patterns.length : null;

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.textPri,
      fontFamily: "'Inter', -apple-system, sans-serif" }}>

      {/* CSS for animations */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0D1117; }
        ::-webkit-scrollbar-thumb { background: #2A2E39; border-radius: 3px; }
        select option { background: #131722; }
      `}</style>

      {/* Top Bar */}
      <div style={{ background: C.panel, borderBottom: `1px solid ${C.border}`,
        padding: '0 20px', height: 52, display: 'flex', alignItems: 'center', gap: 12,
        position: 'sticky', top: 0, zIndex: 40 }}>
        <button
          id="pattern-back-btn"
          onClick={() => navigate('/chart')}
          style={{ background: 'none', border: 'none', cursor: 'pointer',
            color: C.textSec, display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <ArrowLeft size={16} />
          <span style={{ fontSize: 12 }}>Chart</span>
        </button>
        <div style={{ width: 1, height: 20, background: C.border }} />
        <Brain size={16} color={C.blue} />
        <span style={{ fontWeight: 700, fontSize: 15 }}>Pattern Explorer</span>
        {stats && (
          <span style={{ fontSize: 11, color: C.textSec, marginLeft: 4 }}>
            {stats.total} patterns · {stats.with_outcomes} with outcomes
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button
          id="pattern-refresh-btn"
          onClick={() => { fetchPatterns(); fetchStats(); }}
          style={{ background: 'none', border: `1px solid ${C.border}`, cursor: 'pointer',
            color: C.textSec, borderRadius: 6, padding: '4px 10px',
            display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}
        >
          <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          Refresh
        </button>
      </div>

      <div style={{ padding: '20px', animation: 'fadeIn 0.3s ease' }}>

        {/* Stats Cards */}
        {stats && (
          <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <StatCard label="Total Patterns"    value={stats.total}           color={C.blue} />
            <StatCard label="With Outcomes"     value={stats.with_outcomes}   color={C.textPri} />
            <StatCard label="Avg Quality"       value={`${(stats.avg_quality_score * 100).toFixed(0)}%`} color={C.yellow} />
            {stats.breakout_distribution && Object.entries(stats.breakout_distribution).map(([dir, n]) => (
              <StatCard key={dir}
                label={`Breakout ${dir || 'NULL'}`}
                value={n}
                color={dir === 'UP' ? C.green : dir === 'DOWN' ? C.red : C.yellow}
              />
            ))}
            <StatCard label="FAISS Index"       value={stats.faiss_ready ? `✓ ${stats.faiss_index_size}` : '✗ Not Ready'}
              color={stats.faiss_ready ? C.green : C.red} />
          </div>
        )}

        {/* Filter Bar */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8,
          padding: '12px 16px', marginBottom: 16, display: 'flex',
          alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <FilterBar filters={filters} onChange={(f) => { setFilters(f); setPage(0); }} />
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: C.textSec }}>
            {total} results
          </span>
        </div>

        {/* Page Win Rate Banner */}
        {patterns.length > 0 && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
            <div style={{ background: `${C.green}15`, border: `1px solid ${C.green}30`,
              borderRadius: 6, padding: '6px 12px', fontSize: 12,
              display: 'flex', alignItems: 'center', gap: 6 }}>
              <TrendingUp size={13} color={C.green} />
              <span style={{ color: C.green, fontWeight: 600 }}>
                {winCount} Wins
              </span>
            </div>
            <div style={{ background: `${C.red}15`, border: `1px solid ${C.red}30`,
              borderRadius: 6, padding: '6px 12px', fontSize: 12,
              display: 'flex', alignItems: 'center', gap: 6 }}>
              <TrendingDown size={13} color={C.red} />
              <span style={{ color: C.red, fontWeight: 600 }}>
                {lossCount} Losses
              </span>
            </div>
            {winRate != null && (
              <div style={{ background: `${C.blue}15`, border: `1px solid ${C.blue}30`,
                borderRadius: 6, padding: '6px 12px', fontSize: 12 }}>
                <span style={{ color: C.blue, fontWeight: 600 }}>
                  Win Rate: {(winRate * 100).toFixed(1)}%
                </span>
                <span style={{ color: C.textSec, marginLeft: 4 }}>
                  (this page, 20-candle horizon)
                </span>
              </div>
            )}
          </div>
        )}

        {/* Table */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`,
          borderRadius: 8, overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${C.border}` }}>
                {['Chart', 'Symbol / TF', 'Breakout', 'Price Range', 'Return (20c)', 'MFE / MAE', 'Quality', 'Width', 'Action']
                  .map(h => (
                    <th key={h} style={{ padding: '10px 10px', textAlign: h === 'Price Range' || h === 'Return (20c)' || h === 'MFE / MAE' ? 'right' : 'left',
                      color: C.textSec, fontWeight: 600, fontSize: 11,
                      background: `${C.panel}CC`, position: 'sticky', top: 0, zIndex: 1 }}>
                      {h}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {loading && patterns.length === 0 ? (
                <tr><td colSpan={9} style={{ padding: 40, textAlign: 'center', color: C.textSec }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                    <div style={{ width: 16, height: 16, border: `2px solid ${C.blue}`,
                      borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                    Loading patterns…
                  </div>
                </td></tr>
              ) : patterns.length === 0 ? (
                <tr><td colSpan={9} style={{ padding: 60, textAlign: 'center', color: C.textSec }}>
                  <Database size={32} style={{ marginBottom: 8, opacity: 0.4 }} />
                  <div>No patterns found. Run the pattern harvester first.</div>
                  <code style={{ fontSize: 11, color: C.textSec, marginTop: 8, display: 'block' }}>
                    python pattern_harvester.py
                  </code>
                </td></tr>
              ) : patterns.map(p => (
                <PatternRow key={p.pattern_id} p={p} onNavigate={handleNavigate} />
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
            gap: 8, marginTop: 16 }}>
            <button
              id="pattern-prev-page"
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
              style={{ background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 6, padding: '6px 12px', cursor: page === 0 ? 'not-allowed' : 'pointer',
                color: page === 0 ? C.textSec : C.textPri, display: 'flex', alignItems: 'center', gap: 4 }}>
              <ChevronLeft size={14} /> Prev
            </button>
            <span style={{ fontSize: 12, color: C.textSec }}>
              Page {page + 1} of {totalPages} · {total} total
            </span>
            <button
              id="pattern-next-page"
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
              style={{ background: C.card, border: `1px solid ${C.border}`,
                borderRadius: 6, padding: '6px 12px', cursor: page >= totalPages - 1 ? 'not-allowed' : 'pointer',
                color: page >= totalPages - 1 ? C.textSec : C.textPri, display: 'flex', alignItems: 'center', gap: 4 }}>
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}

      </div>
    </div>
  );
};

export default PatternExplorerPage;
