import React from 'react';
import { useNavigate } from 'react-router-dom';
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch';
import { useCanvasStore } from '../../hooks/useCanvasStore';
import DecisionCluster from './DecisionCluster';

export default function InfiniteCanvasPage() {
  const navigate = useNavigate();
  const clusters = useCanvasStore(state => state.clusters);

  return (
    <div style={s.root}>
      {/* ── Top bar (Fixed overlay) ── */}
      <div style={s.topBar}>
        <div style={s.topLeft}>
          <button style={s.backBtn} onClick={() => navigate(-1)}>← Back</button>
          <div style={s.sep} />
          <span style={s.logo}>◈</span>
          <span style={s.title}>Decision Canvas <span style={{ color: '#787B86', fontWeight: 400 }}>(Infinite Surface)</span></span>
        </div>
        <div style={s.topRight}>
          <span style={s.hint}>SPACE + DRAG to pan · WHEEL to zoom</span>
        </div>
      </div>

      {/* ── Infinite Workspace ── */}
      <div style={s.workspace}>
        <TransformWrapper
          initialScale={0.2}
          centerOnInit={true}
          minScale={0.05}
          maxScale={2}
          centerZoomedOut={false}
          wheel={{ step: 0.0005, smoothStep: 0.0002 }}
          panning={{ velocityMultiplier: 0.5, excluded: ['tv-lightweight-charts'] }}
          doubleClick={{ disabled: true }}
        >
          {({ zoomIn, zoomOut, resetTransform }) => (
            <>
              {/* Floating controls in bottom center */}
              <div style={s.zoomControls}>
                <button style={s.zBtn} onClick={() => zoomIn(0.1)}>+</button>
                <button style={s.zBtn} onClick={() => zoomOut(0.1)}>-</button>
                <button style={s.zBtn} onClick={() => resetTransform()}>Reset</button>
              </div>

              {/* The massive scrollable DOM wrapper */}
              <TransformComponent
                wrapperStyle={{ width: '100vw', height: '100vh', touchAction: 'none' }}
                contentStyle={{ width: '20000px', height: '20000px' }} // practically infinite
              >

                {/* Dot grid background */}
                <div style={s.dotGrid} />

                {/* Render each cluster based on spatial rules */}
                {clusters.map(cluster => (
                  <DecisionCluster key={cluster.id} cluster={cluster} />
                ))}

              </TransformComponent>
            </>
          )}
        </TransformWrapper>
      </div>
    </div>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────
const s = {
  root: {
    display: 'flex', flexDirection: 'column',
    width: '100vw', height: '100vh',
    background: '#0a0d14',
    fontFamily: "'Inter', 'Roboto', sans-serif",
    color: '#d4daf7', overflow: 'hidden',
  },
  topBar: {
    position: 'absolute', top: 0, left: 0, right: 0,
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0 16px', height: 48,
    background: 'rgba(10, 13, 20, 0.9)',
    backdropFilter: 'blur(10px)',
    borderBottom: '1px solid rgba(255,255,255,0.06)', zIndex: 100,
  },
  topLeft: { display: 'flex', alignItems: 'center', gap: 12 },
  topRight: { display: 'flex', alignItems: 'center', gap: 12 },
  backBtn: {
    background: 'transparent', border: '1px solid rgba(255,255,255,0.15)',
    color: '#e2e8f0', borderRadius: 6, padding: '6px 14px',
    fontSize: 12, cursor: 'pointer', letterSpacing: '0.04em',
    transition: 'background 0.2s',
  },
  sep: { width: 1, height: 20, background: 'rgba(255,255,255,0.1)' },
  logo: { fontSize: 18, color: '#3B82F6', textShadow: '0 0 12px rgba(59,130,246,0.6)' },
  title: { fontSize: 14, fontWeight: 700, color: '#f8fafc', letterSpacing: '0.03em' },
  hint: { fontSize: 11, color: 'rgba(148,163,184,0.6)', letterSpacing: '0.02em', background: '#ffffff0a', padding: '4px 10px', borderRadius: 12 },

  workspace: {
    flex: 1,
    width: '100%',
    height: '100%',
    position: 'relative'
  },

  dotGrid: {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundImage: `radial-gradient(circle at 2px 2px, rgba(255,255,255,0.06) 1px, transparent 0)`,
    backgroundSize: '40px 40px',
    pointerEvents: 'none', // Don't block interactions
    zIndex: -2,
  },

  zoomControls: {
    position: 'absolute',
    bottom: 32,
    left: '50%',
    transform: 'translateX(-50%)',
    display: 'flex',
    gap: 8,
    zIndex: 100,
    background: 'rgba(16, 20, 31, 0.8)',
    padding: 6,
    borderRadius: 8,
    border: '1px solid rgba(255,255,255,0.08)',
    backdropFilter: 'blur(10px)',
  },
  zBtn: {
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.1)',
    color: '#fff',
    padding: '6px 14px',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 'bold',
  }
};
