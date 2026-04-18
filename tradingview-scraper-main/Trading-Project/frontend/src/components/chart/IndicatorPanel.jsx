/**
 * IndicatorPanel.jsx
 * ──────────────────
 * TradingView-style indicator picker panel.
 *
 * Flow:
 *  1. User clicks "Indicators" in the top toolbar → this panel opens
 *  2. If multi-layout (> 1 pane), shows pane selector at top
 *  3. Shows searchable list of available indicators
 *  4. Active indicators for the selected pane are listed with eye/settings/delete
 *  5. Clicking ⚙ on an active indicator opens its settings (SwingSettingsModal)
 */
import React, { useState, useRef, useEffect } from 'react';
import { X, Search, Eye, EyeOff, Settings, Trash2, Plus, Activity } from 'lucide-react';
import SwingSettingsModal from './SwingSettingsModal';
import ConsolidationSettingsModal, { DEFAULT_CONSOLIDATION_SETTINGS } from './ConsolidationSettingsModal';
import { DEFAULT_SWING_SETTINGS, TF_COLORS } from '../../lib/swingLevels';

// ── Available indicator catalogue ─────────────────────────────────────────────
const INDICATOR_CATALOGUE = [
  {
    type:        'swingLevels',
    name:        'Swing Levels',
    author:      'LeviathanCapital',
    description: 'Multi-timeframe pivot swing highs and lows',
    color:       '#27a7b0',
    tags:        ['swing', 'pivot', 'multi-tf', 'levels', 'structure'],
    defaultSettings: DEFAULT_SWING_SETTINGS,
  },
  {
    type:        'consolidationBoxes',
    name:        'Consolidation Boxes',
    author:      'Antigravity',
    description: 'Multi-timeframe consolidation zone detection',
    color:       '#2962FF',
    tags:        ['consolidation', 'boxes', 'multi-tf', 'structure'],
    defaultSettings: { ...DEFAULT_CONSOLIDATION_SETTINGS },
  },
];

// ── Layout pane count map ─────────────────────────────────────────────────────
const LAYOUT_PANE_COUNT = { '1': 1, '2h': 2, '2v': 2, '4': 4, '3r': 3 };

// ── Pane selector visual grid ─────────────────────────────────────────────────
const LAYOUT_GRIDS = {
  '2h': [[0, 1]],
  '2v': [[0], [1]],
  '4':  [[0, 1], [2, 3]],
  '3r': [[0, null], [null, 1], [null, 2]], // main + 2 right
};

const PaneSelector = ({ activeLayout, selectedPane, onSelectPane }) => {
  const paneCount = LAYOUT_PANE_COUNT[activeLayout] || 1;
  if (paneCount === 1) return null;

  const labels = ['Chart 1', 'Chart 2', 'Chart 3', 'Chart 4'];

  return (
    <div className="px-4 pt-3 pb-0">
      <div className="text-[10px] text-[#787B86] uppercase tracking-widest mb-2 font-medium">Add to chart</div>
      <div className="flex gap-2">
        {Array.from({ length: paneCount }, (_, i) => (
          <button
            key={i}
            onClick={() => onSelectPane(i)}
            className={`flex-1 py-1.5 text-[12px] rounded-md border transition-all font-medium ${
              selectedPane === i
                ? 'bg-[#2962FF20] border-[#2962FF] text-[#2962FF]'
                : 'border-[#363A45] text-[#787B86] hover:border-[#787B86] hover:text-[#D1D4DC]'
            }`}
          >
            {labels[i]}
          </button>
        ))}
      </div>
    </div>
  );
};

// ── Active indicator row ──────────────────────────────────────────────────────
const ActiveIndicatorRow = ({ indicator, onToggleVisible, onSettings, onRemove }) => {
  const cat = INDICATOR_CATALOGUE.find(c => c.type === indicator.type);
  if (!cat) return null;

  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-[#1A1D2E] border border-[#2A2E39] hover:border-[#363A45] transition-all group">
      <div className="flex items-center gap-2.5 min-w-0">
        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: cat.color }} />
        <span className="text-[13px] text-[#D1D4DC] font-medium truncate">{cat.name}</span>
        <span className="text-[10px] text-[#787B86] shrink-0">MTF</span>
      </div>
      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onToggleVisible}
          className="p-1.5 text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded transition-colors"
          title={indicator.enabled ? 'Hide' : 'Show'}
        >
          {indicator.enabled ? <Eye size={13} /> : <EyeOff size={13} />}
        </button>
        <button
          onClick={onSettings}
          className="p-1.5 text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded transition-colors"
          title="Settings"
        >
          <Settings size={13} />
        </button>
        <button
          onClick={onRemove}
          className="p-1.5 text-[#787B86] hover:text-[#EF5350] hover:bg-[#EF535015] rounded transition-colors"
          title="Remove"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
};

// ── Catalogue indicator card ──────────────────────────────────────────────────
const CatalogueCard = ({ indicator, onAdd, isActive }) => (
  <div className="flex items-center justify-between px-3 py-2.5 rounded-lg border border-[#2A2E39] hover:border-[#363A45] hover:bg-[#1A1D2E] transition-all group">
    <div className="flex items-center gap-3 min-w-0">
      <div
        className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
        style={{ backgroundColor: indicator.color + '25' }}
      >
        <Activity size={13} style={{ color: indicator.color }} />
      </div>
      <div className="min-w-0">
        <div className="text-[13px] text-[#D1D4DC] font-medium">{indicator.name}</div>
        <div className="text-[11px] text-[#787B86] truncate">{indicator.description}</div>
      </div>
    </div>
    {isActive ? (
      <div className="flex items-center gap-1 text-[11px] text-[#26A69A] shrink-0 ml-2">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 5l2.5 2.5L8 3" stroke="currentColor" strokeWidth="1.5" fill="none" /></svg>
        Added
      </div>
    ) : (
      <button
        onClick={onAdd}
        className="flex items-center gap-1 px-2.5 py-1 text-[11px] bg-[#2962FF20] text-[#2962FF] hover:bg-[#2962FF] hover:text-white rounded-md transition-colors shrink-0 ml-2 font-medium"
      >
        <Plus size={11} />
        Add
      </button>
    )}
  </div>
);

// ── Main Component ────────────────────────────────────────────────────────────
const IndicatorPanel = ({
  activeLayout,
  panes,
  activePaneIdx,
  onUpdatePane,
  onClose,
}) => {
  const [selectedPane, setSelectedPane] = useState(activePaneIdx);
  const [search, setSearch] = useState('');
  const [editingIndicator, setEditingIndicator] = useState(null); // { paneIdx, indicatorIdx }
  const searchRef = useRef(null);

  useEffect(() => { searchRef.current?.focus(); }, []);

  // Keep selected pane in valid range
  const paneCount = LAYOUT_PANE_COUNT[activeLayout] || 1;
  const safePane  = Math.min(selectedPane, paneCount - 1);
  const pane      = panes[safePane] || panes[0] || {};
  const paneIndicators = pane.indicators || [];

  // Search filter
  const filteredCatalogue = INDICATOR_CATALOGUE.filter(ind =>
    !search.trim() ||
    ind.name.toLowerCase().includes(search.toLowerCase()) ||
    ind.tags.some(t => t.includes(search.toLowerCase()))
  );

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleAdd = (catalogueItem) => {
    const newIndicator = {
      id:       `${catalogueItem.type}_${Date.now()}`,
      type:     catalogueItem.type,
      enabled:  true,
      settings: { ...catalogueItem.defaultSettings },
    };
    const updated = [...paneIndicators, newIndicator];
    onUpdatePane(safePane, 'indicators', updated);
  };

  const handleToggleVisible = (indicatorIdx) => {
    const updated = paneIndicators.map((ind, i) =>
      i === indicatorIdx ? { ...ind, enabled: !ind.enabled } : ind
    );
    onUpdatePane(safePane, 'indicators', updated);
  };

  const handleRemove = (indicatorIdx) => {
    const updated = paneIndicators.filter((_, i) => i !== indicatorIdx);
    onUpdatePane(safePane, 'indicators', updated);
    if (editingIndicator?.paneIdx === safePane && editingIndicator?.indicatorIdx === indicatorIdx) {
      setEditingIndicator(null);
    }
  };

  const handleOpenSettings = (indicatorIdx) => {
    setEditingIndicator({ paneIdx: safePane, indicatorIdx });
  };

  const handleSettingsChange = (newSettings) => {
    if (!editingIndicator) return;
    const { paneIdx, indicatorIdx } = editingIndicator;
    const targetPane = panes[paneIdx] || {};
    const updated = (targetPane.indicators || []).map((ind, i) =>
      i === indicatorIdx ? { ...ind, settings: newSettings } : ind
    );
    onUpdatePane(paneIdx, 'indicators', updated);
  };

  const isActive = (type) => paneIndicators.some(ind => ind.type === type);

  // ── Settings modal for editing indicator ──────────────────────────────────
  if (editingIndicator) {
    const { paneIdx, indicatorIdx } = editingIndicator;
    const targetIndicator = (panes[paneIdx]?.indicators || [])[indicatorIdx];
    if (!targetIndicator) { setEditingIndicator(null); return null; }

    // Route to the correct modal by indicator type
    if (targetIndicator.type === 'consolidationBoxes') {
      return (
        <ConsolidationSettingsModal
          settings={targetIndicator.settings}
          onChange={handleSettingsChange}
          onClose={() => setEditingIndicator(null)}
        />
      );
    }

    return (
      <SwingSettingsModal
        settings={targetIndicator.settings}
        onChange={handleSettingsChange}
        onClose={() => setEditingIndicator(null)}
      />
    );
  }

  // ── Main panel ────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[60px]" onClick={onClose}>
      <div
        className="w-[420px] max-h-[75vh] bg-[#1E222D] rounded-xl shadow-2xl border border-[#363A45] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A2E39]">
          <span className="text-[15px] font-semibold text-white">Indicators</span>
          <button onClick={onClose} className="p-1 text-[#787B86] hover:text-white hover:bg-[#2A2E3960] rounded transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Pane selector (multi-layout only) */}
        <PaneSelector
          activeLayout={activeLayout}
          selectedPane={safePane}
          onSelectPane={setSelectedPane}
        />

        {/* Search */}
        <div className="px-4 pt-3 pb-2">
          <div className="flex items-center gap-2 bg-[#131722] border border-[#2A2E39] rounded-lg px-3 py-1.5 focus-within:border-[#2962FF] transition-colors">
            <Search size={13} className="text-[#787B86] shrink-0" />
            <input
              ref={searchRef}
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search indicators…"
              className="flex-1 bg-transparent text-[13px] text-[#D1D4DC] outline-none placeholder-[#4A4E59]"
            />
          </div>
        </div>

        {/* Body - scrollable */}
        <div className="flex-1 overflow-y-auto px-4 py-2 space-y-4">

          {/* Active indicators on selected pane */}
          {paneIndicators.length > 0 && (
            <div>
              <div className="text-[10px] text-[#787B86] uppercase tracking-widest mb-2 font-medium">
                Active on Chart {safePane + 1}
              </div>
              <div className="space-y-1.5">
                {paneIndicators.map((ind, idx) => (
                  <ActiveIndicatorRow
                    key={ind.id || idx}
                    indicator={ind}
                    onToggleVisible={() => handleToggleVisible(idx)}
                    onSettings={() => handleOpenSettings(idx)}
                    onRemove={() => handleRemove(idx)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Catalogue */}
          <div>
            <div className="text-[10px] text-[#787B86] uppercase tracking-widest mb-2 font-medium">
              {search.trim() ? 'Search Results' : 'Available Indicators'}
            </div>
            {filteredCatalogue.length === 0 ? (
              <div className="text-center py-6 text-[#787B86] text-[13px]">No indicators found</div>
            ) : (
              <div className="space-y-1.5">
                {filteredCatalogue.map(ind => (
                  <CatalogueCard
                    key={ind.type}
                    indicator={ind}
                    onAdd={() => handleAdd(ind)}
                    isActive={isActive(ind.type)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2.5 border-t border-[#2A2E39]">
          <p className="text-[10px] text-[#787B86] text-center">
            Swing data is automatically saved to{' '}
            <code className="text-[#2962FF]">localStorage[&apos;swing_ml_data&apos;]</code>{' '}
            for ML training
          </p>
        </div>
      </div>
    </div>
  );
};

export default IndicatorPanel;
