import { renderConsolidation } from './ConsolidationRenderer';

export const renderEngine = (canvas, ctx, data, layers, camera) => {
  if (!ctx) return;

  // 1. Clear with deep dark background
  ctx.fillStyle = '#0b0e14';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // 2. Draw Grid (Spatial reference)
  drawSpatialGrid(ctx, canvas, camera);

  if (!data) return;

  // 3. Render each timeframe as a vertical "lane" or layer
  const tfs = ['4H', '1H', '15m', '5m', '1m'];
  
  tfs.forEach((tf, index) => {
    if (!layers[tf]) return;
    
    const tfData = data[tf];
    if (!tfData) return;

    // Determine vertical offset for this timeframe's lane
    const laneOffset = index * 800; // 800 pixels per lane in world space
    
    renderTimeframe(ctx, tf, tfData, camera, laneOffset);
  });
};

const drawSpatialGrid = (ctx, canvas, camera) => {
  const gridSize = 100 * camera.zoom;
  const offsetX = camera.x % gridSize;
  const offsetY = camera.y % gridSize;

  ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
  ctx.lineWidth = 1;

  ctx.beginPath();
  for (let x = offsetX; x < canvas.width; x += gridSize) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
  }
  for (let y = offsetY; y < canvas.height; y += gridSize) {
    ctx.moveTo(0, y);
    ctx.lineTo(canvas.width, y);
  }
  ctx.stroke();
};

const renderTimeframe = (ctx, tf, tfData, camera, laneOffset) => {
  const { candles, scenarios } = tfData;
  if (!candles || candles.length === 0) return;

  // Opacity and thickness based on timeframe
  const isHTF = tf === '4H' || tf === '1H';
  const opacity = isHTF ? 0.2 : 0.8;
  const lineWidth = isHTF ? 4 : 1.5;

  // Local World -> Screen transform helper
  const toScreenX = (timestamp, firstTs) => {
    const worldX = (timestamp - firstTs) / 10000; // Scale time
    return (worldX * camera.zoom) + camera.x;
  };
  
  const toScreenY = (price, minPrice, maxPrice) => {
    const range = maxPrice - minPrice || 1;
    const worldY = laneOffset + (1 - (price - minPrice) / range) * 400;
    return (worldY * camera.zoom) + camera.y;
  };

  // Find price bounds for this lane
  const prices = candles.map(c => [c.high, c.low]).flat();
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const firstTs = candles[0].timestamp;

  // Draw Consolidation Box
  renderConsolidation(ctx, candles, minPrice, maxPrice, (ts) => toScreenX(ts, firstTs), (p, minP, maxP) => toScreenY(p, minP, maxP));

  // Draw Price Action (Line Chart for clean forks)
  ctx.beginPath();
  ctx.strokeStyle = `rgba(226, 232, 240, ${opacity})`;
  ctx.lineWidth = lineWidth;
  
  candles.forEach((c, i) => {
    const sx = toScreenX(c.timestamp, firstTs);
    const sy = toScreenY(c.close, minPrice, maxPrice);
    if (i === 0) ctx.moveTo(sx, sy);
    else ctx.lineTo(sx, sy);
  });
  ctx.stroke();

  // Draw Scenarios (Forks)
  const lastCandle = candles[candles.length - 1];
  const startX = toScreenX(lastCandle.timestamp, firstTs);
  const startY = toScreenY(lastCandle.close, minPrice, maxPrice);

  scenarios.forEach(s => {
    if (s.type === 'none') return;

    // Draw SL Line
    const slY = toScreenY(s.sl, minPrice, maxPrice);
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)'; // Red
    ctx.setLineDash([5, 5]);
    ctx.moveTo(startX - 100 * camera.zoom, slY);
    ctx.lineTo(startX + 500 * camera.zoom, slY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw TP Zone (Rectangle)
    const tpTop = toScreenY(s.tp_zone.high, minPrice, maxPrice);
    const tpBot = toScreenY(s.tp_zone.low, minPrice, maxPrice);
    ctx.fillStyle = 'rgba(34, 197, 94, 0.1)'; // Green
    ctx.fillRect(startX, Math.min(tpTop, tpBot), 500 * camera.zoom, Math.abs(tpTop - tpBot));

    // Draw Fork Path
    ctx.beginPath();
    ctx.strokeStyle = s.type === 'buy' ? '#22c55e' : '#ef4444';
    ctx.lineWidth = lineWidth * 2;
    ctx.moveTo(startX, startY);

    if (s.path && s.path.length > 0) {
      s.path.forEach((p, i) => {
        // Path nodes are projected forward in time
        const px = startX + (i + 1) * (100 * camera.zoom); 
        const py = toScreenY(p[1], minPrice, maxPrice);
        ctx.lineTo(px, py);
      });
    }
    
    // Glow effect for forks
    ctx.shadowBlur = 10;
    ctx.shadowColor = ctx.strokeStyle;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Entry Point
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(startX, startY, 3 * camera.zoom, 0, Math.PI * 2);
    ctx.fill();
  });
};
