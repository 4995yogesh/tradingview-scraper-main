import React, { useState, useEffect, useCallback } from 'react';

const BATCH_SIZE = 100;

const LABEL_COLORS = {
  GOOD:    { bg: '#26A69A22', border: '#26A69A60', text: '#26A69A', dot: '#26A69A' },
  BAD:     { bg: '#EF535022', border: '#EF535060', text: '#EF5350', dot: '#EF5350' },
  NEUTRAL: { bg: '#FFB86C22', border: '#FFB86C60', text: '#FFB86C', dot: '#FFB86C' },
};

const TF_ORDER = { '1m': 1, '5m': 2, '15m': 3, '30m': 4, '1h': 5, '4h': 6, '1d': 7, '1w': 8, '1M': 9 };

function formatTime(ms) {
  if (!ms) return '—';
  try {
    const d = new Date(ms < 1e12 ? ms * 1000 : ms);
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' });
  } catch { return '—'; }
}

export default function LabeledListPanel({ onClose, onRetrain, trainStatus }) {
  const [items, setItems]               = useState([]);
  const [total, setTotal]               = useState(0);
  const [loading, setLoading]           = useState(true);
  const [filter, setFilter]             = useState('ALL');      // ALL | GOOD | BAD | NEUTRAL
  const [consumedFilter, setConsumedFilter] = useState('ALL'); // ALL | FRESH | CONSUMED
  const [tfFilter, setTfFilter]         = useState('ALL');
  const [retraining, setRetraining]     = useState(false);

  const fetchList = useCallback(async () => {
    try {
      const r = await fetch('http://localhost:8000/api/ml/labeled-list');
      const d = await r.json();
      if (d.status === 'ok') {
        setItems(d.items || []);
        setTotal(d.total || 0);
      }
    } catch (_) {}
    setLoading(false);
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);
  useEffect(() => {
    const iv = setInterval(fetchList, 10000);
    return () => clearInterval(iv);
  }, [fetchList]);

  // Sync retrain state from parent trainStatus prop
  useEffect(() => {
    if (trainStatus === 'training') setRetraining(true);
    else setRetraining(false);
  }, [trainStatus]);

  const handleRetrain = async () => {
    setRetraining(true);
    try {
      const r = await fetch('http://localhost:8000/api/ml/retrain', { method: 'POST' });
      const d = await r.json();
      if (onRetrain) onRetrain(d);
    } catch (_) {}
  };

  // Derived counts
  const allTfs       = [...new Set(items.map(i => i.timeframe))].sort((a, b) => (TF_ORDER[a] || 99) - (TF_ORDER[b] || 99));
  const goodCount    = items.filter(i => i.user_label === 'GOOD').length;
  const badCount     = items.filter(i => i.user_label === 'BAD').length;
  const neutralCount = items.filter(i => i.user_label === 'NEUTRAL').length;
  const consumedCount = items.filter(i => i.is_consumed).length;
  const freshCount    = items.filter(i => !i.is_consumed).length;

  const filtered = items.filter(i =>
    (filter === 'ALL' || i.user_label === filter) &&
    (tfFilter === 'ALL' || i.timeframe === tfFilter) &&
    (consumedFilter === 'ALL' || (consumedFilter === 'FRESH' ? !i.is_consumed : !!i.is_consumed))
  );

  // Batch progress — only count fresh (unconsumed) labels
  const batchProg = freshCount % BATCH_SIZE;
  const batchNum  = Math.floor(freshCount / BATCH_SIZE) + 1;
  const batchPct  = Math.round((batchProg / BATCH_SIZE) * 100);
  const nextTrain = BATCH_SIZE - batchProg;

  return (
    <div style={{
      position: 'absolute',
      top: 0, right: 0, bottom: 0,
      width: '280px',
      background: '#131722',
      borderLeft: '1px solid #2A2E39',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 40,
      fontFamily: "'Inter', sans-serif",
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 12px 8px',
        borderBottom: '1px solid #2A2E39',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#D1D4DC', letterSpacing: '0.5px' }}>
            LABELED BOXES
          </span>
          <span style={{ fontSize: 10, color: '#787B86', marginLeft: 6 }}>{total} total</span>
        </div>
        <button onClick={onClose} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#787B86', fontSize: 14, lineHeight: 1, padding: '2px 4px',
        }}>✕</button>
      </div>

      {/* Batch progress + train button */}
      <div style={{
        padding: '10px 12px',
        borderBottom: '1px solid #1E222D',
        flexShrink: 0,
      }}>
        {/* Batch info row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 9, color: '#787B86' }}>
            Batch {batchNum} · {batchProg}/{BATCH_SIZE} fresh
            {nextTrain > 0 ? ` · ${nextTrain} to auto-train` : ' · ready'}
          </span>
          {/* Training status badge */}
          {trainStatus === 'training' && (
            <span style={{
              fontSize: 8, fontWeight: 700, color: '#FFB86C',
              background: '#FFB86C15', border: '1px solid #FFB86C40',
              borderRadius: 4, padding: '1px 5px', letterSpacing: '0.5px',
              animation: 'pulse 1.5s infinite',
            }}>TRAINING…</span>
          )}
          {trainStatus === 'trained' && (
            <span style={{
              fontSize: 8, fontWeight: 700, color: '#26A69A',
              background: '#26A69A15', border: '1px solid #26A69A40',
              borderRadius: 4, padding: '1px 5px',
            }}>TRAINED ✓</span>
          )}
          {trainStatus === 'error' && (
            <span style={{
              fontSize: 8, fontWeight: 700, color: '#EF5350',
              background: '#EF535015', border: '1px solid #EF535040',
              borderRadius: 4, padding: '1px 5px',
            }}>ERROR</span>
          )}
        </div>
        {/* Progress bar */}
        <div style={{ height: 3, background: '#2A2E39', borderRadius: 2, overflow: 'hidden', marginBottom: 8 }}>
          <div style={{
            height: '100%',
            width: `${batchPct}%`,
            background: batchPct === 100 ? '#26A69A' : batchPct > 50 ? '#2962FF' : '#787B86',
            borderRadius: 2,
            transition: 'width 0.4s ease',
          }} />
        </div>
        {/* Label summary pills */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
          {[['GOOD', goodCount, '#26A69A'], ['BAD', badCount, '#EF5350'], ['NEU', neutralCount, '#FFB86C']].map(([lbl, cnt, color]) => (
            <div key={lbl} style={{
              flex: 1, textAlign: 'center', padding: '2px 0',
              background: `${color}14`, border: `1px solid ${color}40`, borderRadius: 4,
            }}>
              <div style={{ fontSize: 9, fontWeight: 700, color, fontFamily: 'monospace' }}>{cnt}</div>
              <div style={{ fontSize: 7, color: '#787B86' }}>{lbl}</div>
            </div>
          ))}
          {/* Consumed / Fresh pills */}
          <div style={{
            flex: 1, textAlign: 'center', padding: '2px 0',
            background: '#26A69A10', border: '1px solid #26A69A30', borderRadius: 4,
          }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: '#26A69A', fontFamily: 'monospace' }}>{consumedCount}</div>
            <div style={{ fontSize: 7, color: '#787B86' }}>USED</div>
          </div>
          <div style={{
            flex: 1, textAlign: 'center', padding: '2px 0',
            background: '#2962FF10', border: '1px solid #2962FF30', borderRadius: 4,
          }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: '#2962FF', fontFamily: 'monospace' }}>{freshCount}</div>
            <div style={{ fontSize: 7, color: '#787B86' }}>NEW</div>
          </div>
        </div>
        {/* Train now button */}
        <button
          onClick={handleRetrain}
          disabled={retraining || freshCount < 10}
          style={{
            width: '100%',
            padding: '5px 0',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: '0.5px',
            borderRadius: 4,
            border: 'none',
            cursor: retraining || freshCount < 10 ? 'not-allowed' : 'pointer',
            background: retraining
              ? '#FFB86C20'
              : freshCount < 10
              ? '#2A2E39'
              : 'linear-gradient(135deg, #2962FF, #1565C0)',
            color: retraining
              ? '#FFB86C'
              : freshCount < 10
              ? '#4A4E59'
              : '#fff',
            transition: 'all 0.2s',
          }}
        >
          {retraining ? '⟳ TRAINING…' : freshCount < 10 ? `NEED ${10 - freshCount} MORE FRESH` : `▶ TRAIN NOW (${freshCount} new)`}
        </button>
      </div>

      {/* Filters */}
      <div style={{
        padding: '6px 8px',
        borderBottom: '1px solid #1E222D',
        flexShrink: 0,
      }}>
        {/* Label filter row */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 4, flexWrap: 'wrap' }}>
          {['ALL', 'GOOD', 'BAD', 'NEUTRAL'].map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              fontSize: 8, fontWeight: 600, padding: '2px 6px',
              borderRadius: 3, border: 'none', cursor: 'pointer',
              background: filter === f ? '#2962FF' : '#1E222D',
              color: filter === f ? '#fff' : '#787B86',
            }}>{f}</button>
          ))}
          {allTfs.length > 1 && (
            <select value={tfFilter} onChange={e => setTfFilter(e.target.value)} style={{
              marginLeft: 'auto', fontSize: 8, background: '#1E222D',
              color: '#787B86', border: '1px solid #363A45', borderRadius: 3, padding: '1px 4px',
            }}>
              <option value="ALL">All TF</option>
              {allTfs.map(tf => <option key={tf} value={tf}>{tf}</option>)}
            </select>
          )}
        </div>
        {/* Consumed filter row */}
        <div style={{ display: 'flex', gap: 4 }}>
          {[['ALL', 'All'], ['FRESH', '🔵 New'], ['CONSUMED', '✓ Used']].map(([val, label]) => (
            <button key={val} onClick={() => setConsumedFilter(val)} style={{
              fontSize: 8, fontWeight: 600, padding: '2px 6px',
              borderRadius: 3, border: 'none', cursor: 'pointer',
              background: consumedFilter === val ? (val === 'CONSUMED' ? '#26A69A' : val === 'FRESH' ? '#2962FF' : '#2962FF') : '#1E222D',
              color: consumedFilter === val ? '#fff' : '#787B86',
            }}>{label}</button>
          ))}
          <span style={{ marginLeft: 'auto', fontSize: 8, color: '#363A45', alignSelf: 'center' }}>
            {filtered.length} shown
          </span>
        </div>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {loading && (
          <div style={{ textAlign: 'center', color: '#787B86', fontSize: 10, padding: 20 }}>Loading…</div>
        )}
        {!loading && filtered.length === 0 && (
          <div style={{ textAlign: 'center', color: '#787B86', fontSize: 10, padding: 20 }}>
            No labeled boxes yet.<br />
            <span style={{ fontSize: 9, opacity: 0.7 }}>Click a box on chart → GOOD/BAD/NEUTRAL</span>
          </div>
        )}
        {filtered.map((item, idx) => {
          const lc = LABEL_COLORS[item.user_label] || LABEL_COLORS.NEUTRAL;
          const consumed = !!item.is_consumed;
          const absIdx = total - items.findIndex(x => x.box_id === item.box_id);
          const batch  = Math.ceil(absIdx / BATCH_SIZE);
          return (
            <div key={item.box_id} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '5px 12px',
              borderBottom: '1px solid #1E222D',
              background: consumed
                ? (idx % 2 === 0 ? '#0D1A18' : '#0A1614')
                : (idx % 2 === 0 ? 'transparent' : '#0A0D14'),
              opacity: consumed ? 0.7 : 1,
              transition: 'background 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = '#1E222D50'}
              onMouseLeave={e => e.currentTarget.style.background = consumed
                ? (idx % 2 === 0 ? '#0D1A18' : '#0A1614')
                : (idx % 2 === 0 ? 'transparent' : '#0A0D14')}
            >
              {/* Label dot */}
              <div style={{
                width: 6, height: 6, borderRadius: '50%',
                background: lc.dot, flexShrink: 0,
              }} />
              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{
                    fontSize: 8, fontWeight: 700, color: lc.text,
                    background: lc.bg, border: `1px solid ${lc.border}`,
                    borderRadius: 3, padding: '0 3px',
                  }}>{item.user_label}</span>
                  <span style={{ fontSize: 8, color: '#4A4E59', background: '#1E222D', borderRadius: 3, padding: '0 3px' }}>
                    {item.timeframe}
                  </span>
                  {item.pattern_type && (
                    <span style={{ fontSize: 7, color: '#BD93F9' }}>{item.pattern_type.replace('_', ' ')}</span>
                  )}
                  {consumed && (
                    <span style={{
                      fontSize: 7, fontWeight: 700, color: '#26A69A',
                      background: '#26A69A18', border: '1px solid #26A69A40',
                      borderRadius: 3, padding: '0 3px',
                    }}>✓ used</span>
                  )}
                </div>
                <div style={{ fontSize: 8, color: '#787B86', marginTop: 1, fontFamily: 'monospace' }}>
                  {item.price_high ? `${item.price_high.toFixed(4)} – ${item.price_low.toFixed(4)}` : item.box_id.slice(0, 10) + '…'}
                </div>
              </div>
              {/* Right side */}
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 7, color: '#4A4E59' }}>{formatTime(item.time_start)}</div>
                <div style={{ fontSize: 7, color: '#363A45' }}>B{batch}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div style={{
        padding: '6px 12px',
        borderTop: '1px solid #2A2E39',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 8, color: '#4A4E59' }}>
          All TFs · EURUSD · <span style={{ color: '#26A69A' }}>{consumedCount} trained</span> / <span style={{ color: '#2962FF' }}>{freshCount} new</span>
        </span>
        <button onClick={fetchList} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#787B86', fontSize: 10,
        }} title="Refresh">⟳</button>
      </div>
    </div>
  );
}
