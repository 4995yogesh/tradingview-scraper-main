import React, { useState, useRef, useEffect } from 'react';
import {
  ChevronDown, Menu, Settings, Maximize2, Layout, RotateCw, Keyboard, Activity
} from 'lucide-react';
import { symbolInfo, timeframes } from '../../data/chartData';
import LayoutSelector from './LayoutSelector';

// TradingView-style shortcut map (same as ChartPage)
const TF_SHORTCUT_MAP = {
  '1': '1m', '5': '5m', '15': '15m', '30': '30m',
  '60': '1h', 'H': '1h', '1H': '1h',
  '4': '4h', '4H': '4h',
  'D': '1d', '1D': '1d',
  'W': '1w', '1W': '1w',
  'M': '1M', '1M': '1M',
};

const ChartToolbar = ({
  symbol, timeframe, onTimeframeChange,
  priceData, symbolPrecision = 5, onFullscreen,
  onSettings, onRefresh,
  activeLayout, onLayoutChange, showLayout, onToggleLayout,
  showIndicators, onToggleIndicators, panes,
  countdown,
}) => {
  const [showTimeframes, setShowTimeframes] = useState(false);
  const [showTfInput, setShowTfInput] = useState(false);
  const [tfInputVal, setTfInputVal] = useState('');
  const tfInputRef = useRef(null);
  const tfRef = useRef(null);

  // Count total active indicators across all panes (for badge)
  const totalActiveIndicators = (panes || []).reduce(
    (sum, p) => sum + ((p.indicators || []).filter(i => i.enabled).length),
    0
  );

  const info = symbolInfo[symbol] || { name: symbol, exchange: '', type: '' };
  const lastPrice = priceData?.close || priceData?.value || 0;
  const prevClose = priceData?.open || lastPrice;
  const change = lastPrice - prevClose;
  const changePct = prevClose ? ((change / prevClose) * 100) : 0;
  const isUp = change >= 0;
  const fmt = (n) => (n != null ? Number(n).toFixed(symbolPrecision) : '-');

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (tfRef.current && !tfRef.current.contains(e.target)) {
        setShowTimeframes(false);
        setShowTfInput(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const commitTfInput = () => {
    const raw = tfInputVal.trim().toUpperCase();
    const resolved = TF_SHORTCUT_MAP[raw];
    if (resolved) onTimeframeChange(resolved);
    setTfInputVal('');
    setShowTfInput(false);
  };

  // Get display label for current timeframe
  const currentTfLabel = timeframes.find(t => t.value === timeframe)?.label || 'D';

  return (
    <div className="bg-[#131722] border-b border-[#2A2E39] shrink-0">
      {/* Main toolbar row */}
      <div className="h-[38px] flex items-center px-1 gap-[2px]">
        {/* Hamburger menu */}
        <button className="w-[34px] h-[30px] flex items-center justify-center text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded-[4px] transition-colors">
          <Menu size={16} />
        </button>

        <div className="w-px h-[22px] bg-[#2A2E39] mx-[2px]" />

        {/* Locked Symbol Display */}
        <div className="flex items-center gap-1 px-2 h-[30px] rounded-[4px]">
          <span className="text-[13px] font-semibold text-white">{symbol}</span>
        </div>

        <div className="w-px h-[22px] bg-[#2A2E39] mx-[2px]" />

        {/* Timeframe selector */}
        <div className="relative flex items-center gap-0.5" ref={tfRef}>
          <button
            onClick={() => { setShowTimeframes(!showTimeframes); setShowTfInput(false); }}
            className={`flex items-center gap-0.5 px-2 h-[30px] rounded-[4px] transition-colors text-[13px] font-medium ${
              showTimeframes ? 'bg-[#2962FF20] text-[#2962FF]' : 'text-[#D1D4DC] hover:bg-[#2A2E3960]'
            }`}
          >
            {currentTfLabel}
            <ChevronDown size={11} className="text-[#787B86] ml-0.5" />
          </button>

          {/* Keyboard input toggle */}
          <button
            title="Type timeframe (e.g. 15, 4H, D)"
            onClick={() => {
              setShowTfInput(s => !s);
              setShowTimeframes(false);
              setTimeout(() => tfInputRef.current?.focus(), 50);
            }}
            className={`w-[26px] h-[26px] flex items-center justify-center rounded-[4px] transition-colors ${
              showTfInput ? 'text-[#2962FF] bg-[#2962FF15]' : 'text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960]'
            }`}
          >
            <Keyboard size={12} />
          </button>

          {showTfInput && (
            <input
              ref={tfInputRef}
              value={tfInputVal}
              onChange={e => setTfInputVal(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') commitTfInput();
                if (e.key === 'Escape') { setShowTfInput(false); setTfInputVal(''); }
              }}
              onBlur={() => { commitTfInput(); }}
              placeholder="5m…"
              className="w-[48px] h-[26px] text-[12px] bg-[#1E222D] border border-[#2962FF60] rounded px-1.5 text-white outline-none placeholder-[#4A4E59] font-mono"
            />
          )}

          {showTimeframes && (
            <div className="absolute top-full left-0 mt-1 w-[200px] bg-[#1E222D] rounded-md shadow-2xl border border-[#363A45] z-50 py-1">
              <div className="px-3 py-1.5 text-[10px] text-[#787B86] font-medium uppercase tracking-wider">Time Interval</div>
              {timeframes.map((tf) => (
                <button
                  key={tf.value}
                  onClick={() => { onTimeframeChange(tf.value); setShowTimeframes(false); }}
                  className={`w-full flex items-center justify-between px-3 py-[6px] text-[12px] hover:bg-[#2A2E39] transition-colors ${
                    timeframe === tf.value ? 'text-[#2962FF]' : 'text-[#D1D4DC]'
                  }`}
                >
                  <span>{tf.label}</span>
                  {timeframe === tf.value && (
                    <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 5l2.5 2.5L8 3" stroke="#2962FF" strokeWidth="1.5" fill="none" /></svg>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="w-px h-[22px] bg-[#2A2E39] mx-[2px]" />
        
        {/* Refresh button */}
        <button onClick={onRefresh} className="w-[30px] h-[30px] flex items-center justify-center text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded-[4px] transition-colors" title="Refresh Data">
          <RotateCw size={14} />
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Candle-close countdown — lives in the toolbar, no overlap */}
        {countdown != null && (
          <div
            className="flex items-center gap-1.5 px-2.5 h-[26px] rounded-full bg-[#1E222D] border border-[#363A45] mr-1"
            title="Next candle close"
          >
            <div className="w-1.5 h-1.5 rounded-full bg-[#787B86]" style={{ animation: 'pulse 2s ease-in-out infinite' }} />
            <span className="text-[11px] font-mono text-[#787B86]">
              {String(countdown).padStart(2, '0')}s
            </span>
          </div>
        )}

        {/* Indicators button */}
        <div className="relative">
          <button
            onClick={onToggleIndicators}
            className={`w-[30px] h-[30px] flex items-center justify-center rounded-[4px] transition-colors relative ${
              showIndicators ? 'text-[#2962FF] bg-[#2962FF15]' : 'text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960]'
            }`}
            title="Indicators"
          >
            <Activity size={14} />
            {totalActiveIndicators > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-[14px] h-[14px] bg-[#27a7b0] text-[#131722] text-[8px] font-bold rounded-full flex items-center justify-center leading-none">
                {totalActiveIndicators}
              </span>
            )}
          </button>
        </div>

        {/* Layout actions */}
        <div className="relative">
          <button onClick={onToggleLayout} className={`w-[30px] h-[30px] flex items-center justify-center rounded-[4px] transition-colors ${showLayout ? 'text-[#2962FF] bg-[#2962FF15]' : 'text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960]'}`} title="Layout">
            <Layout size={14} />
          </button>
          {showLayout && (
            <LayoutSelector activeLayout={activeLayout} onLayoutChange={onLayoutChange} isOpen={showLayout} onToggle={onToggleLayout} />
          )}
        </div>

        {/* Settings & Fullscreen */}
        <button onClick={onSettings} className="w-[30px] h-[30px] flex items-center justify-center text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded-[4px] transition-colors" title="Settings">
          <Settings size={14} />
        </button>
        <button onClick={onFullscreen} className="w-[30px] h-[30px] flex items-center justify-center text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded-[4px] transition-colors" title="Fullscreen">
          <Maximize2 size={14} />
        </button>
      </div>

      {/* Sub-header: Symbol info + OHLC */}
      <div className="h-[24px] flex items-center px-3 gap-3 border-b border-[#2A2E39] text-[11px]">
        <div className="flex items-center gap-1.5">
          <div className="w-[14px] h-[14px] rounded-full bg-[#2A2E39] flex items-center justify-center">
            <span className="text-[6px] font-bold text-[#787B86]">{symbol.slice(0, 1)}</span>
          </div>
          <span className="text-[#D1D4DC] font-medium">{info.name}</span>
          <span className="text-[#787B86]">·</span>
          <span className="text-[#787B86]">{currentTfLabel}</span>
          <span className="text-[#787B86]">·</span>
          <span className="text-[#787B86]">{info.exchange}</span>
        </div>
        {priceData && priceData.open !== undefined && (
          <div className="flex items-center gap-2">
            <span className="text-[#787B86]">O</span>
            <span className={priceData.close >= priceData.open ? 'text-[#26A69A]' : 'text-[#EF5350]'}>{fmt(priceData.open)}</span>
            <span className="text-[#787B86]">H</span>
            <span className={priceData.close >= priceData.open ? 'text-[#26A69A]' : 'text-[#EF5350]'}>{fmt(priceData.high)}</span>
            <span className="text-[#787B86]">L</span>
            <span className={priceData.close >= priceData.open ? 'text-[#26A69A]' : 'text-[#EF5350]'}>{fmt(priceData.low)}</span>
            <span className="text-[#787B86]">C</span>
            <span className={priceData.close >= priceData.open ? 'text-[#26A69A]' : 'text-[#EF5350]'}>{fmt(priceData.close)}</span>
            <span className={`font-medium ${isUp ? 'text-[#26A69A]' : 'text-[#EF5350]'}`}>
              {isUp ? '+' : ''}{change.toFixed(symbolPrecision)} ({isUp ? '+' : ''}{changePct.toFixed(2)}%)
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChartToolbar;
