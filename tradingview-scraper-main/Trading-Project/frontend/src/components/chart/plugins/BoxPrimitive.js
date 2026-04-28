export class ConsolidationBoxesPrimitive {
  constructor() {
    this._boxes = [];
    this._paneViews = [new ConsolidationBoxesPaneView(this)];
  }

  updateAllViews() {
    if (this._requestUpdate) this._requestUpdate();
  }

  paneViews() {
    return this._paneViews;
  }

  attached({ requestUpdate, chart, series }) {
    this._requestUpdate = requestUpdate;
    this._chart = chart;
    this._series = series;
  }

  detached() {
    this._requestUpdate = undefined;
    this._chart = undefined;
    this._series = undefined;
  }

  setData(boxes) {
    this._boxes = boxes;
    this.updateAllViews();
  }
}

class ConsolidationBoxesPaneView {
  constructor(source) {
    this._source = source;
  }
  update() {}
  renderer() {
    return new ConsolidationBoxesPaneRenderer(this._source);
  }
  zOrder() {
    return 'bottom';
  }
}

class ConsolidationBoxesPaneRenderer {
  constructor(source) {
    this._source = source;
  }

  draw(target) {
    const chart = this._source._chart;
    const series = this._source._series;
    if (!chart || !series || this._source._boxes.length === 0) return;

    target.useBitmapCoordinateSpace((scope) => {
      const ts = chart.timeScale();
      const ctx = scope.context;
      const hRatio = scope.horizontalPixelRatio;
      const vRatio = scope.verticalPixelRatio;

      for (const box of this._source._boxes) {
        // box = { t1, t2, priceHigh, priceLow, borderColor, fillColor }
        const x1 = ts.timeToCoordinate(box.t1);
        const x2 = ts.timeToCoordinate(box.t2);
        if (x1 === null || x2 === null) continue;

        const y1 = series.priceToCoordinate(box.priceHigh);
        const y2 = series.priceToCoordinate(box.priceLow);
        if (y1 === null || y2 === null) continue;

        const left   = Math.min(x1, x2) * hRatio;
        const right  = Math.max(x1, x2) * hRatio;
        const top    = Math.min(y1, y2) * vRatio;
        const bottom = Math.max(y1, y2) * vRatio;

        const w = right - left;
        const h = bottom - top;

        // Fill
        if (box.fillColor) {
          ctx.fillStyle = box.fillColor;
          ctx.fillRect(left, top, w, h);
        }

        // Borders (top and bottom lines)
        if (box.borderColor) {
          ctx.beginPath();
          ctx.strokeStyle = box.borderColor;
          ctx.lineWidth = (box.highlighted ? 4 : 1) * vRatio;
          
          if (box.isDashed && !box.highlighted) {
            ctx.setLineDash([5 * hRatio, 5 * hRatio]);
          } else {
            ctx.setLineDash([]);
          }
          
          // If highlighted, draw full rectangle and thick yellow glow
          if (box.highlighted) {
            ctx.shadowBlur = 20 * hRatio;
            ctx.shadowColor = '#FFEB3B'; // Bright Yellow Glow
            ctx.strokeStyle = box.borderColor; // Keep label color
            ctx.strokeRect(left, top, w, h);
            
            // Inner stroke for extra definition
            ctx.lineWidth = 1 * vRatio;
            ctx.strokeStyle = '#FFFFFF'; // White inner edge
            ctx.strokeRect(left, top, w, h);
            
            ctx.shadowBlur = 0; // reset
          } else {
            // Top Line
            ctx.moveTo(left, top);
            ctx.lineTo(right, top);
            
            // Bottom Line
            ctx.moveTo(left, bottom);
            ctx.lineTo(right, bottom);
            ctx.stroke();
          }
          ctx.setLineDash([]); // Reset
        }

        // --- Render Auto-Label Info ---
        if (box.autoLabel) {
          const al = box.autoLabel;
          const fontSize = Math.max(10, 10 * hRatio);
          ctx.font = `bold ${fontSize}px Inter, sans-serif`;
          ctx.textAlign = 'left';
          ctx.textBaseline = 'bottom';

          const labelText = `${al.label} (${(al.confidence || 0).toFixed(2)})`;
          const textWidth = ctx.measureText(labelText).width;
          
          // Positioning
          const textX = left + 2 * hRatio;
          const textY = top - 4 * vRatio; // Just above top edge
          const markerY = textY - fontSize - 2 * vRatio; // Above the text

          // 1. Draw small dark background for text legibility outside the box
          ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
          ctx.fillRect(textX - 2 * hRatio, textY - fontSize, textWidth + 4 * hRatio, fontSize + 2 * vRatio);

          // 2. Draw Label Text
          ctx.fillStyle = box.borderColor || '#FFFFFF';
          ctx.fillText(labelText, textX, textY);

          // 3. Status Indicator (Stacked above text)
          const dotRadius = 4 * hRatio;
          const dotX = left + 8 * hRatio;

          ctx.beginPath();
          if (al.status === 'AGREED') {
            ctx.fillStyle = '#4CAF50'; // Green
            ctx.arc(dotX, markerY, dotRadius, 0, Math.PI * 2);
            ctx.fill();
          } else if (al.status === 'DISAGREE') {
            ctx.fillStyle = '#FF9800'; // Orange Warning
            ctx.moveTo(dotX, markerY - dotRadius);
            ctx.lineTo(dotX - dotRadius, markerY + dotRadius);
            ctx.lineTo(dotX + dotRadius, markerY + dotRadius);
            ctx.closePath();
            ctx.fill();
          } else {
            ctx.fillStyle = '#9E9E9E'; // Gray Question
            ctx.arc(dotX, markerY, dotRadius, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = '#FFFFFF';
            ctx.font = `${8 * hRatio}px Inter, sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('?', dotX, markerY);
          }
        }
      }
    });
  }
}
