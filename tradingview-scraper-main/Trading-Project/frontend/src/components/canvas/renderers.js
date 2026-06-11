import { worldToCanvas, COLORS, hexAlpha } from './canvasUtils';

// ── Grid & axes ──────────────────────────────────────────────────────────────
// Batch all vertical lines into one path, horizontal lines into another.
// Was: one beginPath/stroke per line → now: one stroke per axis.
export function drawGrid(ctx, viewport) {
  const { timeMin, timeMax, priceMin, priceMax, width, height } = viewport;

  // Background
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, width, height);

  const timeRange  = timeMax  - timeMin;
  const priceRange = priceMax - priceMin;
  const timeStep   = getTimeStep(timeRange);
  const priceStep  = getPriceStep(priceRange);
  const firstTime  = Math.ceil(timeMin  / timeStep)  * timeStep;
  const firstPrice = Math.ceil(priceMin / priceStep) * priceStep;

  ctx.strokeStyle = COLORS.gridLine;
  ctx.lineWidth   = 0.5;

  // ── Single batched path for all vertical lines ───────────────────────────
  ctx.beginPath();
  for (let t = firstTime; t <= timeMax; t += timeStep) {
    const { x } = worldToCanvas(t, priceMin, viewport);
    if (x < 0 || x > width) continue;
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
  }
  ctx.stroke();

  // ── Single batched path for all horizontal lines ─────────────────────────
  ctx.beginPath();
  for (let p = firstPrice; p <= priceMax; p += priceStep) {
    const { y } = worldToCanvas(timeMin, p, viewport);
    if (y < 0 || y > height) continue;
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
  }
  ctx.stroke();

  // ── Price labels (right axis) ────────────────────────────────────────────
  ctx.fillStyle  = '#3a4160';
  ctx.font       = '10px Inter, sans-serif';
  ctx.textAlign  = 'right';
  for (let p = firstPrice; p <= priceMax; p += priceStep) {
    const { y } = worldToCanvas(timeMin, p, viewport);
    if (y < 0 || y > height) continue;
    ctx.fillText(p.toFixed(4), width - 4, y - 3);
  }
}

// ── Candles ──────────────────────────────────────────────────────────────────
export function drawCandles(ctx, candles, viewport) {
  const { timeMin, timeMax, width } = viewport;
  if (!candles.length) return;

  // Count visible candles in one pass — avoid filter() allocation
  let visible = 0;
  for (const c of candles) {
    if (c.time >= timeMin && c.time <= timeMax) visible++;
  }
  const candleW = Math.max(1, Math.min(12, (width / Math.max(visible, 1)) * 0.6));
  const wickW   = Math.max(0.5, candleW * 0.15);

  for (const candle of candles) {
    if (candle.time < timeMin || candle.time > timeMax) continue;

    const isBull = candle.close >= candle.open;
    const color  = isBull ? COLORS.candleUp : COLORS.candleDown;

    const { x,  y: yHigh  } = worldToCanvas(candle.time, candle.high,  viewport);
    const { y: yLow   }     = worldToCanvas(candle.time, candle.low,   viewport);
    const { y: yOpen  }     = worldToCanvas(candle.time, candle.open,  viewport);
    const { y: yClose }     = worldToCanvas(candle.time, candle.close, viewport);

    const bodyTop = Math.min(yOpen, yClose);
    const bodyH   = Math.max(1, Math.abs(yOpen - yClose));
    const bodyBottom = bodyTop + bodyH;

    // Wick
    ctx.strokeStyle = color;
    ctx.lineWidth   = wickW;
    ctx.beginPath();
    // Top wick
    ctx.moveTo(x, yHigh);
    ctx.lineTo(x, bodyTop);
    // Bottom wick
    ctx.moveTo(x, bodyBottom);
    ctx.lineTo(x, yLow);
    ctx.stroke();

    // Body
    ctx.fillStyle = hexAlpha(color, isBull ? 0.80 : 0.87);
    ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyH);

    ctx.strokeStyle = color;
    ctx.lineWidth   = 0.5;
    ctx.strokeRect(x - candleW / 2, bodyTop, candleW, bodyH);
  }
}

// ── Consolidation zones ───────────────────────────────────────────────────────
export function drawConsolidations(ctx, consolidations, viewport, activeTimeframes) {
  const fillColor   = hexAlpha(COLORS.consolidation, 0.27);
  const strokeColor = hexAlpha(COLORS.consolidation, 0.60);

  ctx.setLineDash([4, 4]);
  ctx.lineWidth = 1;

  for (const zone of consolidations) {
    if (activeTimeframes && !activeTimeframes.includes(zone.timeframe)) continue;

    const { x: x1, y: y1 } = worldToCanvas(zone.timeStart, zone.priceHigh, viewport);
    const { x: x2, y: y2 } = worldToCanvas(zone.timeEnd,   zone.priceLow,  viewport);

    const rx = Math.min(x1, x2);
    const ry = Math.min(y1, y2);
    const rw = Math.abs(x2 - x1);
    const rh = Math.abs(y2 - y1);

    ctx.fillStyle   = fillColor;
    ctx.fillRect(rx, ry, rw, rh);
    ctx.strokeStyle = strokeColor;
    ctx.strokeRect(rx, ry, rw, rh);
  }

  ctx.setLineDash([]);
}

// ── NN-refined consolidation zones ────────────────────────────────────────────
export function drawNNBoxes(ctx, consolidations, viewport) {
  consolidations.forEach(zone => {
    if (!zone.nn_box) return;

    // Original zone — yellow dashed outline
    const s = worldToCanvas(zone.timeStart, zone.priceHigh, viewport);
    const e = worldToCanvas(zone.timeEnd,   zone.priceLow,  viewport);
    ctx.strokeStyle = hexAlpha('#F5C518', 0.6);
    ctx.lineWidth   = 1;
    ctx.setLineDash([5, 5]);
    ctx.strokeRect(s.x, e.y, e.x - s.x, s.y - e.y);
    ctx.setLineDash([]);

    // NN box — solid blue fill + outline
    const ns = worldToCanvas(zone.nn_box.timeStart * 1000, zone.nn_box.priceHigh, viewport);
    const ne = worldToCanvas(zone.nn_box.timeEnd   * 1000, zone.nn_box.priceLow,  viewport);
    ctx.fillStyle   = hexAlpha('#4A90D9', 0.12);
    ctx.fillRect(ns.x, ne.y, ne.x - ns.x, ns.y - ne.y);
    ctx.strokeStyle = '#4A90D9';
    ctx.lineWidth   = 1.5;
    ctx.strokeRect(ns.x, ne.y, ne.x - ns.x, ns.y - ne.y);

    // Confidence label
    ctx.font      = '10px Inter, sans-serif';
    ctx.fillStyle = '#4A90D9';
    ctx.textAlign = 'right';
    ctx.fillText(`NN: ${Math.round((zone.nn_box.confidence || 0) * 100)}%`, ne.x - 2, ne.y - 4);
  });
}

// ── Scenarios ─────────────────────────────────────────────────────────────────
export function drawScenarios(ctx, scenarios, viewport, activeTimeframes, tfConfig) {
  const tfOrder = ['4H', '1H', '15m', '5m', '1m'];

  for (const tf of tfOrder) {
    if (activeTimeframes && !activeTimeframes.includes(tf)) continue;
    if (!scenarios[tf]) continue;

    const cfg = tfConfig[tf];

    for (const scenario of scenarios[tf]) {
      const baseColor = scenario.confirmed
        ? COLORS.confirmed
        : (COLORS[scenario.type] || COLORS.none);

      const opacity = Math.min(1, cfg.opacity * (scenario.confirmed ? 1.4 : 1));
      const strokeW = cfg.strokeWidth * (scenario.confirmed ? 1.5 : 1);

      // ── TP Zone rectangle ─────────────────────────────────────────────────
      const tp = scenario.tp_zone;
      if (tp && tp.high != null && tp.low != null) {
        const entryTime  = scenario.path?.[0]?.time ?? viewport.timeMin;
        const { x: tpX0 } = worldToCanvas(entryTime,       tp.high, viewport);
        const { x: tpX1 } = worldToCanvas(viewport.timeMax, tp.high, viewport);
        const { y: ty1  } = worldToCanvas(viewport.timeMin, tp.high, viewport);
        const { y: ty2  } = worldToCanvas(viewport.timeMin, tp.low,  viewport);

        const rectY = Math.min(ty1, ty2);
        const rectH = Math.abs(ty1 - ty2);

        ctx.fillStyle   = hexAlpha(baseColor, opacity * 0.15);
        ctx.fillRect(tpX0, rectY, tpX1 - tpX0, rectH);

        ctx.strokeStyle = hexAlpha(baseColor, opacity * 0.40);
        ctx.lineWidth   = 0.8;
        ctx.setLineDash([3, 3]);
        ctx.strokeRect(tpX0, rectY, tpX1 - tpX0, rectH);
        ctx.setLineDash([]);
      }

      // ── SL horizontal line ────────────────────────────────────────────────
      if (scenario.sl != null) {
        const entryTime  = scenario.path?.[0]?.time ?? viewport.timeMin;
        const { x: slX } = worldToCanvas(entryTime, scenario.sl, viewport);
        const { y: slY } = worldToCanvas(entryTime, scenario.sl, viewport);

        ctx.strokeStyle = hexAlpha(baseColor, opacity * 0.60);
        ctx.lineWidth   = strokeW * 0.7;
        ctx.setLineDash([6, 3]);
        ctx.beginPath();
        ctx.moveTo(slX, slY);
        ctx.lineTo(viewport.width, slY);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // ── Forward projection path ───────────────────────────────────────────
      const pts = scenario.path;
      if (pts && pts.length > 1) {
        // Quick visibility cull: check if first + last point are both off-screen
        const { x: px0 } = worldToCanvas(pts[0].time,  pts[0].price, viewport);
        const { x: pxN } = worldToCanvas(pts[pts.length - 1].time, pts[pts.length - 1].price, viewport);
        if (px0 > viewport.width && pxN > viewport.width) {
          // Entirely to the right — skip
        } else {
          ctx.strokeStyle = hexAlpha(baseColor, opacity);
          ctx.lineWidth   = strokeW;
          ctx.lineCap     = 'round';
          ctx.lineJoin    = 'round';

          if (scenario.type === 'none') ctx.setLineDash([8, 5]);

          ctx.beginPath();
          const { x: x0, y: y0 } = worldToCanvas(pts[0].time, pts[0].price, viewport);
          ctx.moveTo(x0, y0);
          for (let i = 1; i < pts.length; i++) {
            const { x, y } = worldToCanvas(pts[i].time, pts[i].price, viewport);
            ctx.lineTo(x, y);
          }
          ctx.stroke();
          ctx.setLineDash([]);

          // ── Glow for confirmed (shadowBlur — GPU-friendly vs ctx.filter) ──
          if (scenario.confirmed) {
            ctx.save();
            ctx.shadowColor = baseColor;
            ctx.shadowBlur  = 12;
            ctx.strokeStyle = hexAlpha(baseColor, 0.35);
            ctx.lineWidth   = strokeW * 3;
            ctx.beginPath();
            ctx.moveTo(x0, y0);
            for (let i = 1; i < pts.length; i++) {
              const { x, y } = worldToCanvas(pts[i].time, pts[i].price, viewport);
              ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.restore();
          }
        }
      }

      // ── Entry dot ─────────────────────────────────────────────────────────
      if (scenario.entry != null && pts && pts.length > 0) {
        const { x: ex, y: ey } = worldToCanvas(pts[0].time, scenario.entry, viewport);
        const radius = scenario.confirmed ? 5 : 4;

        ctx.beginPath();
        ctx.arc(ex, ey, radius + 2, 0, 6.2832); // 2π pre-computed
        ctx.fillStyle = hexAlpha(baseColor, opacity * 0.25);
        ctx.fill();

        ctx.beginPath();
        ctx.arc(ex, ey, radius, 0, 6.2832);
        ctx.fillStyle = hexAlpha(baseColor, opacity * 0.90);
        ctx.fill();
      }
    }
  }
}

// ── "Now" vertical line ───────────────────────────────────────────────────────
export function drawNowLine(ctx, viewport) {
  const now = Date.now();
  const { x } = worldToCanvas(now, viewport.priceMin, viewport);
  if (x < 0 || x > viewport.width) return;

  ctx.strokeStyle = hexAlpha(COLORS.crosshair, 0.20);
  ctx.lineWidth   = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, viewport.height);
  ctx.stroke();
  ctx.setLineDash([]);
}

// ── Crosshair ────────────────────────────────────────────────────────────────
export function drawCrosshair(ctx, mouseX, mouseY, viewport) {
  if (mouseX == null || mouseY == null) return;

  ctx.strokeStyle = hexAlpha(COLORS.crosshair, 0.40);
  ctx.lineWidth   = 0.8;
  ctx.setLineDash([4, 4]);

  ctx.beginPath();
  ctx.moveTo(mouseX, 0);
  ctx.lineTo(mouseX, viewport.height);
  ctx.moveTo(0, mouseY);
  ctx.lineTo(viewport.width, mouseY);
  ctx.stroke();

  ctx.setLineDash([]);
}

// ── Step helpers ─────────────────────────────────────────────────────────────
function getTimeStep(range) {
  if (range > 7 * 86_400_000) return 86_400_000;
  if (range > 86_400_000)     return 14_400_000;  // 4 h
  if (range > 21_600_000)     return 3_600_000;   // 1 h
  if (range > 3_600_000)      return 900_000;     // 15 m
  if (range > 1_800_000)      return 300_000;     // 5 m
  return 60_000;
}

function getPriceStep(range) {
  if (range > 0.05)  return 0.0100;
  if (range > 0.02)  return 0.0050;
  if (range > 0.01)  return 0.0020;
  if (range > 0.005) return 0.0010;
  if (range > 0.002) return 0.0005;
  return 0.0001;
}
