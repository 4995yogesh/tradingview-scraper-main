# Representation-Learning Integration

## Purpose

This branch adapts the existing TradingView-like chart/data engine for the candlestick representation-learning project without rebuilding the chart engine or its data plumbing.

The existing application remains the **market-data and visualization engine**. The separate private repository `4995yogesh/candlestick-representation-learning` remains the **research/model repository**.

## Source baseline

- Engine repository: `4995yogesh/tradingview-scraper-main`
- Baseline branch: `ml-try-2`
- Baseline commit: `0cef017fa28c3af04e5aaacd2ddd425d7e092aeb`
- Integration branch: `agent/representation-learning-integration`

## Existing pipeline

```text
TradingView WebSocket/live feed
        |
        v
pipeline/data/collector.py
        |
        | RAW_CANDLE
        v
pipeline/data/validator.py
        |
        | VALIDATED_CANDLE
        +------------------------------+
        |                              |
        v                              v
pipeline/data/storage.py       pipeline/processing/aggregator.py
(RAM hot cache)                (incremental partial/closed HTF candles)
        |                              |
        +---------------+--------------+
                        |
                        v
                 backend/server.py
                        |
                 FastAPI OHLC API
                        |
                        v
              frontend/src/data/chartData.js
                        |
                        v
            frontend ChartWidget / canvas / overlays
```

Persistent chart storage is provided by `pipeline/data/db.py` (`CandleDB`, SQLite/WAL).

Historical seeding already exists in `backend/dukascopy_seeder.py` and directly decodes Dukascopy `BID_candles_min_1.bi5` files. This is the historical downloader that the research path should reuse.

## Reuse matrix

| Existing component | Decision | Representation-learning use |
|---|---|---|
| `backend/dukascopy_seeder.py` | **Reuse + generalize** | Historical 1m BID source; research exporter calls its day decoder |
| `pipeline/data/db.py` | **Reuse for chart/local operational cache** | Inspection, local serving, range queries; not the sole multi-year training store |
| `pipeline/data/storage.py` | **Reuse** | Fast local chart/live cache |
| `pipeline/core/engine.py` | **Reuse** | Event-driven local/live pipeline |
| `pipeline/processing/aggregator.py` | **Reuse + verify** | Existing in-progress HTF logic is the basis for causal partial candles |
| `backend/server.py` | **Reuse + isolate chart semantics** | Existing FastAPI/chart API; later add model/retrieval endpoints |
| `frontend/src/components/chart/ChartWidget.jsx` | **Reuse unchanged initially** | Main visual inspection surface |
| `frontend/src/components/chart/LabelDialog.jsx` | **Reuse later** | Human labels / qualitative error analysis / fine-tuning labels |
| `frontend/src/components/patterns/PatternExplorerPage.jsx` | **Reuse later** | Adapt to embedding nearest-neighbour retrieval |
| legacy `backend/ml/*` supervised models | **Do not use as foundation model** | Keep as legacy baselines / human-feedback infrastructure only |
| `pipeline/processing/features.py` swings/FVG | **Do not blindly use as causal encoder inputs** | Retrospective labels/probes unless information-availability is explicitly corrected |
| TradingView historical/live feed | **Chart/comparison only** | Never mix into canonical pretraining data |
| synthetic chart generator in `chartData.js` | **UI demo only** | Never use for training/evaluation |

## Research data contract

The training source of truth is Dukascopy BID 1-minute data.

Canonical research columns:

```text
timestamp  UTC timestamp
open       float
high       float
low        float
close      float
volume     float
```

The research exporter writes partitioned Parquet outside Git (Google Drive in Colab). Large multi-year datasets are not stored in SQLite or Git.

## Critical semantic boundary

The chart engine contains display/native-feed conventions that must not silently become research-dataset conventions.

Examples:

- OANDA/TradingView daily-session handling and chart labels are UI/feed-parity concerns.
- The canonical research dataset uses explicit UTC timestamps and deterministic research resampling.
- TradingView/OANDA may be used for visual/native-feed comparison, not for filling missing Dukascopy training observations.
- A feature is causal only if every value it depends on was available at the sample decision time.

## Existing logic that needs special treatment

### Partial HTF candles

`pipeline/processing/aggregator.py` already updates and emits an in-progress higher-timeframe candle after every validated base candle. This is directly reusable as the live/chart analogue of the research project's partial-HTF concept.

Research code still needs tests proving that mutating observations after decision time cannot change the partial candle at that decision time.

### Swing confirmation

`pipeline/processing/features.py` detects a swing at the middle candle using the following candle. Such a swing is only *confirmed* after the following candle exists. It must not be timestamped as information available at the middle candle when used by a causal model.

### Multiple aggregation implementations

The current application contains aggregation/bucket logic in more than one place (`pipeline/processing/aggregator.py`, `backend/server.py`, HTF synthesis helpers). These should converge on a tested shared research-compatible boundary implementation before the model relies on them.

## Integration direction

```text
EXISTING ENGINE REPO
Dukascopy BI5 -> research_export.py -> canonical partitioned Parquet -> Google Drive
       |                                                    |
       |                                                    v
       |                                      MODEL / RESEARCH REPO
       |                                      windowing -> SSL model -> embeddings
       |                                                    |
       +-- chart DB / FastAPI / ChartWidget <--- model artifacts / retrieval API
```

This avoids maintaining two chart engines, two Dukascopy downloaders, or two live-data stacks.
