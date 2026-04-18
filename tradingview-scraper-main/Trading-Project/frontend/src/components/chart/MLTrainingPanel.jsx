import React, { useState, useEffect, useRef, useCallback } from 'react';

const STAGES = [
  { id: 'init',     label: 'Init',        icon: '⚙' },
  { id: 'load',     label: 'Load OHLC',   icon: '📂' },
  { id: 'detect',   label: 'Detect',      icon: '🔍' },
  { id: 'features', label: 'Features',    icon: '🧮' },
  { id: 'labels',   label: 'Labels',      icon: '🏷' },
  { id: 'train',    label: 'XGBoost',     icon: '🤖' },
  { id: 'eval',     label: 'Evaluate',    icon: '📊' },
  { id: 'pattern',  label: 'Pattern',     icon: '🎯' },
  { id: 'save',     label: 'Save',        icon: '💾' },
];

const STATE_COLORS = {
  idle:     '#787B86',
  training: '#FFB86C',
  trained:  '#26A69A',
  error:    '#EF5350',
};

function fmt(s) {
  if (!s && s !== 0) return '—';
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export default function MLTrainingPanel({ onClose, onTrain, labelCount = 0 }) {
  const [progress, setProgress] = useState(null);
  const [detectionStats, setDetectionStats] = useState(null);
  const [datasetStats, setDatasetStats] = useState(null);
  const [error,    setError]    = useState(null);
  const logEndRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [pos, setPos] = useState({ x: 80, y: 60 });
  const dragging = useRef(null);
  const panelRef = useRef(null);

  // Drag-to-move
  const onHeaderMouseDown = (e) => {
    if (e.button !== 0) return;
    dragging.current = { startX: e.clientX - pos.x, startY: e.clientY - pos.y };
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragUp);
  };
  const onDragMove = useCallback((e) => {
    if (!dragging.current) return;
    setPos({ x: e.clientX - dragging.current.startX, y: e.clientY - dragging.current.startY });
  }, []);
  const onDragUp = useCallback(() => {
    dragging.current = null;
    document.removeEventListener('mousemove', onDragMove);
    document.removeEventListener('mouseup', onDragUp);
  }, [onDragMove]);

  // Poll /api/ml/train-progress every 1.5s when training, 5s otherwise
  const fetchProgress = useCallback(async () => {
    try {
      // 1. ML Scorer progress
      const r = await fetch('http://localhost:8000/api/ml/train-progress');
      // 2. Detection Model stats
      const r2 = await fetch('http://localhost:8000/api/detection/stats');
      const d2 = await r2.json();
      if (d2.status === 'ok') setDetectionStats(d2);

      // 3. Unified Dataset stats (TASK 2)
      const r3 = await fetch('http://localhost:8000/api/ml/stats');
      const d3 = await r3.json();
      if (!d3.status || d3.status !== 'error') setDatasetStats(d3);

    } catch (e) {
      setError('Cannot reach backend');
    }
  }, []);

  useEffect(() => {
    fetchProgress();
  }, [fetchProgress]);

  useEffect(() => {
    const interval = progress?.retrain_running ? 1500 : 5000;
    const iv = setInterval(fetchProgress, interval);
    return () => clearInterval(iv);
  }, [fetchProgress, progress?.retrain_running]);

  // Auto-scroll log
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [progress?.logs?.length, autoScroll]);

  const state      = progress?.state || 'idle';
  const pct        = progress?.pct   || 0;
  const stateColor = STATE_COLORS[state] || '#787B86';
  const isRunning  = progress?.retrain_running || false;
  const currentStageId = progress?.stage;
  const metrics    = progress?.metrics || {};

  // Find current stage index
  const currentStageIdx = STAGES.findIndex(s => s.id === currentStageId);

  const handleScorerTrain = async () => {
    try {
      const r = await fetch('http://localhost:8000/api/ml/retrain', { method: 'POST' });
      const d = await r.json();
      if (onTrain) onTrain(d);
      setTimeout(fetchProgress, 300);
    } catch (_) {}
  };

  const handleDetectorTrain = async () => {
    try {
      const r = await fetch('http://localhost:8000/api/detection/retrain', { method: 'POST' });
      const d = await r.json();
      if (onTrain) onTrain(d);
      setTimeout(fetchProgress, 300);
    } catch (_) {}
  };

  return (
    <div
      ref={panelRef}
      style={{
        position: 'fixed',
        left: pos.x,
        top:  pos.y,
        width: 520,
        background: '#0E1117',
        border: '1px solid #2A2E39',
        borderRadius: 10,
        boxShadow: '0 24px 60px rgba(0,0,0,0.7)',
        zIndex: 200,
        fontFamily: "'Inter', monospace",
        userSelect: 'none',
        overflow: 'hidden',
      }}
    >
      {/* ── Title bar ── */}
      <div
        onMouseDown={onHeaderMouseDown}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px',
          background: '#131722',
          borderBottom: '1px solid #2A2E39',
          cursor: 'move',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#D1D4DC', letterSpacing: '0.5px' }}>
            ML TRAINING MONITOR
          </span>
          {/* Live indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: isRunning ? '#FFB86C' : stateColor,
              boxShadow: isRunning ? '0 0 6px #FFB86C' : 'none',
              animation: isRunning ? 'pulse 1s infinite' : 'none',
            }} />
            <span style={{ fontSize: 9, color: stateColor, fontWeight: 700 }}>
              {isRunning ? 'RUNNING' : state.toUpperCase()}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {progress?.elapsed_s != null && (
            <span style={{ fontSize: 9, color: '#787B86' }}>{fmt(progress.elapsed_s)}</span>
          )}
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#787B86', fontSize: 14, lineHeight: 1, padding: '2px 4px' }}
          >✕</button>
        </div>
      </div>

      {/* ── Overall progress bar ── */}
      <div style={{ padding: '10px 12px 4px', background: '#131722' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
          <span style={{ fontSize: 9, color: '#787B86' }}>
            {progress?.stage_label || 'Waiting to start'}
          </span>
          <span style={{ fontSize: 9, fontWeight: 700, color: stateColor, fontFamily: 'monospace' }}>
            {pct}%
          </span>
        </div>
        <div style={{ height: 6, background: '#1E222D', borderRadius: 3, overflow: 'hidden', position: 'relative' }}>
          <div style={{
            height: '100%',
            width: `${pct}%`,
            background: state === 'error'
              ? '#EF5350'
              : state === 'trained'
              ? 'linear-gradient(90deg,#26A69A,#00BCD4)'
              : 'linear-gradient(90deg,#2962FF,#BD93F9)',
            borderRadius: 3,
            transition: 'width 0.6s ease',
            position: 'relative',
          }}>
            {isRunning && (
              <div style={{
                position: 'absolute', right: 0, top: 0, bottom: 0, width: 20,
                background: 'linear-gradient(90deg,transparent,rgba(255,255,255,0.3))',
                animation: 'shimmer 1.5s infinite',
              }} />
            )}
          </div>
        </div>
      </div>

      {/* ── Stage chips row ── */}
      <div style={{
        display: 'flex', gap: 3, padding: '6px 12px 8px',
        background: '#131722',
        borderBottom: '1px solid #1E222D',
        overflowX: 'auto',
        flexWrap: 'nowrap',
      }}>
        {STAGES.map((st, i) => {
          const isDone    = currentStageIdx > i || state === 'trained';
          const isActive  = st.id === currentStageId && isRunning;
          const isError   = state === 'error' && st.id === currentStageId;
          const bg        = isError ? '#EF535020' : isDone ? '#26A69A18' : isActive ? '#2962FF20' : 'transparent';
          const border    = isError ? '#EF535060' : isDone ? '#26A69A50' : isActive ? '#2962FF60' : '#2A2E39';
          const textColor = isError ? '#EF5350' : isDone ? '#26A69A' : isActive ? '#90CAF9' : '#4A4E59';
          return (
            <div key={st.id} style={{
              display: 'flex', alignItems: 'center', gap: 3,
              padding: '2px 7px', borderRadius: 4, whiteSpace: 'nowrap',
              background: bg, border: `1px solid ${border}`,
              fontSize: 8, color: textColor, fontWeight: isActive ? 700 : 500,
              flexShrink: 0,
            }}>
              <span>{isDone ? '✓' : isError ? '✗' : st.icon}</span>
              <span>{st.label}</span>
            </div>
          );
        })}
      </div>

      {/* ── Log output ── */}
      <div
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
          setAutoScroll(atBottom);
        }}
        style={{
          height: 200,
          overflowY: 'auto',
          background: '#080B10',
          fontFamily: "'Fira Code','Courier New',monospace",
          fontSize: 10,
          padding: '6px 10px',
          color: '#8B9AAB',
          lineHeight: 1.6,
        }}
      >
        {(!progress?.logs || progress.logs.length === 0) && (
          <div style={{ color: '#363A45', textAlign: 'center', paddingTop: 60 }}>
            {state === 'idle' ? 'No training session yet' : 'Waiting for logs…'}
          </div>
        )}
        {(progress?.logs || []).map((entry, i) => {
          const isErr  = entry.msg?.includes('✗') || entry.msg?.includes('Error') || entry.msg?.includes('error');
          const isOk   = entry.msg?.includes('✓') || entry.msg?.includes('complete') || entry.msg?.includes('saved');
          const isHead = entry.msg?.includes('▶') || entry.msg?.includes('→');
          const color  = isErr ? '#EF7070' : isOk ? '#26A69A' : isHead ? '#90CAF9' : '#8B9AAB';
          return (
            <div key={i} style={{ display: 'flex', gap: 8, color }}>
              <span style={{ opacity: 0.4, flexShrink: 0, fontSize: 9 }}>{entry.ts}</span>
              <span style={{ wordBreak: 'break-all' }}>{entry.msg}</span>
            </div>
          );
        })}
        <div ref={logEndRef} />
      </div>

      {/* ── Metrics panel (visible when trained) ── */}
      {state === 'trained' && Object.keys(metrics).length > 0 && (
        <div style={{
          background: '#0A0D14',
          borderTop: '1px solid #1E222D',
          padding: '8px 12px',
          display: 'grid',
          gridTemplateColumns: 'repeat(4,1fr)',
          gap: 6,
        }}>
          {[
            ['MAE',        metrics.mae,               null],
            ['Pearson r',  metrics.pearson_r,          null],
            ['Threshold',  metrics.optimal_threshold,  null],
            ['Train rows', metrics.train_rows,          0],
            ['Test rows',  metrics.test_rows,           0],
            ['Human lbl',  metrics.human_label_count,  0],
            ['Pattern',    metrics.has_pattern_model ? 'yes' : 'no', null],
            ['Version',    metrics.version,            null],
          ].filter(([,v]) => v !== undefined && v !== null).map(([label, value]) => (
            <div key={label} style={{
              background: '#131722', borderRadius: 4, padding: '4px 6px',
              border: '1px solid #2A2E39',
            }}>
              <div style={{ fontSize: 7, color: '#4A4E59', marginBottom: 1 }}>{label}</div>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#90CAF9', fontFamily: 'monospace' }}>
                {typeof value === 'number' ? value.toString() : value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Error banner ── */}
      {state === 'error' && progress?.error && (
        <div style={{
          background: '#EF535015', borderTop: '1px solid #EF535040',
          padding: '6px 12px', fontSize: 10, color: '#EF7070',
          wordBreak: 'break-all',
        }}>
          ✗ {progress.error}
        </div>
      )}

      {/* ── Footer controls ── */}
      <div style={{
        padding: '10px 12px',
        background: '#131722',
        borderTop: '1px solid #2A2E39',
      }}>
        {/* Row 1: Refresh & Scroll */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <button
            onClick={fetchProgress}
            style={{
              fontSize: 9, padding: '4px 10px', borderRadius: 4,
              background: '#1E222D', border: '1px solid #2A2E39',
              color: '#787B86', cursor: 'pointer',
            }}
          >⟳ Refresh Stats</button>

          {!autoScroll && (
            <button
              onClick={() => { setAutoScroll(true); logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }}
              style={{ fontSize: 8, background: '#2A2E39', border: 'none', borderRadius: 3, padding: '2px 6px', color: '#787B86', cursor: 'pointer' }}
            >↓ auto-scroll</button>
          )}
        </div>

        {/* Training Buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 15 }}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: '#D1D4DC' }}>Scorer Training</span>
              <span style={{ fontSize: 8, color: '#4A4E59' }}>
                Dataset: {datasetStats?.usable_samples ?? '—'} usable samples
              </span>
              <div style={{ fontSize: 7, color: '#4A4E59', marginTop: 1 }}>
                ({datasetStats?.positives ?? 0} pos / {datasetStats?.negatives ?? 0} neg)
              </div>
              {datasetStats?.usable_samples > 0 && datasetStats?.usable_samples < 20 && (
                <span style={{ fontSize: 7, color: '#FFB86C', marginTop: 2 }}>⚠️ Low data — model may be weak</span>
              )}
            </div>
            <button
              onClick={handleScorerTrain}
              disabled={isRunning || !datasetStats || datasetStats.usable_samples === 0}
              style={{
                fontSize: 9, fontWeight: 700, padding: '5px 12px', borderRadius: 4,
                border: 'none', cursor: isRunning || !datasetStats || datasetStats.usable_samples === 0 ? 'not-allowed' : 'pointer',
                background: isRunning ? '#FFB86C20' : (!datasetStats || datasetStats.usable_samples === 0) ? '#2A2E39' : 'linear-gradient(135deg,#2962FF,#1565C0)',
                color: isRunning ? '#FFB86C' : (!datasetStats || datasetStats.usable_samples === 0) ? '#4A4E59' : '#fff',
                minWidth: 100
              }}
            >
              {isRunning ? 'Running…' : 'Train Scorer'}
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 15 }}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: '#D1D4DC' }}>Detector Training</span>
              <span style={{ fontSize: 8, color: '#4A4E59' }}>{((detectionStats?.right || 0) + (detectionStats?.wrong || 0))} boxes (R/W)</span>
            </div>
            <button
              onClick={handleDetectorTrain}
              disabled={isRunning || ((detectionStats?.right || 0) + (detectionStats?.wrong || 0)) < 10}
              style={{
                fontSize: 9, fontWeight: 700, padding: '5px 12px', borderRadius: 4,
                border: 'none', cursor: isRunning || ((detectionStats?.right || 0) + (detectionStats?.wrong || 0)) < 10 ? 'not-allowed' : 'pointer',
                background: isRunning ? '#FFB86C20' : ((detectionStats?.right || 0) + (detectionStats?.wrong || 0)) < 10 ? '#2A2E39' : 'linear-gradient(135deg,#BD93F9,#7b61ff)',
                color: isRunning ? '#FFB86C' : ((detectionStats?.right || 0) + (detectionStats?.wrong || 0)) < 10 ? '#4A4E59' : '#fff',
                minWidth: 100
              }}
            >
              {isRunning ? 'Running…' : ((detectionStats?.right || 0) + (detectionStats?.wrong || 0)) < 10 ? `Need 10` : 'Train Detector'}
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        @keyframes shimmer { 0%{opacity:0} 50%{opacity:1} 100%{opacity:0} }
      `}</style>
    </div>
  );
}
