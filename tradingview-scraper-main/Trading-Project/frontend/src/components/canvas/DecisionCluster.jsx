import React, { useState, useEffect } from 'react';
import ChartWidget from '../chart/ChartWidget';
import { useCanvasStore } from '../../hooks/useCanvasStore';
import { useTransformContext } from 'react-zoom-pan-pinch';
import { useChartMemory } from '../../hooks/useChartMemory';

const BIAS_COLORS = {
  base: '#3B82F6',   // Blue
  bullish: '#10B981', // Green
  bearish: '#EF4444', // Red
  trap: '#F59E0B',    // Amber
};

export default function DecisionCluster({ cluster }) {
  const allNodes = useCanvasStore(state => state.nodes);
  const nodes = allNodes.filter(n => n.clusterId === cluster.id);
  const forkNode = useCanvasStore(state => state.forkNode);
  const removeFork = useCanvasStore(state => state.removeFork);
  const setClusterPosition = useCanvasStore(state => state.setClusterPosition);

  const mainNode = nodes.find(n => n.type === 'main');

  // Read live canvas scale from react-zoom-pan-pinch context
  const { transformState } = useTransformContext();

  // Live tick: increment every 30s so canvas charts auto-update
  const [liveTickKey, setLiveTickKey] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setLiveTickKey(k => k + 1), 30000);
    return () => clearInterval(id);
  }, []);

  const handlePointerDown = (e) => {
    e.stopPropagation();
    e.preventDefault();
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);

    const startX = e.clientX;
    const startY = e.clientY;
    const initialX = cluster.x;
    const initialY = cluster.y;

    const pointerMove = (ev) => {
      const scale = transformState.scale || 1;
      const dx = (ev.clientX - startX) / scale;
      const dy = (ev.clientY - startY) / scale;
      setClusterPosition(cluster.id, initialX + dx, initialY + dy);
    };

    const pointerUp = (ev) => {
      target.releasePointerCapture(ev.pointerId);
      target.removeEventListener('pointermove', pointerMove);
      target.removeEventListener('pointerup', pointerUp);
    };

    target.addEventListener('pointermove', pointerMove);
    target.addEventListener('pointerup', pointerUp);
  };

  return (
    <div style={{ position: 'absolute', left: cluster.x, top: cluster.y }}>
      
      {/* Cluster Header (Draggable Handle) */}
      <div 
        onPointerDown={handlePointerDown}
        style={{ position: 'absolute', top: -50, left: 0, fontSize: 32, fontWeight: 900, color: 'rgba(255,255,255,0.4)', cursor: 'grab', userSelect: 'none' }}
      >
        {cluster.tf.toUpperCase()} Context <span style={{ fontSize: 14, fontWeight: 400, color: '#4a90d9', verticalAlign: 'middle', marginLeft: 12 }}>⋮⋮ drag</span>
      </div>

      {nodes.map(node => (
        <ChartBoxContainer 
          key={node.id} 
          node={node} 
          forkNode={forkNode} 
          removeFork={removeFork} 
          cluster={cluster} 
          liveTickKey={liveTickKey}
        />
      ))}

      {/* Connection Lines (SVGs overlay within the cluster) */}
      <svg style={{ position: 'absolute', top: 0, left: 0, width: 2000, height: 2000, pointerEvents: 'none', zIndex: -1 }}>
        {mainNode && nodes.filter(n => n.type === 'fork').map(fork => {
          // Draw bezier curve from main node right edge to fork node left edge
          const startX = mainNode.relX + 650;
          const startY = mainNode.relY + 225;
          const endX = fork.relX;
          const endY = fork.relY + 130; // Half of 260px height
          
          return (
            <path 
              key={`link-${fork.id}`}
              d={`M ${startX} ${startY} C ${startX + 150} ${startY}, ${endX - 150} ${endY}, ${endX} ${endY}`}
              fill="none"
              stroke={BIAS_COLORS[fork.bias]}
              strokeWidth="3"
              strokeOpacity="0.5"
            />
          );
        })}
      </svg>
    </div>
  );
}

// Sub-component to natively stop wheel propagation
const DEFAULT_CHART_SETTINGS = {
  background: '#131722', showGrid: true, crosshairMode: 'normal',
  upColor: '#26A69A', downColor: '#EF5350', timezone: 'exchange',
  sessionBreaks: false, watermark: false,
};

function ChartBoxContainer({ node, forkNode, removeFork, cluster, liveTickKey }) {
  const boxRef = React.useRef(null);
  const isMain = node.type === 'main';
  
  const w = isMain ? 650 : 375;
  const h = isMain ? 450 : 260;

  // Read style and indicators from the "main chart" adjustment page (pane 0)
  const [chartSettings] = useChartMemory('chartSettings', DEFAULT_CHART_SETTINGS);
  const [chartType] = useChartMemory('chartType', 'hollow');
  const [panes] = useChartMemory('panes', []);
  
  const mainPane = panes[0] || {};
  const indicators = mainPane.indicators || [];
  
  const swingSettings = React.useMemo(() => {
    const ind = indicators.find(i => i.type === 'swingLevels');
    if (!ind) return null;
    return { enabled: ind.enabled, settings: ind.settings };
  }, [indicators]);

  const consolidationSettings = React.useMemo(() => {
    const ind = indicators.find(i => i.type === 'consolidationBoxes');
    if (!ind) return null;
    return { enabled: ind.enabled, settings: ind.settings };
  }, [indicators]);

  React.useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const blockWheel = (e) => { e.stopPropagation(); };
    el.addEventListener('wheel', blockWheel, { passive: false });
    return () => el.removeEventListener('wheel', blockWheel);
  }, []);

  return (
    <div
      ref={boxRef}
      className="chart-box"
      style={{
        position: 'absolute',
        left: node.relX,
        top: node.relY,
        width: w, 
        height: h,
        background: '#0d0f17',
        border: `2px solid ${BIAS_COLORS[node.bias]}88`,
        borderRadius: isMain ? 8 : 6,
        boxShadow: `0 0 20px ${BIAS_COLORS[node.bias]}15`,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      {/* Toolbar */}
      <div style={{ 
        padding: isMain ? '8px 12px' : '4px 8px', 
        background: 'rgba(0,0,0,0.4)', 
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', gap: isMain ? 8 : 4, alignItems: 'center' }}>
          <span style={{ color: BIAS_COLORS[node.bias], fontWeight: 'bold', fontSize: isMain ? 13 : 9, textTransform: 'uppercase' }}>
            {node.bias} {isMain ? 'CHART' : 'PATH'}
          </span>
          <span style={{ color: '#fff', fontSize: isMain ? 12 : 8, fontWeight: 800, background: '#ffffff22', padding: isMain ? '2px 6px' : '1px 4px', borderRadius: 3 }}>
            {cluster.tf}
          </span>
        </div>

        <div style={{ display: 'flex', gap: isMain ? 6 : 3 }}>
          {isMain ? (
            <>
              <button onClick={() => forkNode(cluster.id, node.id, 'bullish')} style={btnStyle(BIAS_COLORS.bullish, isMain)}>+ Bullish</button>
              <button onClick={() => forkNode(cluster.id, node.id, 'bearish')} style={btnStyle(BIAS_COLORS.bearish, isMain)}>+ Bearish</button>
              <button onClick={() => forkNode(cluster.id, node.id, 'trap')} style={btnStyle(BIAS_COLORS.trap, isMain)}>+ Trap</button>
            </>
          ) : (
            <button onClick={() => removeFork(node.id)} style={btnStyle('#EF4444', isMain)}>✕ Remove</button>
          )}
        </div>
      </div>

      {/* Actual Chart */}
      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        <ChartWidget 
          symbol="EURUSD" 
          timeframe={cluster.tf} 
          chartType={chartType} 
          chartSettings={chartSettings}
          swingSettings={swingSettings}
          consolidationSettings={consolidationSettings}
          isSubchart={!isMain}
          liveTickKey={liveTickKey}
          initialBars={isMain ? 60 : 30}
        />
      </div>
      
    </div>
  );
}

function btnStyle(color, isMain = true) {
  return {
    background: `${color}22`,
    border: `1px solid ${color}55`,
    color: '#fff',
    fontSize: isMain ? 10 : 7,
    fontWeight: 'bold',
    padding: isMain ? '4px 8px' : '2px 5px',
    borderRadius: isMain ? 4 : 3,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  };
}
