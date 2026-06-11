import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Search, X, ChevronRight, ChevronLeft, Star, TrendingUp, Loader2 } from 'lucide-react';

// ── Configured symbols ────────────────────────────────────────────────────────
const MAJOR_PAIRS = [
  { symbol: 'EURUSD', label: 'EUR/USD', flag: '🇪🇺🇺🇸', base: 'EUR', quote: 'USD' },
  { symbol: 'XAUUSD', label: 'XAU/USD', flag: '🪙🇺🇸', base: 'XAU', quote: 'USD' },
];

const API_BASE = 'http://127.0.0.1:8000/api';
const STORAGE_KEY = 'forex_sidebar_v2';

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

function saveState(state) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (_) {}
}

// ─────────────────────────────────────────────────────────────────────────────

const ForexPairSidebar = ({ activeSymbol, onSymbolChange }) => {
  const saved = loadState();

  const [collapsed, setCollapsed]   = useState(saved?.collapsed ?? false);
  const [query, setQuery]           = useState('');
  const [favorites, setFavorites]   = useState(saved?.favorites ?? ['EURUSD', 'XAUUSD']);
  const searchRef = useRef(null);

  // Persist state
  useEffect(() => {
    saveState({ collapsed, favorites });
  }, [collapsed, favorites]);

  // ── Filtered pairs ──────────────────────────────────────────────────────────
  const filteredPairs = MAJOR_PAIRS.filter(p => {
    if (!query) return true;
    const q = query.toLowerCase();
    return p.symbol.toLowerCase().includes(q) || p.label.toLowerCase().includes(q);
  });

  // ── Toggle favorite ─────────────────────────────────────────────────────────
  const toggleFavorite = useCallback((symbol, e) => {
    e.stopPropagation();
    setFavorites(prev =>
      prev.includes(symbol) ? prev.filter(s => s !== symbol) : [...prev, symbol]
    );
  }, []);

  // ── Switch symbol — fire-and-forget seeding, switch chart immediately ─────
  const handleSelect = useCallback((symbol) => {
    if (symbol === activeSymbol) return;

    // Fire-and-forget: tell backend to seed this pair — do NOT await it.
    // The chart switches immediately; seeding runs in background.
    fetch(`${API_BASE}/fetch-symbol?exchange=OANDA&symbol=${symbol}`, { method: 'POST' })
      .catch(() => {}); // ignore errors silently

    onSymbolChange(symbol);
  }, [activeSymbol, onSymbolChange]);

  // ── Prefetch on hover — warms the backend cache before click ──────────────
  const handleHover = useCallback((symbol) => {
    if (symbol === activeSymbol) return;
    // Pre-warm the OHLC cache for all pane timeframes silently
    const tfs = ['1d', '4h', '1h', '15m'];
    tfs.forEach(tf => {
      fetch(`${API_BASE}/ohlc?exchange=OANDA&symbol=${symbol}&timeframe=${tf}&candles=750`)
        .catch(() => {});
    });
  }, [activeSymbol]);

  // ── Sorted list: favorites first, then rest ─────────────────────────────────
  const sortedPairs = [...filteredPairs].sort((a, b) => {
    const af = favorites.includes(a.symbol);
    const bf = favorites.includes(b.symbol);
    if (af && !bf) return -1;
    if (!af && bf) return 1;
    return 0;
  });

  // ── Collapsed strip ─────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center bg-[#0A0A0F] border-r border-[#1E2235] py-3 gap-2 shrink-0"
        style={{ width: 36 }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="w-7 h-7 flex items-center justify-center rounded-md text-[#2962FF] hover:bg-[#2962FF15] transition-colors"
          title="Expand pair list"
        >
          <ChevronRight size={13} />
        </button>

        {/* Stacked symbols — click any to expand */}
        {MAJOR_PAIRS.map(p => (
          <button
            key={p.symbol}
            onClick={() => { setCollapsed(false); handleSelect(p.symbol); }}
            className={`w-7 flex flex-col items-center gap-[1px] py-0.5 rounded transition-colors ${
              p.symbol === activeSymbol ? 'bg-[#2962FF20]' : 'hover:bg-[#1E2235]'
            }`}
            title={p.label}
          >
            <span className="text-[9px]">{p.flag.slice(0, 2)}</span>
            <span className={`text-[6px] font-bold leading-none ${p.symbol === activeSymbol ? 'text-[#2962FF]' : 'text-[#4A4E59]'}`}>
              {p.base}
            </span>
          </button>
        ))}
      </div>
    );
  }

  // ── Expanded panel ──────────────────────────────────────────────────────────
  return (
    <div
      className="flex flex-col bg-[#0A0A0F] border-r border-[#1E2235] shrink-0 overflow-hidden"
      style={{ width: 196 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#1E2235] shrink-0">
        <div className="flex items-center gap-1.5">
          <TrendingUp size={11} className="text-[#2962FF]" />
          <span className="text-[11px] font-semibold text-[#D1D4DC] tracking-wide">MAJOR PAIRS</span>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="w-5 h-5 flex items-center justify-center rounded text-[#4A4E59] hover:text-[#787B86] hover:bg-[#1E2235] transition-colors"
          title="Collapse"
        >
          <ChevronLeft size={12} />
        </button>
      </div>

      {/* Search */}
      <div className="px-2 py-1.5 border-b border-[#1E2235] shrink-0">
        <div className="relative flex items-center">
          <Search size={10} className="absolute left-2 text-[#4A4E59] pointer-events-none" />
          <input
            ref={searchRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Filter pairs…"
            className="w-full bg-[#13141F] border border-[#1E2235] rounded-[4px] pl-6 pr-2 py-1 text-[11px] text-[#D1D4DC] placeholder-[#4A4E59] outline-none focus:border-[#2962FF60] transition-colors"
          />
          {query && (
            <button onClick={() => setQuery('')} className="absolute right-1.5 text-[#4A4E59] hover:text-[#787B86]">
              <X size={9} />
            </button>
          )}
        </div>
      </div>

      {/* Pair list */}
      <div className="flex-1 overflow-y-auto py-1" style={{ scrollbarWidth: 'thin', scrollbarColor: '#2A2E39 transparent' }}>
        {sortedPairs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2">
            <span className="text-[24px]">🔍</span>
            <span className="text-[10px] text-[#4A4E59]">No pairs match</span>
          </div>
        ) : (
          sortedPairs.map(pair => {
            const isActive = pair.symbol === activeSymbol;
            const isFav    = favorites.includes(pair.symbol);
            return (
              <button
                key={pair.symbol}
                onClick={() => handleSelect(pair.symbol)}
                onMouseEnter={() => handleHover(pair.symbol)}
                className={`w-full flex items-center justify-between px-2.5 py-[6px] text-left transition-all group border-l-2 ${
                  isActive
                    ? 'bg-[#2962FF14] border-[#2962FF]'
                    : 'border-transparent hover:bg-[#1E2235] hover:border-[#2962FF40]'
                }`}
              >
                {/* Left: flag + label */}
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[13px] shrink-0" aria-hidden="true">{pair.flag}</span>
                  <div className="flex flex-col min-w-0">
                    <span className={`text-[12px] font-semibold leading-tight ${isActive ? 'text-[#2962FF]' : 'text-[#D1D4DC]'}`}>
                      {pair.label}
                    </span>
                    <span className="text-[9px] text-[#4A4E59] leading-none">Major · OANDA</span>
                  </div>
                </div>

                {/* Right: star */}
                <div className="flex items-center gap-0.5 shrink-0">
                  <button
                    onClick={e => toggleFavorite(pair.symbol, e)}
                    className={`w-4 h-4 flex items-center justify-center rounded transition-colors ${
                      isFav
                        ? 'text-[#F5A623]'
                        : 'text-transparent group-hover:text-[#4A4E59] hover:!text-[#F5A623]'
                    }`}
                    title={isFav ? 'Unfavorite' : 'Favorite'}
                  >
                    <Star size={9} fill={isFav ? 'currentColor' : 'none'} />
                  </button>
                </div>
              </button>
            );
          })
        )}
      </div>

      {/* Active symbol badge */}
      <div className="px-2 pb-2 pt-1 border-t border-[#1E2235] shrink-0">
        <div className="flex items-center gap-1.5 px-2 py-1 bg-[#2962FF10] border border-[#2962FF30] rounded-[4px]">
          <div className="w-1.5 h-1.5 rounded-full bg-[#2962FF] shadow-[0_0_4px_#2962FF] animate-pulse shrink-0" />
          <span className="text-[10px] text-[#2962FF] font-mono font-semibold">
            {MAJOR_PAIRS.find(p => p.symbol === activeSymbol)?.label || activeSymbol}
          </span>
          <span className="text-[9px] text-[#4A4E59] ml-auto">LIVE</span>
        </div>
      </div>
    </div>
  );
};

export default ForexPairSidebar;
