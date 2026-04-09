import React, { useState, useCallback, useEffect } from 'react';
import ChartCanvas from './ChartCanvas';
import LayerController from './LayerController';
import StatusBar from './StatusBar';
import { useDataFetcher } from './useDataFetcher';
import { TF_ORDER, COLORS } from './canvasUtils';

/**
 * InfiniteCanvasPage – full-screen decision visualization engine.
 *
 * Route: /canvas
 */
export default function InfiniteCanvasPage() {
  const [activeTimeframes, setActiveTimeframes] = useState([...TF_ORDER]);
  const [showLayers, setShowLayers] = useState(true);
  const [showHelp, setShowHelp] = useState(false);

  const { scenarios, candles, consolidations, error, lastUpdated } = useDataFetcher();

  const toggleTimeframe = useCallback((tf) => {
    setActiveTimeframes(prev =>
      prev.includes(tf) ? prev.filter(t => t !== tf) : [...prev, tf]
    );
  }, []);

  // Hide help after 5s
  useEffect(() => {
    const t = setTimeout(() => setShowHelp(false), 5000);
    setShowHelp(true);
    return () => clearTimeout(t);
  }, []);

  return (
    <div style={styles.root}>
      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div style={styles.topBar}>
        <div style={styles.topLeft}>
          <div style={styles.logoMark}>
            <span style={styles.logoIcon}>◈</span>
            <span style={styles.logoText}>Decision Canvas</span>
          </div>
          <div style={styles.topSep} />
          <span style={styles.symbolBadge}>EURUSD</span>
        </div>

        <div style={styles.topRight}>
          {/* Toggle layers sidebar */}
          <button
            style={{
              ...styles.iconBtn,
              background: showLayers ? 'rgba(74,144,217,0.2)' : 'transparent',
              borderColor: showLayers ? 'rgba(74,144,217,0.4)' : 'rgba(255,255,255,0.08)',
            }}
            onClick={() => setShowLayers(v => !v)}
            title="Toggle layer panel"
          >
            ⊞
          </button>

          {/* Quick TF toggles in top bar */}
          <div style={styles.tfQuickRow}>
            {TF_ORDER.map(tf => (
              <button
                key={tf}
                onClick={() => toggleTimeframe(tf)}
                style={{
                  ...styles.tfQuickBtn,
                  color: activeTimeframes.includes(tf) ? getTypeColor(scenarios[tf]) : '#2a3050',
                  borderColor: activeTimeframes.includes(tf) ? `${getTypeColor(scenarios[tf])}44` : 'rgba(255,255,255,0.06)',
                  background: activeTimeframes.includes(tf) ? `${getTypeColor(scenarios[tf])}12` : 'transparent',
                }}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Main area ───────────────────────────────────────────────────── */}
      <div style={styles.mainArea}>
        {/* Canvas */}
        <div style={styles.canvasWrap}>
          <ChartCanvas
            candles={candles}
            scenarios={scenarios}
            consolidations={consolidations}
            activeTimeframes={activeTimeframes}
          />

          {/* Zoom hint */}
          {showHelp && (
            <div style={styles.helpBadge}>
              Scroll to zoom · Drag to pan
            </div>
          )}

          {/* Scenario legend overlay (top-right corner of canvas) */}
          <div style={styles.canvasOverlay}>
            <ScenarioSummary scenarios={scenarios} activeTimeframes={activeTimeframes} />
          </div>
        </div>

        {/* Layer panel */}
        {showLayers && (
          <div style={styles.layerPanel}>
            <LayerController
              activeTimeframes={activeTimeframes}
              onToggle={toggleTimeframe}
              scenarios={scenarios}
            />
          </div>
        )}
      </div>

      {/* ── Status bar ─────────────────────────────────────────────────── */}
      <StatusBar
        scenarios={scenarios}
        lastUpdated={lastUpdated}
        error={error}
        activeTimeframes={activeTimeframes}
      />
    </div>
  );
}

// ── Compact scenario summary in canvas top-right ───────────────────────────
function ScenarioSummary({ scenarios, activeTimeframes }) {
  const activeTfs = TF_ORDER.filter(tf => activeTimeframes.includes(tf));

  return (
    <div style={summaryStyles.wrap}>
      {activeTfs.map(tf => {
        const tfScenarios = scenarios[tf] || [];
        if (!tfScenarios.length) return null;

        return (
          <div key={tf} style={summaryStyles.row}>
            <span style={summaryStyles.tfTag}>{tf}</span>
            {tfScenarios.map((s, i) => (
              <div key={i} style={{
                ...summaryStyles.typeBadge,
                background: `${COLORS[s.type] || COLORS.none}22`,
                borderColor: `${COLORS[s.type] || COLORS.none}55`,
                color: s.confirmed ? '#ffd700' : (COLORS[s.type] || COLORS.none),
                boxShadow: s.confirmed ? `0 0 8px ${COLORS[s.type]}55` : 'none',
              }}>
                {s.type.toUpperCase()}
                {s.confirmed && ' ★'}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function getTypeColor(tfScenarios = []) {
  const types = tfScenarios.map(s => s.type);
  if (types.includes('buy')) return COLORS.buy;
  if (types.includes('sell')) return COLORS.sell;
  return COLORS.none;
}

// ── Styles ─────────────────────────────────────────────────────────────────
const styles = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    width: '100vw',
    background: '#0d0f17',
    fontFamily: "'Inter', 'Roboto', sans-serif",
    color: '#d4daf7',
    overflow: 'hidden',
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 16px',
    height: 44,
    background: 'rgba(10,12,20,0.97)',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    flexShrink: 0,
    zIndex: 10,
  },
  topLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  logoMark: {
    display: 'flex',
    alignItems: 'center',
    gap: 7,
  },
  logoIcon: {
    fontSize: 16,
    color: '#4a90d9',
    textShadow: '0 0 10px #4a90d9',
  },
  logoText: {
    fontSize: 13,
    fontWeight: 600,
    color: '#8892b8',
    letterSpacing: '0.02em',
  },
  topSep: {
    width: 1,
    height: 18,
    background: 'rgba(255,255,255,0.08)',
  },
  symbolBadge: {
    fontSize: 13,
    fontWeight: 700,
    color: '#d4daf7',
    letterSpacing: '0.04em',
  },
  topRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  iconBtn: {
    padding: '5px 9px',
    borderRadius: 6,
    border: '1px solid',
    cursor: 'pointer',
    fontSize: 14,
    color: '#8892b8',
    transition: 'all 0.15s',
    lineHeight: 1,
  },
  tfQuickRow: {
    display: 'flex',
    gap: 4,
  },
  tfQuickBtn: {
    padding: '4px 8px',
    borderRadius: 5,
    border: '1px solid',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.04em',
    transition: 'all 0.15s',
    lineHeight: 1,
  },
  mainArea: {
    display: 'flex',
    flex: 1,
    overflow: 'hidden',
    position: 'relative',
  },
  canvasWrap: {
    flex: 1,
    position: 'relative',
    overflow: 'hidden',
  },
  layerPanel: {
    padding: 12,
    flexShrink: 0,
    display: 'flex',
    alignItems: 'flex-start',
    paddingTop: 14,
    background: 'rgba(8,10,18,0.8)',
    borderLeft: '1px solid rgba(255,255,255,0.05)',
  },
  helpBadge: {
    position: 'absolute',
    bottom: 16,
    left: '50%',
    transform: 'translateX(-50%)',
    background: 'rgba(0,0,0,0.6)',
    border: '1px solid rgba(255,255,255,0.08)',
    color: '#4a5480',
    fontSize: 11,
    padding: '5px 14px',
    borderRadius: 20,
    pointerEvents: 'none',
    animation: 'fadeOut 5s forwards',
  },
  canvasOverlay: {
    position: 'absolute',
    top: 12,
    left: 12,
    pointerEvents: 'none',
  },
};

const summaryStyles = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
  },
  tfTag: {
    fontSize: 9,
    color: '#3a4160',
    fontWeight: 700,
    letterSpacing: '0.06em',
    minWidth: 24,
  },
  typeBadge: {
    fontSize: 8,
    fontWeight: 700,
    letterSpacing: '0.08em',
    padding: '2px 5px',
    borderRadius: 3,
    border: '1px solid',
    lineHeight: 1,
  },
};
