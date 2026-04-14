/**
 * SwingSettingsModal.jsx
 * ──────────────────────
 * Settings panel for the "Swing Levels" indicator.
 * Allows per-TF enable/color/lookback/extend-till-filled configuration.
 * Colors match the Pine Script defaults exactly.
 */
import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { X, RotateCcw } from 'lucide-react';
import { DEFAULT_SWING_SETTINGS, TF_LABELS, ALL_TFS } from '../../lib/swingLevels';

// ── Mini color picker (same design as SettingsPanel's ColorSwatch) ────────────
const PRESETS = [
  '#27a7b0', '#2196F3', '#4CAF50', '#FFC107', '#FF9800', '#F44336',
  '#9C27B0', '#E91E63', '#00BCD4', '#26A69A', '#2962FF', '#8BC34A',
  '#FFFFFF', '#D1D4DC', '#787B86', '#363A45', '#1E222D', '#131722',
];

const ColorDot = ({ color, onChange }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos]   = useState({ top: 0, left: 0 });
  const btnRef          = React.useRef(null);

  const handleOpen = () => {
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const left = Math.min(r.left, window.innerWidth - 180);
      const top  = r.bottom + 4;
      setPos({ top, left });
    }
    setOpen(o => !o);
  };

  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={handleOpen}
        className="w-[22px] h-[22px] rounded-full border-2 border-[#363A45] hover:border-[#787B86] transition-colors shrink-0"
        style={{ backgroundColor: color }}
        title="Choose color"
      />
      {open && ReactDOM.createPortal(
        <>
          <div className="fixed inset-0 z-[300]" onClick={() => setOpen(false)} />
          <div
            className="fixed z-[301] bg-[#1E222D] border border-[#363A45] rounded-lg shadow-2xl p-2"
            style={{ top: pos.top, left: pos.left, width: 172 }}
          >
            <div className="grid grid-cols-6 gap-1.5">
              {PRESETS.map(c => (
                <button
                  key={c}
                  onClick={() => { onChange(c); setOpen(false); }}
                  className={`w-[22px] h-[22px] rounded-sm border-2 transition-all ${color === c ? 'border-white scale-110' : 'border-transparent hover:border-[#787B86]'}`}
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
            {/* Hex input */}
            <div className="mt-2 flex items-center gap-1.5">
              <div className="w-[18px] h-[18px] rounded shrink-0 border border-[#363A45]" style={{ backgroundColor: color }} />
              <input
                value={color}
                onChange={e => onChange(e.target.value)}
                className="flex-1 bg-[#131722] border border-[#2A2E39] rounded px-1.5 py-0.5 text-[11px] text-[#D1D4DC] outline-none focus:border-[#2962FF] font-mono"
                placeholder="#rrggbb"
                spellCheck={false}
              />
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  );
};

// ── Toggle (checkbox) ─────────────────────────────────────────────────────────
const Toggle = ({ checked, onChange }) => (
  <button
    onClick={() => onChange(!checked)}
    className={`w-[16px] h-[16px] rounded-[3px] border flex items-center justify-center transition-colors shrink-0 ${
      checked ? 'bg-[#2962FF] border-[#2962FF]' : 'border-[#4A4E59] hover:border-[#787B86]'
    }`}
  >
    {checked && (
      <svg width="9" height="9" viewBox="0 0 9 9">
        <path d="M1.5 4.5l2 2L7.5 2" stroke="white" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      </svg>
    )}
  </button>
);

// ── Main Component ────────────────────────────────────────────────────────────
const SwingSettingsModal = ({ settings, onChange, onClose }) => {
  // Merge with defaults so missing keys are always present
  const s = {
    ...DEFAULT_SWING_SETTINGS,
    ...settings,
    tfs: {
      ...DEFAULT_SWING_SETTINGS.tfs,
      ...(settings?.tfs || {}),
    },
  };

  const set = (key, value) => onChange({ ...s, [key]: value });

  const setTf = (tf, key, value) =>
    onChange({
      ...s,
      tfs: {
        ...s.tfs,
        [tf]: { ...s.tfs[tf], [key]: value },
      },
    });

  const handleReset = () => onChange(DEFAULT_SWING_SETTINGS);

  return (
    <div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-[520px] max-h-[90vh] bg-[#1E222D] rounded-xl shadow-2xl border border-[#363A45] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#2A2E39]">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-[#27a7b0]" />
            <span className="text-[15px] font-semibold text-white">Swing Levels</span>
            <span className="text-[11px] text-[#787B86] bg-[#2A2E39] px-1.5 py-0.5 rounded">MTF</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="flex items-center gap-1 text-[11px] text-[#787B86] hover:text-[#D1D4DC] transition-colors"
              title="Reset to defaults"
            >
              <RotateCcw size={11} />
              Reset
            </button>
            <button onClick={onClose} className="p-1 text-[#787B86] hover:text-white hover:bg-[#2A2E3960] rounded transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">

          {/* ── Global toggles ── */}
          <div className="text-[10px] text-[#787B86] font-medium uppercase tracking-widest mb-2.5">Visibility</div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-5">
            {[
              ['showHighs',       'Show Swing Highs'],
              ['showLows',        'Show Swing Lows'],
              ['hideFilled',      'Hide Filled Levels'],
              ['filterMitigated', 'Filter Mitigated'],
              ['showMitigated',   'Show Mitigated Swings'],
            ].map(([key, label]) => (
              <label key={key} className="flex items-center gap-2.5 cursor-pointer select-none">
                <Toggle checked={!!s[key]} onChange={v => set(key, v)} />
                <span className="text-[13px] text-[#D1D4DC]">{label}</span>
              </label>
            ))}
          </div>

          <div className="h-px bg-[#2A2E39] mb-4" />

          {/* ── Per-TF table ── */}
          <div className="text-[10px] text-[#787B86] font-medium uppercase tracking-widest mb-3">Per-Timeframe Settings</div>

          {/* Table header */}
          <div className="grid text-[10px] text-[#787B86] font-medium mb-2 px-1"
            style={{ gridTemplateColumns: '40px 28px 28px 1fr 1fr' }}>
            <span>TF</span>
            <span className="text-center">On</span>
            <span className="text-center">Color</span>
            <span className="text-center">Lookback (bars)</span>
            <span className="text-center">Extend Till Filled</span>
          </div>

          {/* TF rows */}
          <div className="space-y-0.5">
            {ALL_TFS.map(tf => {
              const tfCfg = s.tfs[tf] || DEFAULT_SWING_SETTINGS.tfs[tf];
              return (
                <div
                  key={tf}
                  className={`grid items-center px-1 py-1.5 rounded-[5px] transition-colors ${
                    tfCfg.enabled ? 'bg-[#1A1E2B]' : 'bg-transparent opacity-50'
                  }`}
                  style={{ gridTemplateColumns: '40px 28px 28px 1fr 1fr' }}
                >
                  {/* TF label with color dot */}
                  <div className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: tfCfg.color }} />
                    <span className="text-[12px] font-semibold text-[#D1D4DC]">{TF_LABELS[tf]}</span>
                  </div>

                  {/* Enable toggle */}
                  <div className="flex justify-center">
                    <Toggle checked={tfCfg.enabled} onChange={v => setTf(tf, 'enabled', v)} />
                  </div>

                  {/* Color picker */}
                  <div className="flex justify-center">
                    <ColorDot color={tfCfg.color} onChange={c => setTf(tf, 'color', c)} />
                  </div>

                  {/* Lookback */}
                  <div className="flex justify-center">
                    <input
                      type="number"
                      min="1"
                      max="2000"
                      step="1"
                      value={tfCfg.lookback}
                      onChange={e => setTf(tf, 'lookback', Math.max(1, parseInt(e.target.value) || 1))}
                      disabled={!tfCfg.enabled}
                      className="w-[70px] text-center bg-[#131722] border border-[#2A2E39] rounded px-1 py-0.5 text-[12px] text-[#D1D4DC] outline-none focus:border-[#2962FF] disabled:opacity-40"
                    />
                  </div>

                  {/* Extend till filled */}
                  <div className="flex justify-center">
                    <Toggle
                      checked={tfCfg.extendTillFilled}
                      onChange={v => setTf(tf, 'extendTillFilled', v)}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          <div className="h-px bg-[#2A2E39] mt-4 mb-4" />

          {/* ── ML data note ── */}
          <div className="flex items-start gap-2.5 bg-[#131722] rounded-lg p-3 border border-[#2A2E39]">
            <div className="w-4 h-4 rounded-full bg-[#2962FF20] flex items-center justify-center shrink-0 mt-0.5">
              <div className="w-1.5 h-1.5 rounded-full bg-[#2962FF]" />
            </div>
            <div>
              <div className="text-[12px] text-[#D1D4DC] font-medium mb-0.5">ML Data Storage</div>
              <div className="text-[11px] text-[#787B86] leading-relaxed">
                All detected swing highs/lows are automatically saved to{' '}
                <code className="text-[#2962FF] bg-[#2962FF10] px-1 rounded">localStorage</code>
                {' '}under the key <code className="text-[#2962FF] bg-[#2962FF10] px-1 rounded">swing_ml_data</code>.
                Includes symbol, TF, type, price, and timestamp.
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[#2A2E39]">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-[#D1D4DC] text-[12px] rounded hover:bg-[#2A2E3960] transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default SwingSettingsModal;
