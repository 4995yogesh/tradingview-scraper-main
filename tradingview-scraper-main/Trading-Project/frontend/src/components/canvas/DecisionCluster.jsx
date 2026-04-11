import React from 'react';
import ChartWidget from '../chart/ChartWidget';
import { useCanvasStore } from '../../hooks/useCanvasStore';

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

  const handlePointerDown = (e) => {
    e.stopPropagation();
    e.preventDefault(); // prevent pan
    const target = e.currentTarget;
    target.setPointerCapture(e.pointerId);

    const startX = e.clientX;
    const startY = e.clientY;
    const initialX = cluster.x;
    const initialY = cluster.y;

    const getScale = () => {
      const wrapper = document.querySelector('.react-transform-component');
      if (!wrapper) return 1;
      const style = window.getComputedStyle(wrapper.firstElementChild);
      if (style.transform && style.transform !== 'none') {
        return parseFloat(style.transform.split('(')[1].split(',')[0]);
      }
      return 1;
    };

    const pointerMove = (ev) => {
      const scale = getScale();
      const dx = (ev.clientX - startX) / (scale || 1);
      const dy = (ev.clientY - startY) / (scale || 1);
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
const STATIC_CHART_SETTINGS = {
  showGrid: true, 
  showBorders: true, 
  showWick: true,
  background: '#131722',
  gridColor: 'rgba(255, 255, 255, 0.05)',
};

function ChartBoxContainer({ node, forkNode, removeFork, cluster }) {
  const boxRef = React.useRef(null);
  const isMain = node.type === 'main';
  
  const w = isMain ? 650 : 375;
  const h = isMain ? 450 : 260;

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
          chartType="candlestick" 
          chartSettings={STATIC_CHART_SETTINGS}
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
