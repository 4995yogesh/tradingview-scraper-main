import pandas as pd
import numpy as np
import os
import torch
import torch.nn as nn
from typing import Optional

# ── Neural Network Architecture (Must match ml/train_nn.py) ──────────────────
from ml.shared_models import ConsolidationCNN

class NNPredictor:
    _instance = None
    _model = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_model()
        return cls._instance

    def _load_model(self):
        # Path relative to project root (Trading-Project)
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "models", "consolidation_nn.pt"))
        if os.path.exists(path):
            try:
                self._model = ConsolidationCNN(sequence_length=100)
                self._model.load_state_dict(torch.load(path, map_location='cpu'))
                self._model.eval()
                print(f"[NN] Loaded model from {path}")
            except Exception as e:
                print(f"[NN] Error loading model: {e}")
                self._model = None

    def predict(self, df: pd.DataFrame, window_size: int = 100) -> Optional[dict]:
        """
        Unified prediction logic with Min-Max normalization.
        DEPRECATED: Global chart prediction is unreliable for localization.
        Use per-zone refinement instead.
        """
        if self._model is None or len(df) < window_size:
            return None
        
        try:
            # Prepare last 100 candles (only for legacy support)
            last_n = df.iloc[-window_size:]
            candles_np = np.array([[c['open'], c['high'], c['low'], c['close']] for _, c in last_n.iterrows()])
            
            # Min-Max Normalization (matches train_nn.py)
            window_min = np.min(candles_np)
            window_max = np.max(candles_np)
            window_range = max(1e-9, window_max - window_min)
            feat = (candles_np - window_min) / window_range
            
            # Add Positional Encoding (matches train_nn.py)
            pos = np.linspace(0, 1, window_size).reshape(-1, 1)
            feat = np.hstack([feat, pos]) # (100, 5)
            
            X_t = torch.tensor([feat], dtype=torch.float32)
            with torch.no_grad():
                pred = self._model(X_t).numpy()[0]
            
            # pred: [start_idx_pct, end_idx_pct, y_high, y_low]
            s_idx = int(round(pred[0] * window_size))
            e_idx = int(round(pred[1] * window_size))
            s_idx = max(0, min(window_size - 1, s_idx))
            e_idx = max(0, min(window_size - 1, e_idx))
            
            p_hi = float((pred[2] * window_range) + window_min)
            p_lo = float((pred[3] * window_range) + window_min)
            
            # Global index in original df
            base_idx = len(df) - window_size
            
            return {
                "start": base_idx + s_idx,
                "end":   base_idx + e_idx,
                "top":   p_hi,
                "bottom": p_lo,
                "type": "NEURAL_REFINED",
                "score": 1.0
            }
        except Exception as e:
            print(f"[NN] Prediction failed: {e}")
            return None


def consolidation_boxes(
    df: pd.DataFrame,
    min_bars: int = 6,
    fvg_threshold: float = 0.4,
    use_time_filter: bool = True,
    max_consec_dir: int = 4,
    max_net_move: float = 0.60,
) -> pd.DataFrame:
    """Detect consolidation boxes.
    df must have columns ['open','high','low','close'] and datetime index.
    Returns DataFrame with columns: start, end, top, bottom (indices).

    Optimised: all OHLC data pre-extracted to numpy arrays so the hot loop
    does O(1) array indexing instead of slow pandas .iloc row access.

    Trending-box rejection gates (applied after the close-inside validation):
      max_consec_dir : reject if the longest run of consecutive same-direction
                       closes >= this value (catches staircase trends).
      max_net_move   : reject if |close[-1] - close[0]| / box_height > this
                       value (catches directional traversal of the range).
    """
    n = len(df)
    if n < 3:
        return pd.DataFrame()

    # ── Pre-extract numpy arrays (avoids slow pandas row access in loop) ──────
    high_arr  = df["high"].to_numpy(dtype=np.float64)
    low_arr   = df["low"].to_numpy(dtype=np.float64)
    open_arr  = df["open"].to_numpy(dtype=np.float64)
    close_arr = df["close"].to_numpy(dtype=np.float64)

    # Hour array for time filter (0 for daily/weekly indices without .hour)
    if use_time_filter:
        idx = df.index
        # Shift UTC index to IST (UTC+5.5) before extracting hour
        hour_arr = np.array(
            [(v + pd.Timedelta(hours=5, minutes=30)).hour if hasattr(v, "hour") else 0 for v in idx],
            dtype=np.int8,
        )
    else:
        hour_arr = np.zeros(n, dtype=np.int8)

    boxes = []
    searchingSwings = True
    anchorIndex     = 0
    gotSwingHigh    = gotSwingLow = False
    swingHighVal    = swingLowVal = np.nan
    firstSwingIndex = None
    active          = False
    activeBox       = None
    rangeTop        = rangeBottom = np.nan
    fvgBlocked      = False
    boxStarted      = False

    for i in range(2, n):
        h   = high_arr[i];  l   = low_arr[i]
        o   = open_arr[i];  c   = close_arr[i]
        h1  = high_arr[i-1]; l1 = low_arr[i-1]
        h2  = high_arr[i-2]; l2 = low_arr[i-2]
        o1  = open_arr[i-1]; c1 = close_arr[i-1]

        isBlockedTime = use_time_filter and (0 <= hour_arr[i] < 6)

        isSwingHigh = h1 > h2 and h1 >= h
        isSwingLow  = l1 < l2 and l1 <= l

        bullishFVG  = l  > h2
        bearishFVG  = h  < l2
        bullFvgSize = (l  - h2) if bullishFVG else 0.0
        bearFvgSize = (l2 - h)  if bearishFVG else 0.0
        bodySize    = abs(c - o)
        smallBull   = bullishFVG and bullFvgSize < bodySize * fvg_threshold
        smallBear   = bearishFVG and bearFvgSize < bodySize * fvg_threshold
        validFVG    = (bullishFVG and not smallBull) or (bearishFVG and not smallBear)

        if active:
            if c > rangeTop or c < rangeBottom or isBlockedTime:
                # User enforced strict rule: terminate box exactly one candle prior to breakout
                activeBox["end"]    = i - 1
                activeBox["top"]    = float(high_arr[activeBox["start"] : activeBox["end"] + 1].max())
                activeBox["bottom"] = float(low_arr[activeBox["start"] : activeBox["end"] + 1].min())
                boxes.append(activeBox)
                active          = False
                activeBox       = None
                rangeTop        = rangeBottom = np.nan
                searchingSwings = True
                boxStarted      = False
                gotSwingHigh    = gotSwingLow = False
                swingHighVal    = swingLowVal = np.nan
                firstSwingIndex = None
                anchorIndex     = i
            else:
                # LOCK: Only expand if count <= 5
                age = i - activeBox["start"] + 1
                if age <= 5:
                    if h > rangeTop:    rangeTop    = h
                    if l < rangeBottom: rangeBottom = l
                
                activeBox["end"]    = i
                activeBox["top"]    = rangeTop
                activeBox["bottom"] = rangeBottom

        # Reset search state entirely if we are in blocked time
        if not active and isBlockedTime:
            anchorIndex     = i
            gotSwingHigh    = gotSwingLow = False
            swingHighVal    = swingLowVal = np.nan
            firstSwingIndex = None
            rangeTop        = rangeBottom = np.nan
            fvgBlocked      = False
            boxStarted      = False
            continue

        if not boxStarted and validFVG and not isBlockedTime:
            fvgBlocked = True

        if searchingSwings and not active and i > anchorIndex and not isBlockedTime:
            swingBarIndex = i - 1
            if swingBarIndex > anchorIndex:
                if not gotSwingHigh and isSwingHigh:
                    gotSwingHigh = True
                    swingHighVal = h1
                    if firstSwingIndex is None:
                        firstSwingIndex = swingBarIndex
                if not gotSwingLow and isSwingLow:
                    gotSwingLow = True
                    swingLowVal = l1
                    if firstSwingIndex is None:
                        firstSwingIndex = swingBarIndex


            if fvgBlocked:
                anchorIndex     = i
                gotSwingHigh    = gotSwingLow = False
                swingHighVal    = swingLowVal = np.nan
                firstSwingIndex = None
                rangeTop        = rangeBottom = np.nan
                fvgBlocked      = False
                continue

            if gotSwingHigh and gotSwingLow and firstSwingIndex is not None:
                # Requirement: ALL candles must close inside until we hit min_bars
                # Extension: Expansion allowed if wicks break range but close inside
                all_inside = True
                tempHigh   = swingHighVal
                tempLow    = swingLowVal
                current_count = 0
                
                for j in range(firstSwingIndex, i + 1):
                    # How many candles have we processed in this potential box?
                    pos_in_box = j - firstSwingIndex + 1

                    # Check close against CURRENT range
                    if tempLow <= close_arr[j] <= tempHigh:
                        # Expansion ONLY allowed during the formation phase (first 5 candles)
                        if pos_in_box <= 5:
                            if low_arr[j]  < tempLow:  tempLow  = low_arr[j]
                            if high_arr[j] > tempHigh: tempHigh = high_arr[j]
                        
                        current_count += 1
                    else:
                        all_inside = False
                        break

                if all_inside and current_count >= min_bars:
                    # ── Trending-box rejection Gate 1: consecutive directional closes ──
                    # Walk the validated span chronologically and find the longest
                    # unbroken run of closes that move in the same direction.
                    max_run = 0
                    cur_run = 0
                    cur_dir = 0  # +1 up, -1 down, 0 not yet set
                    for j in range(firstSwingIndex + 1, i + 1):
                        diff = close_arr[j] - close_arr[j - 1]
                        if diff != 0:
                            direction = 1 if diff > 0 else -1
                            if direction == cur_dir:
                                cur_run += 1
                            else:
                                cur_run = 1
                                cur_dir = direction
                            max_run = max(max_run, cur_run)
                        else:
                            cur_run = 0

                    # ── Trending-box rejection Gate 2: net displacement ratio ──────
                    # |close[-1] - close[0]| / box_height > max_net_move → trending
                    box_height   = tempHigh - tempLow
                    net_move     = abs(close_arr[i] - close_arr[firstSwingIndex])
                    net_ratio    = (net_move / box_height) if box_height > 0 else 0.0

                    trending_box = (max_run >= max_consec_dir) or (net_ratio > max_net_move)

                if all_inside and current_count >= min_bars and not trending_box:
                    swingHighVal    = tempHigh
                    swingLowVal     = tempLow
                    rangeTop        = swingHighVal
                    rangeBottom     = swingLowVal
                    active          = True
                    searchingSwings = False
                    boxStarted      = True
                    
                    # ── Classification & Scoring ──
                    box_candles = df.iloc[firstSwingIndex : i + 1]
                    cl = box_candles["close"].to_numpy()
                    op = box_candles["open"].to_numpy()
                    hi = box_candles["high"].to_numpy()
                    lo = box_candles["low"].to_numpy()
                    
                    rng = rangeTop - rangeBottom
                    mid = (rangeTop + rangeBottom) / 2.0
                    tightness = rng / (cl[-1] + 1e-9)
                    
                    displacement = abs(cl[-1] - cl[0])
                    path_length  = np.sum(np.abs(np.diff(cl))) + 1e-9
                    efficiency   = displacement / path_length
                    
                    body_avg = np.mean(np.abs(cl - op))
                    bias     = body_avg / (rng + 1e-9)
                    
                    touch_thresh = rng * 0.05
                    touches = np.sum(rangeTop - hi < touch_thresh) + np.sum(lo - rangeBottom < touch_thresh)
                    
                    score = (float(touches) * 0.5) + (float(efficiency) * 3.0) - (float(bias) * 2.0)
                    
                    box_type = "LOOSE"
                    if tightness < 0.005 and touches >= 4:
                        box_type = "TIGHT"
                    elif efficiency < 0.4 and bias > 0.3:
                        box_type = "DRIFT"
                    
                    activeBox = {
                        "start": firstSwingIndex, 
                        "end": i,
                        "top": rangeTop, 
                        "bottom": rangeBottom,
                        "type": box_type,
                        "score": round(score, 2)
                    }



    # ── Neural Network Refinement / Overlay (DEPRECATED) ──
    # Global chart-wide prediction is disabled here to prevent right-side anchoring bugs.
    # Localization is now handled via the dedicated /api/nn/refined_zones pipeline.
    pass

    return pd.DataFrame(boxes)
