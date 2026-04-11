import { useState, useEffect } from 'react';
import ChartCanvas from './components/ChartCanvas';
import LayerController from './components/LayerController';
import InfiniteCanvas from './components/InfiniteCanvas';

// ── Simple hash router ───────────────────────────────────────────────────────
function useHash() {
  const [hash, setHash] = useState(window.location.hash || '#main');
  useEffect(() => {
    const onHash = () => setHash(window.location.hash || '#main');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  return hash;
}

// ── Main dashboard (original) ─────────────────────────────────────────────────
function MainDashboard() {
  const [data, setData] = useState(null);
  const [layers, setLayers] = useState({
    '4H': true, '1H': true, '15m': true, '5m': true, '1m': true,
  });

  useEffect(() => {
    let timeoutId;
    const fetchData = async () => {
      try {
        const res = await fetch('http://localhost:8001/scenarios');
        if (res.ok) setData(await res.json());
      } catch (err) {
        console.warn('API poll failed', err);
      }
      timeoutId = setTimeout(fetchData, 5000);
    };
    fetchData();
    return () => clearTimeout(timeoutId);
  }, []);

  const toggleLayer = (tf) =>
    setLayers(prev => ({ ...prev, [tf]: !prev[tf] }));

  return (
    <div className="app-container">
      <ChartCanvas data={data} layers={layers} />
      <LayerController layers={layers} onToggle={toggleLayer} />
      {/* Nav to canvas */}
      <a
        href="#canvas"
        className="nav-btn"
        title="Open Multi-Timeframe Canvas"
      >
        ⬡ Canvas
      </a>
    </div>
  );
}

// ── Root ─────────────────────────────────────────────────────────────────────
function App() {
  const hash = useHash();
  return hash === '#canvas' ? <InfiniteCanvas /> : <MainDashboard />;
}

export default App;
