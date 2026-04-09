import React, { memo } from 'react';
import { TF_ORDER, COLORS } from './canvasUtils';

const TF_LABELS = {
  '4H': '4 Hour',
  '1H': '1 Hour',
  '15m': '15 Min',
  '5m': '5 Min',
  '1m': '1 Min',
};

/**
 * LayerController – sidebar panel to toggle timeframe layers on/off.
 *
 * Props:
 *   activeTimeframes  string[]
 *   onToggle          (tf: string) => void
 *   scenarios         { [tf]: scenario[] }  – for confirming count/status
 */
const LayerController = memo(({ activeTimeframes, onToggle, scenarios = {} }) => {
  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <div style={styles.headerDot} />
        <span style={styles.headerText}>Layers</span>
      </div>

      <div style={styles.layerList}>
        {TF_ORDER.map((tf) => {
          const isActive = activeTimeframes.includes(tf);
          const tfScenarios = scenarios[tf] || [];
          const hasConfirmed = tfScenarios.some(s => s.confirmed);
          const types = [...new Set(tfScenarios.map(s => s.type))];

          return (
            <button
              key={tf}
              onClick={() => onToggle(tf)}
              style={{
                ...styles.layerBtn,
                opacity: isActive ? 1 : 0.35,
                background: isActive ? 'rgba(255,255,255,0.05)' : 'transparent',
                borderColor: isActive ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.04)',
              }}
            >
              {/* Indicator strip */}
              <div style={{
                ...styles.strip,
                background: getStripGradient(types),
                opacity: isActive ? 1 : 0.4,
              }} />

              <div style={styles.tfInfo}>
                <span style={styles.tfLabel}>{tf}</span>
                <span style={styles.tfSub}>{TF_LABELS[tf]}</span>
              </div>

              {/* Scenario type dots */}
              <div style={styles.dotRow}>
                {tfScenarios.slice(0, 3).map((s, i) => (
                  <div
                    key={i}
                    style={{
                      ...styles.dot,
                      background: COLORS[s.type] || COLORS.none,
                      boxShadow: s.confirmed ? `0 0 6px ${COLORS[s.type]}` : 'none',
                    }}
                  />
                ))}
              </div>

              {/* Active indicator */}
              {isActive && <div style={styles.activeCheck}>✓</div>}
            </button>
          );
        })}
      </div>

      <div style={styles.legend}>
        <LegendRow color={COLORS.buy} label="Buy" />
        <LegendRow color={COLORS.sell} label="Sell" />
        <LegendRow color={COLORS.none} label="No Trade" dashed />
        <LegendRow color="#ffd700" label="Confirmed" glow />
      </div>
    </div>
  );
});

const LegendRow = ({ color, label, dashed, glow }) => (
  <div style={styles.legendRow}>
    <div style={{
      width: 20,
      height: 2,
      background: color,
      borderRadius: 1,
      borderTop: dashed ? `2px dashed ${color}` : 'none',
      boxShadow: glow ? `0 0 6px ${color}66` : 'none',
    }} />
    <span style={styles.legendLabel}>{label}</span>
  </div>
);

function getStripGradient(types) {
  if (types.length === 0) return '#333';
  if (types.length === 1) return COLORS[types[0]] || COLORS.none;
  const stops = types.map((t, i) => `${COLORS[t] || COLORS.none} ${(i / (types.length - 1)) * 100}%`);
  return `linear-gradient(to bottom, ${stops.join(', ')})`;
}

const styles = {
  panel: {
    background: 'rgba(13,15,23,0.92)',
    backdropFilter: 'blur(12px)',
    border: '1px solid rgba(255,255,255,0.07)',
    borderRadius: 12,
    padding: '14px 10px',
    minWidth: 160,
    userSelect: 'none',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 12,
    paddingBottom: 8,
    borderBottom: '1px solid rgba(255,255,255,0.06)',
  },
  headerDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: '#4a90d9',
    boxShadow: '0 0 8px #4a90d9',
  },
  headerText: {
    color: '#8892b8',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
  },
  layerList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
    marginBottom: 14,
  },
  layerBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '7px 8px',
    borderRadius: 8,
    border: '1px solid',
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    textAlign: 'left',
    width: '100%',
  },
  strip: {
    width: 3,
    height: 28,
    borderRadius: 2,
    flexShrink: 0,
  },
  tfInfo: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 1,
  },
  tfLabel: {
    color: '#d4daf7',
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.2,
  },
  tfSub: {
    color: '#4a5480',
    fontSize: 10,
    lineHeight: 1.2,
  },
  dotRow: {
    display: 'flex',
    gap: 3,
    alignItems: 'center',
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
  },
  activeCheck: {
    color: '#4a90d9',
    fontSize: 10,
    fontWeight: 700,
    marginLeft: 2,
  },
  legend: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    paddingTop: 8,
    borderTop: '1px solid rgba(255,255,255,0.06)',
  },
  legendRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  legendLabel: {
    color: '#5a6480',
    fontSize: 10,
    letterSpacing: '0.05em',
  },
};

export default LayerController;
