/**
 * ConsolidationSettingsModal.jsx
 * ────────────────────────────────
 * Settings modal for the Consolidation Boxes indicator.
 * Lets users toggle which timeframes are visible on the current chart.
 */
import React from 'react';
import { X, Layers } from 'lucide-react';
import { ALL_TFS } from '../../lib/swingLevels';

// Human-readable TF labels
const TF_LABELS = {
  '1m': '1 min', '5m': '5 min', '15m': '15 min', '30m': '30 min',
  '1h': '1 Hour', '4h': '4 Hour', '1d': 'Daily', '1w': 'Weekly', '1m_month': 'Monthly',
};

// Colors per TF (reuse swingLevels palette)
const TF_COLORS_MAP = {
  '1m': '#9C27B0', '5m': '#2196F3', '15m': '#00BCD4', '30m': '#009688',
  '1h': '#4CAF50', '4h': '#FF9800', '1d': '#F44336', '1w': '#E91E63', '1M': '#FF5722',
};

export const DEFAULT_CONSOLIDATION_SETTINGS = {
  showSameTF:   true,    // show boxes from the chart's own timeframe
  showHigherTF: true,    // show boxes from higher timeframes
  // Per-TF overrides — null means "use group toggle above"
  tfOverrides: {},       // e.g. { '1d': false, '4h': true }
};

const Toggle = ({ checked, onChange, label, color, sublabel }) => (
  <div
    style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '7px 0', borderBottom: '1px solid #23283880',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {color && (
        <div style={{
          width: 8, height: 8, borderRadius: '50%',
          background: color, flexShrink: 0,
        }} />
      )}
      <div>
        <div style={{ fontSize: 12, color: '#D1D4DC', fontWeight: 500 }}>{label}</div>
        {sublabel && <div style={{ fontSize: 10, color: '#787B86', marginTop: 1 }}>{sublabel}</div>}
      </div>
    </div>
    <button
      onClick={() => onChange(!checked)}
      style={{
        width: 32, height: 18, borderRadius: 9,
        background: checked ? '#2962FF' : '#363A45',
        border: 'none', cursor: 'pointer', position: 'relative',
        transition: 'background 0.2s', flexShrink: 0,
      }}
    >
      <div style={{
        position: 'absolute', top: 3, left: checked ? 16 : 3,
        width: 12, height: 12, borderRadius: '50%',
        background: '#fff', transition: 'left 0.2s',
      }} />
    </button>
  </div>
);

const ConsolidationSettingsModal = ({ settings = {}, onChange, onClose }) => {
  const s = { ...DEFAULT_CONSOLIDATION_SETTINGS, ...settings };

  const update = (key, val) => onChange({ ...s, [key]: val });

  const setTfOverride = (tf, val) => {
    const overrides = { ...s.tfOverrides, [tf]: val };
    onChange({ ...s, tfOverrides: overrides });
  };

  const clearTfOverride = (tf) => {
    const overrides = { ...s.tfOverrides };
    delete overrides[tf];
    onChange({ ...s, tfOverrides: overrides });
  };

  // The TFs backend produces
  const backendTFs = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'];

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        paddingTop: 70, background: 'rgba(0,0,0,0.55)',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: 380, maxHeight: '80vh',
          background: '#1E222D', borderRadius: 12,
          border: '1px solid #363A45', boxShadow: '0 8px 40px rgba(0,0,0,0.6)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 16px', borderBottom: '1px solid #2A2E39',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Layers size={14} color="#2962FF" />
            <span style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>
              Consolidation Boxes — Settings
            </span>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#787B86', padding: 4 }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>

          {/* ── Group toggles ─────────────────────────────────────── */}
          <div style={{ fontSize: 10, color: '#787B86', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6, fontWeight: 600 }}>
            Display Group
          </div>

          <Toggle
            checked={s.showSameTF}
            onChange={v => update('showSameTF', v)}
            label="Same Timeframe"
            sublabel="Boxes detected on this chart's own TF"
            color="#2962FF"
          />
          <Toggle
            checked={s.showHigherTF}
            onChange={v => update('showHigherTF', v)}
            label="Higher Timeframes"
            sublabel="HTF zones overlaid on current chart"
            color="#26A69A"
          />

          {/* ── Per-TF overrides ──────────────────────────────────── */}
          <div style={{ fontSize: 10, color: '#787B86', textTransform: 'uppercase', letterSpacing: 1, marginTop: 16, marginBottom: 6, fontWeight: 600 }}>
            Per-Timeframe Override
          </div>
          <div style={{ fontSize: 10, color: '#4A4E59', marginBottom: 8 }}>
            Force on/off per TF, regardless of group setting above.
          </div>

          {backendTFs.map(tf => {
            const hasOverride = tf in s.tfOverrides;
            const overrideVal = s.tfOverrides[tf];
            return (
              <div key={tf} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '5px 0', borderBottom: '1px solid #1a1d2a',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: TF_COLORS_MAP[tf] || '#787B86',
                  }} />
                  <span style={{ fontSize: 12, color: '#D1D4DC', minWidth: 50 }}>
                    {TF_LABELS[tf] || tf}
                  </span>
                  <span style={{ fontSize: 9, color: '#4A4E59' }}>({tf})</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {hasOverride && (
                    <button
                      onClick={() => clearTfOverride(tf)}
                      title="Clear override (use group setting)"
                      style={{
                        fontSize: 9, color: '#4A4E59', background: 'none',
                        border: '1px solid #363A45', borderRadius: 4,
                        padding: '1px 5px', cursor: 'pointer',
                      }}
                    >
                      auto
                    </button>
                  )}
                  <button
                    onClick={() => setTfOverride(tf, !overrideVal)}
                    style={{
                      width: 28, height: 16, borderRadius: 8,
                      background: hasOverride
                        ? (overrideVal ? '#26A69A' : '#EF5350')
                        : '#363A45',
                      border: hasOverride ? 'none' : '1px dashed #4A4E59',
                      cursor: 'pointer', position: 'relative',
                      transition: 'background 0.2s', flexShrink: 0,
                    }}
                    title={hasOverride ? `Override: ${overrideVal ? 'ON' : 'OFF'}` : 'Click to set override'}
                  >
                    <div style={{
                      position: 'absolute', top: 3,
                      left: hasOverride && overrideVal ? 14 : 3,
                      width: 10, height: 10, borderRadius: '50%',
                      background: hasOverride ? '#fff' : '#787B86',
                      transition: 'left 0.2s',
                    }} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{
          padding: '10px 16px', borderTop: '1px solid #2A2E39',
          fontSize: 10, color: '#4A4E59', textAlign: 'center',
        }}>
          Settings auto-saved · Precedence: Per-TF override {'>'} Group toggle
        </div>
      </div>
    </div>
  );
};

export default ConsolidationSettingsModal;
