export const renderConsolidation = (ctx, candles, minPrice, maxPrice, toScreenX, toScreenY) => {
  if (!candles || candles.length < 5) return;

  // Simple logic: Draw a box around the most recent 10 candles
  const recent = candles.slice(-10);
  const startTs = recent[0].timestamp;
  const endTs = recent[recent.length - 1].timestamp;
  
  const high = Math.max(...recent.map(c => c.high));
  const low = Math.min(...recent.map(c => c.low));

  const xStart = toScreenX(startTs);
  const xEnd = toScreenX(endTs);
  const yHigh = toScreenY(high, minPrice, maxPrice);
  const yLow = toScreenY(low, minPrice, maxPrice);

  ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
  ctx.lineWidth = 1;
  ctx.fillRect(xStart, yHigh, xEnd - xStart, yLow - yHigh);
  ctx.strokeRect(xStart, yHigh, xEnd - xStart, yLow - yHigh);
};
