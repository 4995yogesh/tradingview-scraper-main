import { useState, useEffect } from 'react';
import ChartCanvas from './components/ChartCanvas';
import LayerController from './components/LayerController';

function App() {
  const [data, setData] = useState(null);
  const [layers, setLayers] = useState({
    '4H': true,
    '1H': true,
    '15m': true,
    '5m': true,
    '1m': true
  });

  // Poll Engine
  useEffect(() => {
    let timeoutId;
    const fetchData = async () => {
      try {
        const res = await fetch('http://localhost:8001/scenarios');
        if (res.ok) {
          const json = await res.json();
          setData(json);
        }
      } catch (err) {
        console.warn("API poll failed", err);
      }
      timeoutId = setTimeout(fetchData, 5000);
    };
    
    fetchData();
    return () => clearTimeout(timeoutId);
  }, []);

  const toggleLayer = (tf) => {
    setLayers(prev => ({ ...prev, [tf]: !prev[tf] }));
  };

  return (
    <div className="app-container">
      <ChartCanvas data={data} layers={layers} />
      <LayerController layers={layers} onToggle={toggleLayer} />
    </div>
  );
}

export default App;
