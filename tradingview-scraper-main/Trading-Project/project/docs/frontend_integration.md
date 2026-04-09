# Frontend Integration Guide

The FastAPI backend exposes the projections via:
`GET http://localhost:8001/scenarios`

This endpoint returns JSON structured by timeframe, such as `1m`, `5m`, etc.

## 1. Polling the Data
In your React or Vanilla JS application, fetch the data whenever your chart updates (or periodically):

```javascript
async function fetchScenarios() {
    const res = await fetch('http://localhost:8001/scenarios');
    const data = await res.json();
    return data;
}
```

## 2. Drawing on TradingView Lightweight Charts
If using the Lightweight Charts library, you cannot natively draw irregular "shapes" (consolidation boxes) without custom plugins, but you can draw scenario paths and TP/SL lines.

**Price Lines (SL / TP)**
```javascript
const activeScenarios = data['15m'].filter(s => s.type !== 'none');

activeScenarios.forEach(scenario => {
    // Stop Loss Line
    const slLine = chartSeries.createPriceLine({
        price: scenario.sl,
        color: '#ff4d4d',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'SL',
    });

    // Take Profit High Bound
    const tpLine = chartSeries.createPriceLine({
        price: scenario.tp_zone.high,
        color: '#4caf50',
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: 'TP',
    });
});
```

**Drawing Paths using a Line Series (Infinite Canvas Style Projection)**
To draw the scenario path as a future projection, you can create a secondary line series, or if you want to draw directly on canvas context, you have to use the chart's subscribe tool.

```javascript
const pathSeries = chart.addLineSeries({
    color: '#2196f3',
    lineStyle: LightweightCharts.LineStyle.Dotted
});

// scenario.path is an array of [timestamp, price]
const pathData = scenario.path.map(point => ({ 
    time: point[0] / 1000, 
    value: point[1] 
}));

pathSeries.setData(pathData);
```

## 3. Drawing on Raw HTML Canvas
If you manage your own HTML canvas overlay (absolute positioned over your chart), transform prices/times to X/Y coordinates:

```javascript
function drawConsolidationBox(ctx, xStart, xEnd, yHigh, yLow) {
    ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.strokeStyle = '#ffffff';
    ctx.beginPath();
    ctx.rect(xStart, yHigh, xEnd - xStart, yLow - yHigh);
    ctx.fill();
    ctx.stroke();
}
```
