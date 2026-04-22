/**
 * ConsolidationSettingsModal.jsx
 * ──────────────────────────────
 * Minimal settings for Consolidation Boxes.
 * Single HTF toggle: show/hide boxes from timeframes
 * higher than the current chart timeframe.
 */
import React from 'react';
import { X, Layers } from 'lucide-react';

export const DEFAULT_CONSOLIDATION_SETTINGS = {
  showHTF: true,
};

// ─── Pill toggle switch ──────────────────────────────────────────────────────
const PillSwitch = ({ checked, onChange }) => (
  <button
    role="switch"
    aria-checked={checked}
    onClick={() => onChange(!checked)}
    className={`relative inline-flex items-center h-[22px] w-[40px] rounded-full transition-colors duration-200 focus:outline-none ${
      checked ? 'bg-[#2962FF]' : 'bg-[#363A45]'
    }`}
  >
    <span
      className={`inline-block h-[16px] w-[16px] rounded-full bg-white shadow transform transition-transform duration-200 ${
        checked ? 'translate-x-[21px]' : 'translate-x-[3px]'
      }`}
    />
  </button>
);

// ─── Main Component ──────────────────────────────────────────────────────────
const ConsolidationSettingsModal = ({ settings, onChange, onClose }) => {
  const s = { ...DEFAULT_CONSOLIDATION_SETTINGS, ...settings };
  const set = (key, val) => onChange({ ...s, [key]: val });

  return (
    <div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-[340px] bg-[#1E222D] rounded-xl shadow-2xl border border-[#363A45] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A2E39]">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-[#2962FF20] flex items-center justify-center">
              <Layers size={12} className="text-[#2962FF]" />
            </div>
            <span className="text-[14px] font-semibold text-white">Consolidation Boxes</span>
            <span className="text-[10px] text-[#787B86] bg-[#2A2E39] px-1.5 py-0.5 rounded">MTF</span>
          </div>
          <button onClick={onClose} className="p-1 text-[#787B86] hover:text-white hover:bg-[#2A2E3960] rounded transition-colors">
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-3">

          {/* HTF toggle row */}
          <div className="flex items-center justify-between py-2 px-3 bg-[#131722] rounded-lg border border-[#2A2E39]">
            <div>
              <div className="text-[13px] font-medium text-[#D1D4DC]">Show HTF Boxes</div>
              <div className="text-[11px] text-[#787B86] mt-0.5">
                Display consolidation zones from higher timeframes
              </div>
            </div>
            <PillSwitch
              checked={!!s.showHTF}
              onChange={v => set('showHTF', v)}
            />
          </div>

        </div>

        {/* Footer */}
        <div className="flex justify-end px-4 py-3 border-t border-[#2A2E39]">
          <button
            onClick={onClose}
            className="px-5 py-1.5 bg-[#2962FF] hover:bg-[#1E53E5] text-white text-[12px] font-medium rounded transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConsolidationSettingsModal;
