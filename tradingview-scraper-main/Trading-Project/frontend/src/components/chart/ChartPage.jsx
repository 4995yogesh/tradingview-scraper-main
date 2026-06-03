import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useChartMemory } from '../../hooks/useChartMemory';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import ChartWidget from './ChartWidget';
import ChartToolbar from './ChartToolbar';
import SettingsPanel from './SettingsPanel';
import LayoutSelector from './LayoutSelector';
import IndicatorPanel from './IndicatorPanel';
import ForexPairSidebar from './ForexPairSidebar';

// ── Keyboard timeframe shortcut map (TradingView-style) ─────────────────────
// Supports both single-key and multi-char sequences (e.g. "15", "4H", "30")
const TF_SHORTCUT_MAP = {
  '1':   '1m',
  '5':   '5m',
  '15':  '15m',
'60':  '1h',
  'H':   '1h',
  '1H':  '1h',
  '4':   '4h',
  '4H':  '4h',
  'D':   '1d',
  '1D':  '1d',
  'W':   '1w',
  '1W':  '1w',
  'M':   '1M',
  '1M':  '1M',
};

// Auto-refresh interval in seconds
const AUTO_REFRESH_INTERVAL = 5;

// Symbol precision map — 3 decimal pairs use JPY cross convention
const JPY_PAIRS = new Set(['USDJPY','EURJPY','GBPJPY','AUDJPY','CHFJPY','NZDJPY','CADJPY']);

export function getSymbolPrecision(symbol) {
  if (symbol === 'XAUUSD') return 2;
  return JPY_PAIRS.has(symbol) ? 3 : 5;
}

const DEFAULT_SYMBOL = 'EURUSD';

const defaultPanes = [
  { symbol: DEFAULT_SYMBOL, timeframe: '1d', chartType: 'hollow', indicators: [] },
  { symbol: DEFAULT_SYMBOL, timeframe: '4h', chartType: 'hollow', indicators: [] },
  { symbol: DEFAULT_SYMBOL, timeframe: '1h', chartType: 'hollow', indicators: [] },
  { symbol: DEFAULT_SYMBOL, timeframe: '15m', chartType: 'hollow', indicators: [] },
];

/**
 * getSwingSettings
 * ────────────────
 * Extracts the first enabled/disabled SwingLevels indicator from a pane's
 * indicators array and returns the shape expected by ChartWidget.
 * Returns null if the pane has no Swing Levels indicator.
 */
function getSwingSettings(pane) {
  const ind = (pane?.indicators || []).find(i => i.type === 'swingLevels');
  if (!ind) return null;
  return { enabled: ind.enabled, settings: ind.settings };
}

function getConsolidationSettings(pane) {
  const ind = (pane?.indicators || []).find(i => i.type === 'consolidationBoxes');
  if (!ind) return null;
  return { enabled: ind.enabled, settings: ind.settings };
}

function getNeuralSettings(pane) {
  const ind = (pane?.indicators || []).find(i => i.type === 'neuralBoxes');
  if (!ind) return null;
  return { enabled: ind.enabled, settings: ind.settings };
}

const ResizeHandle = ({ direction = 'horizontal', onDoubleClick }) => (
  <PanelResizeHandle 
    className={`group relative flex items-center justify-center ${
      direction === 'horizontal' ? 'w-[5px] cursor-col-resize' : 'h-[5px] cursor-row-resize'
    } bg-[#2A2E39] hover:bg-[#2962FF60] active:bg-[#2962FF] transition-colors`}
    onDoubleClick={onDoubleClick}
  >
    <div className={`${
      direction === 'horizontal' ? 'w-[3px] h-8' : 'h-[3px] w-8'
    } rounded-full bg-[#363A45] group-hover:bg-[#2962FF] transition-colors`} />
  </PanelResizeHandle>
);

const ChartPage = () => {
  const { symbol: urlSymbol } = useParams();
  const chartWidgetRef = useRef(null);
  const containerRef = useRef(null);

  // ── Persisted state (auto-saved to localStorage via useChartMemory) ──────────
  const [symbol, setSymbol] = useChartMemory('activeSymbol', DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useChartMemory('timeframe', '1d');
  const [chartType, setChartType] = useChartMemory('chartType', 'hollow');
  const [panes, setPanes] = useChartMemory('panes', defaultPanes);

  // ── Keyboard shortcut state ──────────────────────────────────────────────────
  const [kbBuffer, setKbBuffer] = useState('');
  const kbTimerRef = useRef(null);
  const kbActivePane = useRef(0); // mirrors activePaneIdx without closure issues

  const [logScale, setLogScale] = useChartMemory('logScale', false);
  const [chartSettings, setChartSettings] = useChartMemory('chartSettings', {
    background: '#000000', gridColor: '#000000', showGrid: true, crosshairMode: 'normal',
    upColor: '#26A69A', downColor: '#EF5350', timezone: 'exchange',
    sessionBreaks: false, watermark: false,
  });
  const [activeLayout, setActiveLayout] = useChartMemory('activeLayout', '1');

  // ── Transient state (not persisted) ─────────────────────────────────────────
  const [activePaneIdx, setActivePaneIdx] = useState(0);
  const [layoutResetKey, setLayoutResetKey] = useState(0);
  const [priceData, setPriceData] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showLayout, setShowLayout] = useState(false);
  const [showIndicators, setShowIndicators] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [toastMsg, setToastMsg] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [countdown, setCountdown] = useState(AUTO_REFRESH_INTERVAL);
  const [liveTickKey, setLiveTickKey] = useState(0);
  const [showML, setShowML] = useState(false);
  const [showNN, setShowNN] = useState(false);
  const [showPM, setShowPM] = useState(true);


  const symbolPrecision = getSymbolPrecision(symbol);

  // ── Shared data polling — fetches once for ALL panes, not per-ChartWidget ───────
  // Prevents N-chart × 4-endpoint = 16+ concurrent requests every 5 seconds.
  const [sharedConsolidations, setSharedConsolidations] = useState([]);
  const [sharedSwings,         setSharedSwings        ] = useState([]);
  const [sharedAutoLabels,     setSharedAutoLabels    ] = useState([]);
  const [sharedNNZones,        setSharedNNZones       ] = useState([]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const [cRes, sRes, aRes] = await Promise.all([
          fetch('http://localhost:8000/consolidations'),
          fetch('http://localhost:8000/swings'),
          fetch('http://localhost:8000/api/ml/quality/auto-labels'),
        ]);
        if (!cancelled) {
          if (cRes.ok) { const d = await cRes.json(); if (d.status === 'ok') setSharedConsolidations(d.zones || []); }
          if (sRes.ok) { const d = await sRes.json(); if (d.status === 'ok') setSharedSwings(d.swings || []); }
          if (aRes.ok) { const d = await aRes.json(); setSharedAutoLabels(d || []); }
        }
      } catch (_) {}
    };
    poll();
    const iv = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(iv); };
  }, []);

  // NN zones are per-symbol+timeframe — fetch once for the active pane's symbol
  useEffect(() => {
    let cancelled = false;
    const fetchNN = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/nn/refined_zones?symbol=${symbol}&timeframe=${timeframe}`);
        if (res.ok && !cancelled) {
          const d = await res.json();
          setSharedNNZones(d || []);
        }
      } catch (_) {}
    };
    fetchNN();
    const iv = setInterval(fetchNN, 5000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [symbol, timeframe]);

  // ── 5-Second Auto Refresh ───────────────────────────────────────────────
  useEffect(() => {
    let lastPeriod = Math.floor(new Date().getSeconds() / 5);

    const getSecondsLeft = () => {
      const secs = new Date().getSeconds() % 5;
      const left = 5 - secs;
      return left === 0 ? 5 : left;
    };

    setCountdown(getSecondsLeft());

    const tick = setInterval(() => {
      setCountdown(getSecondsLeft());
      
      const currentPeriod = Math.floor(new Date().getSeconds() / 5);
      if (currentPeriod !== lastPeriod) {
        lastPeriod = currentPeriod;
        setLiveTickKey(prev => prev + 1);
      }
    }, 1000);

    return () => clearInterval(tick);
  }, []);

  const showToast = useCallback((msg) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 2500);
  }, []);

  const handleResetLayout = useCallback(() => {
    setLayoutResetKey(k => k + 1);
  }, []);

  const handlePriceUpdate = useCallback((data) => { setPriceData(data); }, []);
  
  const handleRefresh = useCallback(() => {
    setRefreshKey(prev => prev + 1);
    showToast('Refreshing chart data...');
  }, [showToast]);

  const handleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen?.();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  }, []);

  const handleBottomRange = useCallback((range) => {
    chartWidgetRef.current?.setVisibleRange(range);
  }, []);

  // Fullscreen change listener
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  // Handle symbol switch: update all panes to new symbol
  const handleSymbolChange = useCallback((newSymbol) => {
    setSymbol(newSymbol);
    setPanes(prev => prev.map(p => ({ ...p, symbol: newSymbol })));
  }, [setSymbol, setPanes]);

  // Sync URL symbol parameter to active symbol
  useEffect(() => {
    if (urlSymbol) {
      const normalized = urlSymbol.toUpperCase();
      if (normalized !== symbol) {
        handleSymbolChange(normalized);
      }
    }
  }, [urlSymbol, symbol, handleSymbolChange]);

  // Sync pane state — symbol + chartType kept in sync across panes
  const updatePane = useCallback((idx, key, value) => {
    setPanes(prev => prev.map((p, i) => i === idx ? { ...p, [key]: value } : p));
    if (idx === 0) {
      if (key === 'timeframe') setTimeframe(value);
      if (key === 'chartType') setChartType(value);
    }
  }, [setPanes, setTimeframe, setChartType]);

  // Ensure all panes share the global symbol and chartType
  useEffect(() => {
    setPanes(prev => prev.map((p, i) => {
      const update = { ...p, symbol: symbol, chartType: chartType };
      if (i === 0) { update.timeframe = timeframe; }
      return update;
    }));
  }, [symbol, timeframe, chartType, setPanes]);

  // Keep keyboard active-pane ref in sync
  useEffect(() => { kbActivePane.current = activePaneIdx; }, [activePaneIdx]);

  // ── Global keyboard timeframe shortcut (commit on Enter) ────────────────────
  useEffect(() => {
    const handleKey = (e) => {
      // Ignore when typing in inputs/textareas
      const tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable) return;

      // Enter: commit current buffer as timeframe
      if (e.key === 'Enter') {
        setKbBuffer(buf => {
          if (buf && TF_SHORTCUT_MAP[buf]) {
            const tf = TF_SHORTCUT_MAP[buf];
            const paneIdx = kbActivePane.current;
            updatePane(paneIdx, 'timeframe', tf);
            if (paneIdx === 0) setTimeframe(tf);
          }
          return '';
        });
        return;
      }

      // Escape: clear buffer without applying
      if (e.key === 'Escape') { setKbBuffer(''); return; }

      // Backspace: delete last char from buffer
      if (e.key === 'Backspace') { setKbBuffer(prev => prev.slice(0, -1)); return; }

      // Only handle alphanumeric
      if (!/^[a-zA-Z0-9]$/.test(e.key)) return;

      const char = e.key.toUpperCase();
      setKbBuffer(prev => {
        const next = prev + char;
        // Only accept characters that could still build a valid TF shortcut
        const stillPossible = Object.keys(TF_SHORTCUT_MAP).some(k => k.startsWith(next));
        return stillPossible ? next : prev;
      });
    };

    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updatePane, setTimeframe]);

  const lastTfSwitchRef = useRef(0);
  // ── ML auto-timeframe switch listener ──────────────────────────────────────
  useEffect(() => {
    const handleTfSwitch = (e) => {
      let { timeframe: targetTf, originalEvent } = e.detail;
      if (!targetTf) return;
      targetTf = targetTf.toLowerCase();
      
      const now = Date.now();
      if (now - lastTfSwitchRef.current < 2000) return; // Cooldown 2s
      lastTfSwitchRef.current = now;
      
      console.log(`[App] Switching TF to ${targetTf} for ML Nav...`);
      // Update global and pane 0 timeframe
      setTimeframe(targetTf);
      updatePane(0, 'timeframe', targetTf);
      
      // Re-trigger the goto event after the chart has had a moment to switch
      setTimeout(() => {
        console.log(`[App] Retrying ML Nav for ${originalEvent.box_id}...`);
        window.dispatchEvent(new CustomEvent('ml-goto-box', { detail: originalEvent }));
      }, 1200);
    };

    window.addEventListener('ml-change-timeframe', handleTfSwitch);
    return () => window.removeEventListener('ml-change-timeframe', handleTfSwitch);
  }, [setTimeframe, updatePane]);

  const PaneMiniToolbar = ({ pane, idx }) => {
    const [showTf, setShowTf] = useState(false);
    const [tfInput, setTfInput] = useState('');
    const [showInput, setShowInput] = useState(false);
    const inputRef = useRef(null);
    const tfLabels = { '1m': '1m', '5m': '5m', '15m': '15m','1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W', '1M': '1M' };

    const commitTfInput = () => {
      const raw = tfInput.trim().toUpperCase();
      const resolved = TF_SHORTCUT_MAP[raw];
      if (resolved) {
        updatePane(idx, 'timeframe', resolved);
        if (idx === 0) setTimeframe(resolved);
      }
      setTfInput('');
      setShowInput(false);
    };

    // Active indicator badges for this pane
    const activeIndicators = pane.indicators || [];

    return (
      <div className="absolute top-0 left-0 right-0 z-20 flex items-center gap-1 px-2 py-1 bg-[#000000E0] border-b border-[#2A2E39]" onClick={e => e.stopPropagation()}>
        <span className="text-[6px] font-semibold text-white">{pane.symbol || symbol}</span>
        <div className="relative">
          <button onClick={() => { setShowTf(!showTf); setShowInput(false); }} className="text-[5px] text-[#787B86] hover:text-white bg-[#2A2E39] px-1.5 py-0.5 rounded transition-colors">
            {tfLabels[pane.timeframe] || '1D'}
          </button>
          {showTf && (
            <div className="absolute top-full left-0 mt-1 bg-[#1E222D] border border-[#363A45] rounded shadow-xl z-50 py-1 w-[60px]">
              {Object.entries(tfLabels).map(([val, lbl]) => (
                <button key={val} onClick={() => { updatePane(idx, 'timeframe', val); setShowTf(false); }}
                  className={`w-full px-2 py-1 text-[10px] text-left hover:bg-[#2A2E39] ${pane.timeframe === val ? 'text-[#2962FF]' : 'text-[#D1D4DC]'}`}>
                  {lbl}
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Manual TF input button */}
        <button
          title="Type timeframe (e.g. 5, 15, 4H, D)"
          onClick={() => { setShowInput(s => !s); setShowTf(false); setTimeout(() => inputRef.current?.focus(), 50); }}
          className="text-[4px] text-[#787B86] hover:text-[#2962FF] bg-[#1E222D] border border-[#363A45] px-1 py-0.5 rounded transition-colors"
        >T</button>
        {showInput && (
          <input
            ref={inputRef}
            value={tfInput}
            onChange={e => setTfInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { commitTfInput(); }
              if (e.key === 'Escape') { setShowInput(false); setTfInput(''); }
            }}
            onBlur={commitTfInput}
            placeholder="5m…"
            className="w-[40px] text-[10px] bg-[#1E222D] border border-[#2962FF60] rounded px-1 py-0.5 text-white outline-none"
          />
        )}
        {activeIndicators.map((ind, i) => {
          const isCb = ind.type === 'consolidationBoxes';
          const isNb = ind.type === 'neuralBoxes';
          const color = isNb ? '#29B6F6' : (isCb ? '#2962FF' : '#27a7b0');
          const title = isNb ? 'Neural Boxes' : (isCb ? 'Consolidation Boxes' : ind.type === 'swingLevels' ? 'Swing Levels' : ind.type);
          const label = isNb ? 'NB' : (isCb ? 'CB' : ind.type === 'swingLevels' ? 'SL' : 'IN');
          
          return (
            <span
              key={ind.id || i}
              className={`text-[4px] font-bold px-1 py-0.5 rounded leading-none uppercase transition-opacity ${
                ind.enabled ? 'opacity-100' : 'opacity-40'
              }`}
              style={{ backgroundColor: `${color}20`, color, border: `1px solid ${color}40` }}
              title={`${title} – ${ind.enabled ? 'visible' : 'hidden'}`}
            >
              {label}
            </span>
          );
        })}
      </div>
    );
  };

  const renderChart = (idx) => {
    const pane = panes[idx] || { ...panes[0], timeframe: panes[0].timeframe };
    const effectivePane = { ...pane, symbol: symbol, indicators: pane.indicators || [] };
    const isMain = idx === 0;
    const cRef = isMain ? chartWidgetRef : null;
    const panePrecision = getSymbolPrecision(symbol);
    const swingSettings = getSwingSettings(effectivePane);
    const consolidationSettings = getConsolidationSettings(effectivePane);
    const neuralSettings = getNeuralSettings(effectivePane);
    return (
      <div
        key={`pane-${idx}-${effectivePane.timeframe}-${symbol}`}
        className={`h-full w-full relative border border-[#2A2E39] ${
          activePaneIdx === idx && activeLayout !== '1' ? 'ring-1 ring-[#2962FF60]' : ''
        }`}
        onClick={() => setActivePaneIdx(idx)}
      >
        <ChartWidget
          ref={cRef}
          symbol={symbol}
          timeframe={effectivePane.timeframe}
          chartType={isMain ? chartType : effectivePane.chartType}
          onPriceUpdate={isMain ? handlePriceUpdate : undefined}
          logScale={logScale}
          chartSettings={chartSettings}
          refreshKey={refreshKey}
          symbolPrecision={panePrecision}
          swingSettings={swingSettings}
          consolidationSettings={consolidationSettings}
          neuralSettings={neuralSettings}
          liveTickKey={liveTickKey}
          aiMode={showML}
          nnMode={showNN}
          pmMode={showPM}
          paneIndex={idx}
          sharedConsolidations={sharedConsolidations}
          sharedSwings={sharedSwings}
          sharedAutoLabels={sharedAutoLabels}
          sharedNNZones={sharedNNZones}
        />
        {/* Show mini toolbar for every pane in multi-layout */}
        {activeLayout !== '1' && (
          <PaneMiniToolbar pane={effectivePane} idx={idx} />
        )}
      </div>
    );
  };

  const getLayoutCharts = () => {
    const lgKey = `${activeLayout}-${layoutResetKey}`;
    switch (activeLayout) {
      case '2h': return (
        <PanelGroup key={lgKey} direction="horizontal" className="flex-1">
          <Panel defaultSize={50} minSize={20}>{renderChart(0)}</Panel>
          <ResizeHandle direction="horizontal" onDoubleClick={handleResetLayout} />
          <Panel defaultSize={50} minSize={20}>{renderChart(1)}</Panel>
        </PanelGroup>
      );
      case '2v': return (
        <PanelGroup key={lgKey} direction="vertical" className="flex-1">
          <Panel defaultSize={50} minSize={20}>{renderChart(0)}</Panel>
          <ResizeHandle direction="vertical" onDoubleClick={handleResetLayout} />
          <Panel defaultSize={50} minSize={20}>{renderChart(1)}</Panel>
        </PanelGroup>
      );
      case '4': return (
        <PanelGroup key={lgKey} direction="vertical" className="flex-1">
          <Panel defaultSize={50} minSize={15}>
            <PanelGroup direction="horizontal">
              <Panel defaultSize={50} minSize={15}>{renderChart(0)}</Panel>
              <ResizeHandle direction="horizontal" onDoubleClick={handleResetLayout} />
              <Panel defaultSize={50} minSize={15}>{renderChart(1)}</Panel>
            </PanelGroup>
          </Panel>
          <ResizeHandle direction="vertical" onDoubleClick={handleResetLayout} />
          <Panel defaultSize={50} minSize={15}>
            <PanelGroup direction="horizontal">
              <Panel defaultSize={50} minSize={15}>{renderChart(2)}</Panel>
              <ResizeHandle direction="horizontal" onDoubleClick={handleResetLayout} />
              <Panel defaultSize={50} minSize={15}>{renderChart(3)}</Panel>
            </PanelGroup>
          </Panel>
        </PanelGroup>
      );
      case '3r': return (
        <PanelGroup key={lgKey} direction="horizontal" className="flex-1">
          <Panel defaultSize={65} minSize={25}>{renderChart(0)}</Panel>
          <ResizeHandle direction="horizontal" onDoubleClick={handleResetLayout} />
          <Panel defaultSize={35} minSize={15}>
            <PanelGroup direction="vertical">
              <Panel defaultSize={50} minSize={20}>{renderChart(1)}</Panel>
              <ResizeHandle direction="vertical" onDoubleClick={handleResetLayout} />
              <Panel defaultSize={50} minSize={20}>{renderChart(2)}</Panel>
            </PanelGroup>
          </Panel>
        </PanelGroup>
      );
      default: return (
        <div className="flex-1 relative min-w-0">
          <ChartWidget
            ref={chartWidgetRef}
            key={`main-${symbol}`}
            symbol={symbol}
            timeframe={timeframe}
            chartType={chartType}
            onPriceUpdate={handlePriceUpdate}
            logScale={logScale}
            chartSettings={chartSettings}
            refreshKey={refreshKey}
            symbolPrecision={symbolPrecision}
            swingSettings={getSwingSettings(panes[0] || {})}
            consolidationSettings={getConsolidationSettings(panes[0] || {})}
            neuralSettings={getNeuralSettings(panes[0] || {})}
            liveTickKey={liveTickKey}
            aiMode={showML}
            nnMode={showNN}
            pmMode={showPM}
            paneIndex={0}
            sharedConsolidations={sharedConsolidations}
            sharedSwings={sharedSwings}
            sharedAutoLabels={sharedAutoLabels}
            sharedNNZones={sharedNNZones}
          />
        </div>
      );
    }
  };

  return (
    <div ref={containerRef} className="h-screen w-screen bg-[#000000] flex flex-col overflow-hidden select-none">

      {/* Keyboard buffer HUD – shows what keys have been typed so far */}
      {kbBuffer && (
        <div className="fixed bottom-10 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#1E222D] border border-[#2962FF60] shadow-2xl">
          <span className="text-[10px] text-[#787B86] uppercase tracking-widest">Timeframe</span>
          <span className="text-[14px] font-mono font-bold text-[#2962FF]">{kbBuffer}</span>
          <span className="text-[10px] text-[#4A4E59]">↵ to apply</span>
        </div>
      )}

      <ChartToolbar
        symbol={symbol}
        timeframe={timeframe}
        onTimeframeChange={setTimeframe}
        chartType={chartType}
        onChartTypeChange={setChartType}
        priceData={priceData}
        symbolPrecision={symbolPrecision}
        onFullscreen={handleFullscreen}
        onSettings={() => setShowSettings(true)}
        onRefresh={handleRefresh}
        activeLayout={activeLayout}
        onLayoutChange={setActiveLayout}
        showLayout={showLayout}
        onToggleLayout={() => setShowLayout(prev => !prev)}
        showIndicators={showIndicators}
        onToggleIndicators={() => setShowIndicators(prev => !prev)}
        countdown={countdown}
        panes={panes}
        aiMode={showML}
        onToggleML={() => setShowML(prev => !prev)}
        nnMode={showNN}
        onToggleNN={() => setShowNN(prev => !prev)}
        pmMode={showPM}
        onTogglePM={() => setShowPM(prev => !prev)}
      />


      <div className="flex flex-1 overflow-hidden min-w-0">
        <ForexPairSidebar
          activeSymbol={symbol}
          onSymbolChange={handleSymbolChange}
        />
        <div className="flex flex-1 overflow-hidden min-w-0">
          {getLayoutCharts()}
        </div>
      </div>

      <div className="h-[26px] bg-[#000000] border-t border-[#2A2E39] flex items-center px-2 justify-between shrink-0">
        <div className="flex items-center gap-1">
          {['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y', 'All'].map((r) => (
            <button key={r} onClick={() => handleBottomRange(r === 'All' ? 'all' : r)}
              className="px-1.5 py-0.5 text-[10px] text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#2A2E3960] rounded transition-colors">{r}</button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-[#787B86]">
          <span>{new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} UTC</span>
          <div className="w-px h-3 bg-[#2A2E39]" />
          <button onClick={() => chartWidgetRef.current?.fitContent()} className="hover:text-[#D1D4DC] transition-colors">Auto</button>
          <button onClick={() => { setLogScale(prev => !prev); showToast(logScale ? 'Linear scale' : 'Log scale'); }}
            className={`transition-colors ${logScale ? 'text-[#2962FF]' : 'hover:text-[#D1D4DC]'}`}>Log</button>
          <button className="hover:text-[#D1D4DC] transition-colors">ADJ</button>
        </div>
      </div>

      {showSettings && (
        <SettingsPanel settings={chartSettings} onSettingsChange={setChartSettings} onClose={() => setShowSettings(false)} />
      )}

      {showIndicators && (
        <IndicatorPanel
          activeLayout={activeLayout}
          panes={panes}
          activePaneIdx={activePaneIdx}
          onUpdatePane={updatePane}
          onClose={() => setShowIndicators(false)}
        />
      )}


      {toastMsg && (
        <div className="fixed bottom-16 left-1/2 -translate-x-1/2 z-50 px-4 py-2 bg-[#363A45] text-white text-[12px] rounded-lg shadow-xl border border-[#4A4E59] animate-fade-in">
          {toastMsg}
        </div>
      )}
    </div>
  );
};

export default ChartPage;
