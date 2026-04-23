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
          ctx.lineWidth = 1 * vRatio;
          
          // Top Line
          ctx.moveTo(left, top);
          ctx.lineTo(right, top);
          
          // Bottom Line
          ctx.moveTo(left, bottom);
          ctx.lineTo(right, bottom);
          ctx.stroke();
        }
      }
    });
  }
}
