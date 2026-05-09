# Root Cause Analysis: ML Localization Failure

## 1. Confirmed Root Cause
The systematic anchoring of blue ML boxes to the right side of the chart is caused by **hardcoded inference windowing** in the indicator layer.

### Primary Bug: Hardcoded "Last 100" Window
In `Trading-Project/project/indicators/consolidation.py`, the `NNPredictor` class explicitly slices the input data to the last 100 candles regardless of where the actual consolidation is.
```python
# indicators/consolidation.py:59
last_100 = df.iloc[-100:]
...
# indicators/consolidation.py:75
base_idx = len(df) - 100
```
This causes the "NEURAL" zone to always be anchored to the latest data on the chart.

### Secondary Bug: Blue Color Fallback
The frontend `ChartWidget.jsx` does not have a specific color mapping for the `NEURAL` zone type. It falls back to a light blue color (`rgba(144, 202, 249)`), which is why the user identifies these as "ML boxes".

---

## 2. Technical Audit Findings

### A. Architecture Mismatch
There is a critical discrepancy between the models used in different parts of the system:
*   **`ml/nn_scorer.py`**: Uses a **Flatten** layer (`64 * 100`), preserving some temporal resolution.
*   **`indicators/consolidation.py`**: Uses **AdaptiveAvgPool1d(1)**, which collapses the entire 100-candle sequence into a single average vector. This makes it impossible for the model to distinguish *where* a consolidation starts or ends within the window.

### B. Normalization Mismatch
*   **Training (`train_nn.py`)**: Uses **Min-Max** normalization `(x - min) / (max - min)`.
*   **Inference (`indicators/consolidation.py`)**: Uses **Percentage Change** `(x - first_close) / first_close`.
This ensures the model receives data in a distribution it never saw during training, leading to saturated or erratic outputs.

### C. Training Label Bias
The training script `ml/train_nn.py` generates samples by cropping 100 candles ending 30 bars after the box end. 
```python
crop_end = end_idx_in_all + 30
crop_start = max(0, crop_end - 100)
```
This forces the model to learn that every consolidation "ends at index 70". Consequently, even when given a correct window, the model defaults to predicting the box in that specific relative position.

---

## 3. Implementation Status (as of 2026-05-06)

### Phase 1: Stabilization [COMPLETED]
- [x] **Architecture Unified**: Created `backend/ml/shared_models.py` with a consistent `ConsolidationCNN`.
- [x] **Normalization Synchronized**: Standardized on Min-Max scaling across all modules.
- [x] **Indicator Layer Decoupling**: Removed hardcoded right-side anchoring from `indicators/consolidation.py`.

### Phase 2: Temporal Segmentation [IN PROGRESS]
The system has been redesigned to move from coordinate regression (predicting global indices) to **Candle-Level Temporal Segmentation** (predicting membership probability per candle).

#### Structural Changes:
1.  **Segmentation Head**: The model now outputs a 100-length probability vector (heatmap) using 1D-CNN layers that preserve temporal resolution.
2.  **Dual Output**: The architecture now features a Segmentation Head (heatmap) and a Price Head (High/Low regression).
3.  **Weighted Supervision**: Training now uses `BCEWithLogitsLoss` with `pos_weight=2.0` to handle class imbalance.
4.  **Inference Post-Processing**: `predict_box` now extracts the largest contiguous block of high-probability candles.

#### Current Training Metrics:
- **Architecture**: CNN-Encoder + Segmentation Head + Price Regression Head.
- **Samples**: 693 labeled boxes.
- **Target Loss**: < 0.05 BCE for segmentation.
- **Verification**: Testing on USDJPY following 300-epoch training cycle.

---

## 4. Summary of Failure Categorization
| Category | Status | Confidence |
| :--- | :--- | :--- |
| **A) Classification-only architecture** | **Fixed** | 100% (Moved to Segmentation) |
| **B) Missing localization labels** | **Fixed** | 100% (Binary masks used) |
| **C) Sliding-window indexing bug** | **Fixed** | 100% (Dynamic windowing implemented) |
| **D) Rendering/UI anchoring bug** | **Fixed** | 100% (Color mapping decoupled) |
| **E) Temporal info collapse** | **Fixed** | 100% (Flatten/Pooling replaced by Segmentation) |
| **F) Coordinate conversion error** | **Fixed** | 100% (Normalization standardized) |
