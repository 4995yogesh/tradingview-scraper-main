import React, { memo, useMemo } from 'react';
import { COLORS, TF_ORDER } from './canvasUtils';

/**
 * StatusBar – minimal HUD at the bottom showing live info, last-update, error.
 *
 * Props:
 *   scenarios     { [tf]: scenario[] }
 *   lastUpdated   number (epoch ms) | null
 *   error         string | null
 *   activeTimeframes string[]
 */
const StatusBar = memo(({ scenarios, lastUpdated, error, activeTimeframes }) => {
  const confirmedCount = useMemo(() => {
    return Object.values(scenarios)
      .flat()
      .filter(s => s.confirmed).length;
  }, [scenarios]);

  const totalCount = useMemo(() => {
    return Object.values(scenarios).flat().length;
  }, [scenarios]);

  const timeStr = useMemo(() => {
    if (!lastUpdated) return '--:--:--';
    return new Date(lastUpdated).toLocaleTimeString();
  }, [lastUpdated]);

  const activeTfs = activeTimeframes.join(' · ');

  return (
    <div style={styles.bar}>
      {/* Live pulse */}
      <div style={styles.liveGroup}>
        <div style={{ ...styles.pulseDot, background: error ? '#f5525b' : '#22d3a5' }} />
        <span style={{ ...styles.liveText, color: error ? '#f5525b' : '#22d3a5' }}>
          {error ? 'OFFLINE' : 'LIVE'}
        </span>
      </div>

      <div style={styles.sep} />

      {/* Timeframes active */}
      <span style={styles.stat}>
        <span style={styles.statLabel}>LAYERS</span>
        <span style={styles.statVal}>{activeTfs || '—'}</span>
      </span>

      <div style={styles.sep} />

      {/* Scenario count */}
      <span style={styles.stat}>
        <span style={styles.statLabel}>SCENARIOS</span>
        <span style={styles.statVal}>{totalCount}</span>
      </span>

      <div style={styles.sep} />

      {/* Confirmed count */}
      <span style={styles.stat}>
        <span style={styles.statLabel}>CONFIRMED</span>
        <span style={{ ...styles.statVal, color: confirmedCount > 0 ? '#ffd700' : '#4a5480' }}>
          {confirmedCount}
        </span>
      </span>

      <div style={{ flex: 1 }} />

      {/* Error badge */}
      {error && (
        <span style={styles.errorBadge}>{error}</span>
      )}

      {/* Last updated */}
      <span style={styles.updated}>Updated {timeStr}</span>
    </div>
  );
});

const styles = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '6px 16px',
    background: 'rgba(10,12,20,0.95)',
    backdropFilter: 'blur(8px)',
    borderTop: '1px solid rgba(255,255,255,0.06)',
    height: 34,
    flexShrink: 0,
  },
  liveGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
  },
  pulseDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    animation: 'canvasPulse 2s ease-in-out infinite',
  },
  liveText: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.1em',
  },
  sep: {
    width: 1,
    height: 14,
    background: 'rgba(255,255,255,0.08)',
  },
  stat: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  statLabel: {
    color: '#3a4160',
    fontSize: 9,
    fontWeight: 600,
    letterSpacing: '0.08em',
  },
  statVal: {
    color: '#8892b8',
    fontSize: 11,
    fontWeight: 500,
  },
  errorBadge: {
    background: 'rgba(245,82,91,0.15)',
    border: '1px solid rgba(245,82,91,0.3)',
    color: '#f5525b',
    fontSize: 10,
    padding: '2px 8px',
    borderRadius: 4,
  },
  updated: {
    color: '#2a3050',
    fontSize: 10,
  },
};

export default StatusBar;
