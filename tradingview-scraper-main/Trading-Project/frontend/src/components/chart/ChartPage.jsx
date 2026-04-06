import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useChartMemory } from '../../hooks/useChartMemory';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import ChartWidget from './ChartWidget';
import ChartToolbar from './ChartToolbar';
import SettingsPanel from './SettingsPanel';
import LayoutSelector from './LayoutSelector';

// Auto-refresh interval in seconds
const AUTO_REFRESH_INTERVAL = 60;

// Symbol precision map
const SYMBOL_PRECISION = {
  EURUSD: 5,
};

export function getSymbolPrecision(symbol) {
  return SYMBOL_PRECISION[symbol] ?? 5;
}

const defaultPanes = [
  { symbol: 'EURUSD', timeframe: '1d', chartType: 'candle' },
];

const ChartPage = () => {
  const chartWidgetRef = useRef(null);
  const containerRef = useRef(null);

  // ── Persisted state (auto-saved to localStorage via useChartMemory) ──────────
  const [symbol, setSymbol] = useChartMemory('symbol', 'EURUSD');
  const [timeframe, setTimeframe] = useChartMemory('timeframe', '1d');
  const [chartType, setChartType] = useChartMemory('chartType', 'candle');
  const [panes, setPanes] = useChartMemory('panes', defaultPanes);

  const [logScale, setLogScale] = useChartMemory('logScale', false);
  const [chartSettings, setChartSettings] = useChartMemory('chartSettings', {
    background: '#131722', showGrid: true, crosshairMode: 'normal',
    upColor: '#26A69A', downColor: '#EF5350', timezone: 'exchange',
    sessionBreaks: false, watermark: false,
  });
  const [activeLayout, setActiveLayout] = useChartMemory('activeLayout', '1');

  // ── Transient state (not persisted) ─────────────────────────────────────────
  const [activePaneIdx, setActivePaneIdx] = useState(0);
  const [priceData, setPriceData] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showLayout, setShowLayout] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [toastMsg, setToastMsg] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [countdown, setCountdown] = useState(AUTO_REFRESH_INTERVAL);

  const symbolPrecision = getSymbolPrecision(symbol);

  // ── Countdown synced to real wall-clock minute boundary ──────────────────
  useEffect(() => {
    const getSecondsLeft = () => {
      const secs = new Date().getSeconds();
      return secs === 0 ? 60 : 60 - secs;
    };

    setCountdown(getSecondsLeft());

    const tick = setInterval(() => {
      const left = getSecondsLeft();
      setCountdown(left);
      if (left === 60) {
        setRefreshKey(prev => prev + 1);
      }
    }, 1000);

    return () => clearInterval(tick);
  }, []);

  const showToast = useCallback((msg) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 2500);
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

  // Sync pane 0 with main symbol/timeframe/chartType
  const updatePane = useCallback((idx, key, value) => {
    setPanes(prev => prev.map((p, i) => i === idx ? { ...p, [key]: value } : p));
    if (idx === 0) {
      if (key === 'symbol') setSymbol(value);
      if (key === 'timeframe') setTimeframe(value);
      if (key === 'chartType') setChartType(value);
    }
  }, [setPanes, setSymbol, setTimeframe, setChartType]);

  useEffect(() => {
    setPanes(prev => prev.map((p, i) => i === 0 ? { ...p, symbol, timeframe, chartType } : p));
  }, [symbol, timeframe, chartType, setPanes]);

  const PaneMiniToolbar = ({ pane, idx }) => {
    const [showTf, setShowTf] = useState(false);
    const tfLabels = { '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W', '1M': '1M' };
    return (
      <div className="absolute top-0 left-0 right-0 z-20 flex items-center gap-1 px-2 py-1 bg-[#131722E0] border-b border-[#2A2E39]" onClick={e => e.stopPropagation()}>
        <span className="text-[11px] font-semibold text-white">{pane.symbol}</span>
        <div className="relative">
          <button onClick={() => setShowTf(!showTf)} className="text-[10px] text-[#787B86] hover:text-white bg-[#2A2E39] px-1.5 py-0.5 rounded transition-colors">
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
      </div>
    );
  };

  const renderChart = (idx) => {
    const pane = panes[idx] || panes[0];
    const isMain = idx === 0;
    const cRef = isMain ? chartWidgetRef : null;
    const panePrecision = getSymbolPrecision(pane.symbol);
    return (
      <div key={`pane-${idx}-${pane.symbol}`} className={`h-full w-full relative border border-[#2A2E39] ${activePaneIdx === idx && activeLayout !== '1' ? 'ring-1 ring-[#2962FF40]' : ''}`}
        onClick={() => setActivePaneIdx(idx)}>
        <ChartWidget
          ref={cRef}
          symbol={pane.symbol}
          timeframe={pane.timeframe}
          chartType={isMain ? chartType : pane.chartType}
          onPriceUpdate={isMain ? handlePriceUpdate : undefined}
          logScale={logScale}
          chartSettings={chartSettings}
          refreshKey={refreshKey}
          symbolPrecision={panePrecision}
        />
        {activeLayout !== '1' && idx > 0 && (
          <PaneMiniToolbar pane={pane} idx={idx} />
        )}
      </div>
    );
  };

  const ResizeHandle = ({ direction = 'horizontal' }) => (
    <PanelResizeHandle className={`group relative flex items-center justify-center ${
      direction === 'horizontal' ? 'w-[5px] cursor-col-resize' : 'h-[5px] cursor-row-resize'
    } bg-[#2A2E39] hover:bg-[#2962FF60] active:bg-[#2962FF] transition-colors`}>
      <div className={`${
        direction === 'horizontal' ? 'w-[3px] h-8' : 'h-[3px] w-8'
      } rounded-full bg-[#363A45] group-hover:bg-[#2962FF] transition-colors`} />
    </PanelResizeHandle>
  );

  const getLayoutCharts = () => {
    switch (activeLayout) {
      case '2h': return (
        <PanelGroup direction="horizontal" className="flex-1">
          <Panel defaultSize={50} minSize={20}>{renderChart(0)}</Panel>
          <ResizeHandle direction="horizontal" />
          <Panel defaultSize={50} minSize={20}>{renderChart(1)}</Panel>
        </PanelGroup>
      );
      case '2v': return (
        <PanelGroup direction="vertical" className="flex-1">
          <Panel defaultSize={50} minSize={20}>{renderChart(0)}</Panel>
          <ResizeHandle direction="vertical" />
          <Panel defaultSize={50} minSize={20}>{renderChart(1)}</Panel>
        </PanelGroup>
      );
      case '4': return (
        <PanelGroup direction="vertical" className="flex-1">
          <Panel defaultSize={50} minSize={15}>
            <PanelGroup direction="horizontal">
              <Panel defaultSize={50} minSize={15}>{renderChart(0)}</Panel>
              <ResizeHandle direction="horizontal" />
              <Panel defaultSize={50} minSize={15}>{renderChart(1)}</Panel>
            </PanelGroup>
          </Panel>
          <ResizeHandle direction="vertical" />
          <Panel defaultSize={50} minSize={15}>
            <PanelGroup direction="horizontal">
              <Panel defaultSize={50} minSize={15}>{renderChart(2)}</Panel>
              <ResizeHandle direction="horizontal" />
              <Panel defaultSize={50} minSize={15}>{renderChart(3)}</Panel>
            </PanelGroup>
          </Panel>
        </PanelGroup>
      );
      case '3r': return (
        <PanelGroup direction="horizontal" className="flex-1">
          <Panel defaultSize={65} minSize={25}>{renderChart(0)}</Panel>
          <ResizeHandle direction="horizontal" />
          <Panel defaultSize={35} minSize={15}>
            <PanelGroup direction="vertical">
              <Panel defaultSize={50} minSize={20}>{renderChart(1)}</Panel>
              <ResizeHandle direction="vertical" />
              <Panel defaultSize={50} minSize={20}>{renderChart(2)}</Panel>
            </PanelGroup>
          </Panel>
        </PanelGroup>
      );
      default: return (
        <div className="flex-1 relative min-w-0">
          <ChartWidget
            ref={chartWidgetRef}
            symbol={symbol}
            timeframe={timeframe}
            chartType={chartType}
            onPriceUpdate={handlePriceUpdate}
            logScale={logScale}
            chartSettings={chartSettings}
            refreshKey={refreshKey}
            symbolPrecision={symbolPrecision}
          />
        </div>
      );
    }
  };

  return (
    <div ref={containerRef} className="h-screen w-screen bg-[#131722] flex flex-col overflow-hidden select-none">
      <div
        className="fixed top-2 right-4 z-50 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#1E222D] border border-[#363A45] shadow-lg select-none"
        title="Next candle close"
      >
        <div
          className="w-1.5 h-1.5 rounded-full bg-[#787B86]"
          style={{ animation: 'pulse 2s ease-in-out infinite' }}
        />
        <span className="text-[11px] font-mono text-[#787B86]">
          {String(countdown).padStart(2, '0')}s
        </span>
      </div>

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
      />

      <div className="flex flex-1 overflow-hidden">
        {getLayoutCharts()}
      </div>

      <div className="h-[26px] bg-[#131722] border-t border-[#2A2E39] flex items-center px-2 justify-between shrink-0">
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

      {toastMsg && (
        <div className="fixed bottom-16 left-1/2 -translate-x-1/2 z-50 px-4 py-2 bg-[#363A45] text-white text-[12px] rounded-lg shadow-xl border border-[#4A4E59] animate-fade-in">
          {toastMsg}
        </div>
      )}
    </div>
  );
};

export default ChartPage;
