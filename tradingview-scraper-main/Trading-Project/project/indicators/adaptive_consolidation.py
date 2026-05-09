import pandas as pd
import numpy as np
import os
from project.indicators.user_style_learner import UserStyleLearner

def adaptive_consolidation_boxes(
    df: pd.DataFrame,
    min_bars: int = 6,
    fvg_threshold: float = 0.4,
    use_time_filter: bool = True,
) -> pd.DataFrame:
    """Detect consolidation boxes with parameters loaded from the evolution database.
    df must have columns ['open','high','low','close'] and datetime index.
    """
    n = len(df)
    if n < 3:
        return pd.DataFrame()

    # Load parameters from UserStyleLearner
    learner = UserStyleLearner()
    params = learner.get_parameters()
    
    # Extract parameters with defaults if not present
    touch_thresh_pct = params.get('touch_thresh_pct', 0.05)
    min_touches = int(params.get('min_touches', 4))
    tightness_thresh = params.get('tightness_thresh', 0.005)
    efficiency_thresh = params.get('efficiency_thresh', 0.4)
    bias_thresh = params.get('bias_thresh', 0.3)
    
    # We can also parameterize the score weights if needed
    w_touches = 0.5
    w_efficiency = 3.0
    w_bias = 2.0

    # ── Pre-extract numpy arrays ──────────────────
    high_arr  = df["high"].to_numpy(dtype=np.float64)
    low_arr   = df["low"].to_numpy(dtype=np.float64)
    open_arr  = df["open"].to_numpy(dtype=np.float64)
    close_arr = df["close"].to_numpy(dtype=np.float64)

    if use_time_filter:
        idx = df.index
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
                activeBox["end"]    = i - 1
                activeBox["price_high"] = float(high_arr[activeBox["start"] : activeBox["end"] + 1].max())
                activeBox["price_low"]  = float(low_arr[activeBox["start"] : activeBox["end"] + 1].min())
                activeBox["time_start"] = int(pd.Timestamp(df.index[activeBox["start"]]).timestamp() * 1000)
                activeBox["time_end"]   = int(pd.Timestamp(df.index[activeBox["end"]]).timestamp() * 1000)
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
                age = i - activeBox["start"] + 1
                if age <= 5:
                    if h > rangeTop:    rangeTop    = h
                    if l < rangeBottom: rangeBottom = l
                
                activeBox["end"]    = i
                activeBox["top"]    = rangeTop
                activeBox["bottom"] = rangeBottom

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
                all_inside = True
                tempHigh   = swingHighVal
                tempLow    = swingLowVal
                current_count = 0
                
                for j in range(firstSwingIndex, i + 1):
                    pos_in_box = j - firstSwingIndex + 1

                    if tempLow <= close_arr[j] <= tempHigh:
                        if pos_in_box <= 5:
                            if low_arr[j]  < tempLow:  tempLow  = low_arr[j]
                            if high_arr[j] > tempHigh: tempHigh = high_arr[j]
                        
                        current_count += 1
                    else:
                        all_inside = False
                        break

                if all_inside and current_count >= min_bars:
                    swingHighVal    = tempHigh
                    swingLowVal     = tempLow
                    rangeTop        = swingHighVal
                    rangeBottom     = swingLowVal
                    active          = True
                    searchingSwings = False
                    boxStarted      = True
                    
                    # ── Classification & Scoring (Adaptive) ──
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
                    
                    # Use adaptive parameter for touch threshold
                    touch_thresh = rng * touch_thresh_pct
                    touches = np.sum(rangeTop - hi < touch_thresh) + np.sum(lo - rangeBottom < touch_thresh)
                    
                    score = (float(touches) * w_touches) + (float(efficiency) * w_efficiency) - (float(bias) * w_bias)
                    
                    box_type = "LOOSE"
                    # Use adaptive parameters for classification
                    if tightness < tightness_thresh and touches >= min_touches:
                        box_type = "TIGHT"
                    elif efficiency < efficiency_thresh and bias > bias_thresh:
                        box_type = "DRIFT"
                    
                    activeBox = {
                        "start": firstSwingIndex, 
                        "end": i,
                        "top": rangeTop, 
                        "bottom": rangeBottom,
                        "type": box_type,
                        "score": round(score, 2)
                    }

    return pd.DataFrame(boxes)
