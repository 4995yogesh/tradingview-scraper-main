/**
 * CandleRenderer.js
 * Pure canvas candlestick chart renderer.
 * Expects data = { candleData: [{time, open, high, low, close}], volumeData: [{time, value, color}] }
 */

export function renderCandleChart(canvas, ctx, data, label, camera) {
  if (!ctx) return;

  const W = canvas.width;
  const H = canvas.height;

  // Background
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0, 0, W, H);

  // Grid
  drawGrid(ctx, W, H);

  // Label (timeframe)
  drawLabel(ctx, label, W);

  if (!data || !data.candleData || data.candleData.length === 0) {
    drawLoading(ctx, W, H);
    return;
  }

  const candles = data.candleData;
  const totalCandles = candles.length;

  // Chart area (leave margin)
  const marginLeft = 8;
  const marginRight = 60; // space for price axis
  const marginTop = 36;
  const marginBottom = 50;
  const chartW = W - marginLeft - marginRight;
  const chartH = H - marginTop - marginBottom;

  // Camera: x = pan offset (pixels), zoom = bar width multiplier
  const baseBarW = Math.max(1, chartW / totalCandles);
  const barW = baseBarW * camera.zoom;
  const visibleBars = Math.ceil(chartW / barW);
  const startIdx = Math.max(0, Math.floor(-camera.x / barW));
  const endIdx = Math.min(totalCandles - 1, startIdx + visibleBars + 1);

  // Price range of visible candles
  const visible = candles.slice(startIdx, endIdx + 1);
  if (visible.length === 0) return;
  const highs = visible.map(c => c.high);
  const lows = visible.map(c => c.low);
  const maxP = Math.max(...highs);
  const minP = Math.min(...lows);
  const priceRange = maxP - minP || 0.0001;
  const pricePad = priceRange * 0.05;

  const toX = (i) => marginLeft + camera.x + i * barW;
  const toY = (price) =>
    marginTop + chartH - ((price - (minP - pricePad)) / (priceRange + pricePad * 2)) * chartH;

  // Draw candles
  for (let i = startIdx; i <= endIdx; i++) {
    const c = candles[i];
    const x = toX(i);
    if (x + barW < marginLeft || x > W - marginRight) continue;

    const bull = c.close >= c.open;
    const color = bull ? '#26a69a' : '#ef5350';
    const bodyTop = toY(Math.max(c.open, c.close));
    const bodyBot = toY(Math.min(c.open, c.close));
    const bodyH = Math.max(1, bodyBot - bodyTop);
    const cx = x + barW / 2;

    // Wick
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, toY(c.high));
    ctx.lineTo(cx, toY(c.low));
    ctx.stroke();

    // Body
    ctx.fillStyle = color;
    ctx.fillRect(x + barW * 0.1, bodyTop, barW * 0.8, bodyH);
  }

  // Price axis labels (right side)
  drawPriceAxis(ctx, W, marginRight, marginTop, chartH, minP - pricePad, maxP + pricePad);

  // Volume bars (bottom strip)
  if (data.volumeData && data.volumeData.length > 0) {
    drawVolume(ctx, data.volumeData, startIdx, endIdx, toX, barW, H, marginBottom, chartH);
  }

  // Crosshair label at bottom
  drawTimeAxis(ctx, candles, startIdx, endIdx, toX, barW, H, marginBottom);
}

function drawGrid(ctx, W, H) {
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 1;
  const rows = 6, cols = 8;
  ctx.beginPath();
  for (let i = 1; i < rows; i++) {
    const y = (H / rows) * i;
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
  }
  for (let i = 1; i < cols; i++) {
    const x = (W / cols) * i;
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
  }
  ctx.stroke();
}

function drawLabel(ctx, label, W) {
  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  ctx.fillRect(8, 6, 60, 24);
  ctx.fillStyle = '#94a3b8';
  ctx.font = 'bold 12px Inter, sans-serif';
  ctx.fillText(label, 16, 22);
}

function drawLoading(ctx, W, H) {
  ctx.fillStyle = 'rgba(148,163,184,0.4)';
  ctx.font = '13px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Loading…', W / 2, H / 2);
  ctx.textAlign = 'left';
}

function drawPriceAxis(ctx, W, marginRight, marginTop, chartH, minP, maxP) {
  const steps = 5;
  const priceRange = maxP - minP;
  ctx.fillStyle = 'rgba(148,163,184,0.7)';
  ctx.font = '10px Inter, monospace';
  for (let i = 0; i <= steps; i++) {
    const price = minP + (priceRange * i) / steps;
    const y = marginTop + chartH - (chartH * i) / steps;
    ctx.fillText(price.toFixed(5), W - marginRight + 4, y + 4);
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W - marginRight, y);
    ctx.stroke();
  }
}

function drawVolume(ctx, volumeData, startIdx, endIdx, toX, barW, H, marginBottom, chartH) {
  const volH = marginBottom * 0.65;
  const maxVol = Math.max(...volumeData.slice(startIdx, endIdx + 1).map(v => v.value)) || 1;
  for (let i = startIdx; i <= endIdx; i++) {
    const v = volumeData[i];
    if (!v) continue;
    const x = toX(i);
    const barHeight = (v.value / maxVol) * volH;
    ctx.fillStyle = v.color || 'rgba(148,163,184,0.3)';
    ctx.fillRect(x + barW * 0.1, H - marginBottom + (marginBottom - volH), barW * 0.8, barHeight);
  }
}

function drawTimeAxis(ctx, candles, startIdx, endIdx, toX, barW, H, marginBottom) {
  ctx.fillStyle = 'rgba(148,163,184,0.5)';
  ctx.font = '9px Inter, monospace';
  const step = Math.max(1, Math.floor((endIdx - startIdx) / 6));
  for (let i = startIdx; i <= endIdx; i += step) {
    const c = candles[i];
    if (!c) continue;
    const x = toX(i) + barW / 2;
    const label = typeof c.time === 'number'
      ? new Date(c.time * 1000).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
      : String(c.time).slice(0, 10);
    ctx.fillText(label, x - 20, H - marginBottom + 14);
  }
}
