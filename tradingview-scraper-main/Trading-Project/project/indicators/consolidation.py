import pandas as pd
import numpy as np
from typing import List, Dict

def consolidation_boxes(df: pd.DataFrame, min_bars: int = 5, fvg_threshold: float = 0.4, use_time_filter: bool = True) -> pd.DataFrame:
    """Detect consolidation boxes.
    df must have columns ['open','high','low','close'] and datetime index.
    Returns DataFrame with columns: start, end, top, bottom (indices).
    """
    boxes = []
    searchingSwings = True
    anchorIndex = 0
    gotSwingHigh = gotSwingLow = False
    swingHighVal = swingLowVal = np.nan
    firstSwingIndex = None
    active = False
    activeBox = None
    rangeTop = rangeBottom = np.nan
    fvgBlocked = False
    boxStarted = False
    for i in range(len(df)):
        if i < 2:
            continue
        row = df.iloc[i]
        prev1 = df.iloc[i-1]
        prev2 = df.iloc[i-2]
        if use_time_filter:
            hour = df.index[i].hour
            isBlockedTime = 0 <= hour < 6
        else:
            isBlockedTime = False
        isSwingHigh = prev1['high'] > prev2['high'] and prev1['high'] >= row['high']
        isSwingLow = prev1['low'] < prev2['low'] and prev1['low'] <= row['low']
        bullishFVG = row['low'] > prev2['high']
        bearishFVG = row['high'] < prev2['low']
        bullFvgSize = (row['low'] - prev2['high']) if bullishFVG else 0
        bearFvgSize = (prev2['low'] - row['high']) if bearishFVG else 0
        bodySize = abs(row['close'] - row['open'])
        smallBullFVG = bullishFVG and bullFvgSize < bodySize * fvg_threshold
        smallBearFVG = bearishFVG and bearFvgSize < bodySize * fvg_threshold
        validFVG = (bullishFVG and not smallBullFVG) or (bearishFVG and not smallBearFVG)
        if not boxStarted and validFVG and not isBlockedTime:
            fvgBlocked = True
        if searchingSwings and not active and i > anchorIndex and not isBlockedTime:
            swingBarIndex = i - 1
            if swingBarIndex > anchorIndex:
                if not gotSwingHigh and isSwingHigh:
                    gotSwingHigh = True
                    swingHighVal = prev1['high']
                    if firstSwingIndex is None:
                        firstSwingIndex = swingBarIndex
                if not gotSwingLow and isSwingLow:
                    gotSwingLow = True
                    swingLowVal = prev1['low']
                    if firstSwingIndex is None:
                        firstSwingIndex = swingBarIndex
            barsInside = None if firstSwingIndex is None else (i - firstSwingIndex + 1)
            if fvgBlocked:
                anchorIndex = i
                gotSwingHigh = gotSwingLow = False
                swingHighVal = swingLowVal = np.nan
                firstSwingIndex = None
                rangeTop = rangeBottom = np.nan
                fvgBlocked = False
                continue
            if gotSwingHigh and gotSwingLow and barsInside is not None and barsInside >= min_bars:
                rangeTop = swingHighVal
                rangeBottom = swingLowVal
                active = True
                searchingSwings = False
                boxStarted = True
                activeBox = {"start": firstSwingIndex, "end": i, "top": rangeTop, "bottom": rangeBottom}
        if active:
            breakoutUp = row['close'] > rangeTop
            breakoutDown = row['close'] < rangeBottom
            if breakoutUp or breakoutDown:
                activeBox["end"] = i - 1
                activeBox["top"] = rangeTop
                activeBox["bottom"] = rangeBottom
                boxes.append(activeBox)
                active = False
                activeBox = None
                rangeTop = rangeBottom = np.nan
                searchingSwings = False
                boxStarted = False
            else:
                rangeTop = max(rangeTop, row['high'])
                rangeBottom = min(rangeBottom, row['low'])
                activeBox["end"] = i
                activeBox["top"] = rangeTop
                activeBox["bottom"] = rangeBottom
    return pd.DataFrame(boxes)
