import pandas as pd
import numpy as np

def consolidation_boxes(
    df: pd.DataFrame,
    min_bars: int = 6,
    fvg_threshold: float = 0.4,
    use_time_filter: bool = True,
) -> pd.DataFrame:
    """Detect consolidation boxes.
    df must have columns ['open','high','low','close'] and datetime index.
    Returns DataFrame with columns: start, end, top, bottom (indices).

    Optimised: all OHLC data pre-extracted to numpy arrays so the hot loop
    does O(1) array indexing instead of slow pandas .iloc row access.
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
                activeBox["end"]    = i - 1
                activeBox["top"]    = rangeTop
                activeBox["bottom"] = rangeBottom
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


    return pd.DataFrame(boxes)
