/**
 * boxEngine.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Single source of truth for all consolidation-box logic in the frontend.
 *
 * DETECTION (calculate):
 *   detectHeuristicBox(ohlc)            – fast single-pass detector (dashboard style)
 *   detectAllConsolidationBoxes(ohlc,   – full multi-box detector, port of Python
 *     { minBars, fvgThreshold,            consolidation_boxes() in
 *       useTimeFilter, istOffsetHours })   project/indicators/consolidation.py
 *
 * DRAWING (draw):
 *   drawOriginalBox(ctx, meta, coords)  – yellow dashed ground-truth box
 *   drawML2PredictionBox(ctx, ml2,      – light-blue dashed ML prediction box
 *     coords, ohlc, winStart)
 *   drawML2RefinementBox(ctx, ml2,      – teal solid ML refined box
 *     coords, ohlc, winStart)
 *   drawHeatmap(ctx, heatmap,           – neural segmentation heatmap strip
 *     ohlc, W, H, sx, cw, cg)
 *   drawHeuristicBoxes(ctx, boxes,      – draws an array of heuristic boxes
 *     ohlc, toY, sx, cw, cg)              from detectAllConsolidationBoxes()
 *   drawUserBoxes(ctx, drawBoxes,       – draws interactive user-drawn boxes
 *     getPixelCoords, activeIdx)          on the drag canvas
 *
 * SHARED HELPERS (used internally & exported for callers):
 *   isWeekendCandle(timeStr)
 *   findNearestIndex(times, targetTs)
 *   BOX_COLORS                          – canonical colour palette
 *   CHART_CONSTANTS                     – CW / CG / PAD
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ══════════════════════════════════════════════════════════════════════════════
// 1.  SHARED CONSTANTS
// ══════════════════════════════════════════════════════════════════════════════

/** Candle width (px) and gap (px) at zoom=1. */
export const CHART_CONSTANTS = {
  CW: 12,   // candle body width
  CG: 4,    // gap between candles
  PAD: { t: 40, b: 60, l: 50, r: 80 }, // canvas padding
};

/** Canonical colour palette for every box type. */
export const BOX_COLORS = {
  ORIGINAL:    { stroke: '#F7C948', fill: 'rgba(247,201,72,0.02)',  dash: [5, 3], lineWidth: 1.2 },
  ML_PREDICT:  { stroke: '#29B6F6', fill: 'rgba(41,182,246,0.02)', dash: [5, 3], lineWidth: 1.2 },
  ML_REFINED:  { stroke: '#26A69A', fill: 'rgba(38,166,154,0.04)', dash: [],     lineWidth: 2   },
  HEURISTIC:   { stroke: '#AB47BC', fill: 'rgba(171,71,188,0.04)', dash: [4, 2], lineWidth: 1   },
  TIGHT:       { stroke: '#66BB6A', fill: 'rgba(102,187,106,0.05)', dash: [],    lineWidth: 1.5 },
  LOOSE:       { stroke: '#FFA726', fill: 'rgba(255,167,38,0.04)', dash: [3, 3], lineWidth: 1   },
  DRIFT:       { stroke: '#EF5350', fill: 'rgba(239,83,80,0.04)',  dash: [2, 4], lineWidth: 1   },
  USER_ACTIVE: { stroke: '#2962FF', fill: 'rgba(41,98,255,0.10)', dash: [],      lineWidth: 1.5 },
  USER_IDLE:   { stroke: '#2962FF88', fill: 'rgba(41,98,255,0.04)', dash: [],    lineWidth: 1   },
};

// ══════════════════════════════════════════════════════════════════════════════
// 2.  SHARED HELPERS
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Returns true when the candle's timestamp falls on a Saturday or Sunday (UTC).
 * Accepts ISO strings, Unix-seconds numbers, or Date objects.
 * @param {string|number|Date} timeVal
 * @returns {boolean}
 */
export function isWeekendCandle(timeVal) {
  try {
    const d = timeVal instanceof Date ? timeVal : new Date(
      typeof timeVal === 'number' && timeVal < 2e10 ? timeVal * 1000 : timeVal
    );
    const dow = d.getUTCDay();
    return dow === 0 || dow === 6;
  } catch {
    return false;
  }
}

/**
 * Binary-search the closest index in a sorted millisecond timestamp array.
 * O(log n) replacement for the O(n) forEach loop used throughout the dashboard.
 * @param {number[]} times  – sorted array of ms timestamps
 * @param {number}   target – ms timestamp to find
 * @returns {number} index of closest match
 */
export function findNearestIndex(times, target) {
  let lo = 0, hi = times.length - 1, best = 0, bestDiff = Infinity;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const diff = Math.abs(times[mid] - target);
    if (diff < bestDiff) { bestDiff = diff; best = mid; }
    if (times[mid] < target) lo = mid + 1;
    else if (times[mid] > target) hi = mid - 1;
    else break;
  }
  return best;
}

/**
 * Convert an OHLC candle's `time` field to a millisecond timestamp.
 * Handles: ISO strings, Unix-seconds integers, Unix-ms integers.
 * @param {string|number} t
 * @returns {number} ms
 */
export function candleTimeMs(t) {
  if (typeof t === 'number') return t < 2e10 ? t * 1000 : t;
  return new Date(t).getTime();
}

/**
 * Filter ghost candles (open=high=low=close) and weekend candles from a raw
 * OHLC array.
 * @param {object[]} ohlcRaw
 * @returns {object[]}
 */
export function filterOHLC(ohlcRaw) {
  return (ohlcRaw || []).filter(c => {
    if (c.open === c.high && c.high === c.low && c.low === c.close) return false;
    if (isWeekendCandle(c.time)) return false;
    return true;
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// 3.  BOX DETECTION ALGORITHMS
// ══════════════════════════════════════════════════════════════════════════════

/**
 * FAST SINGLE-PASS HEURISTIC DETECTOR
 * ─────────────────────────────────────
 * Mirrors `detectImprovedBox()` from RefinementDashboard.jsx.
 * Finds the FIRST valid consolidation box by scanning forward through the OHLC
 * array, returns it as soon as a breakout is confirmed.
 *
 * Algorithm:
 *  1. Scan for a swing-high AND swing-low (3-bar pivot, 1-bar look-ahead).
 *  2. Once both pivots found, verify ALL subsequent closes stay inside [SL, SH].
 *     During the first 5 candles the range may expand to accommodate wicks.
 *  3. Minimum 6 qualifying candles required.
 *  4. Box terminates when a close breaks outside the range.
 *
 * @param {object[]} ohlc  – filtered OHLC array with { high, low, close, time }
 * @returns {{ start, end, top, bottom, time }|null}
 */
export function detectHeuristicBox(ohlc) {
  if (!ohlc || ohlc.length < 10) return null;

  const n = ohlc.length;
  let searchingSwings = true;
  let anchorIndex = 0;
  let gotSH = false, gotSL = false;
  let shVal = -Infinity, slVal = Infinity;
  let firstSwingIdx = null;
  let active = false;
  let rangeTop = -Infinity, rangeBottom = Infinity;
  let activeBox = null;

  for (let i = 2; i < n; i++) {
    const h  = ohlc[i].high,     l  = ohlc[i].low,  c = ohlc[i].close;
    const h1 = ohlc[i - 1].high, l1 = ohlc[i - 1].low;
    const h2 = ohlc[i - 2].high, l2 = ohlc[i - 2].low;

    const isSH = h1 > h2 && h1 >= h;
    const isSL = l1 < l2 && l1 <= l;

    // ── Active box: extend or terminate ──
    if (active) {
      const isBreakout = c > rangeTop || c < rangeBottom;
      if (isBreakout) {
        activeBox.end = i - 1;
        activeBox.top = rangeTop;
        activeBox.bottom = rangeBottom;
        return activeBox;
      }
      const age = i - activeBox.start + 1;
      if (age <= 5) {
        if (h > rangeTop)    rangeTop    = h;
        if (l < rangeBottom) rangeBottom = l;
      }
      activeBox.end    = i;
      activeBox.top    = rangeTop;
      activeBox.bottom = rangeBottom;
    }

    // ── Search phase: collect swing pivots ──
    if (searchingSwings && !active && i > anchorIndex) {
      const sbi = i - 1;
      if (sbi > anchorIndex) {
        if (!gotSH && isSH) {
          gotSH = true; shVal = h1;
          if (firstSwingIdx === null) firstSwingIdx = sbi;
        }
        if (!gotSL && isSL) {
          gotSL = true; slVal = l1;
          if (firstSwingIdx === null) firstSwingIdx = sbi;
        }
      }

      // ── Validate potential box once both pivots found ──
      if (gotSH && gotSL && firstSwingIdx !== null) {
        let allInside = true;
        let tH = shVal, tL = slVal, count = 0;

        for (let j = firstSwingIdx; j <= i; j++) {
          const age = j - firstSwingIdx + 1;
          if (ohlc[j].close >= tL && ohlc[j].close <= tH) {
            if (age <= 5) {
              if (ohlc[j].high > tH) tH = ohlc[j].high;
              if (ohlc[j].low  < tL) tL = ohlc[j].low;
            }
            count++;
          } else {
            allInside = false;
            break;
          }
        }

        if (allInside && count >= 6) {
          rangeTop    = tH;
          rangeBottom = tL;
          active          = true;
          searchingSwings = false;
          activeBox = {
            start:  firstSwingIdx,
            end:    i,
            top:    rangeTop,
            bottom: rangeBottom,
          };
        }
      }
    }
  }

  return activeBox;
}

/**
 * FULL MULTI-BOX CONSOLIDATION DETECTOR
 * ──────────────────────────────────────
 * JavaScript port of `consolidation_boxes()` from
 * `Trading-Project/project/indicators/consolidation.py`.
 *
 * Differences from the simple heuristic:
 *  • Detects ALL boxes across the full OHLC array (not just the first one).
 *  • Implements FVG (Fair Value Gap) blocking to avoid starting boxes inside
 *    impulsive moves.
 *  • Optionally filters candles in IST midnight hours (00:00–05:59).
 *  • Scores and classifies each box as TIGHT / DRIFT / LOOSE.
 *
 * @param {object[]} ohlc
 *   Array of candles: { open, high, low, close, time }
 *   `time` must be parseable to UTC ms (ISO string or Unix-seconds number).
 *
 * @param {object}  [opts]
 * @param {number}  [opts.minBars=6]           Minimum qualifying candles.
 * @param {number}  [opts.fvgThreshold=0.4]    FVG size threshold (fraction of body).
 * @param {boolean} [opts.useTimeFilter=true]  Filter IST 00:00–05:59 candles.
 * @param {number}  [opts.istOffsetHours=5.5]  UTC→IST offset in hours.
 *
 * @returns {Array<{
 *   start:  number,  // index in ohlc array
 *   end:    number,
 *   top:    number,  // price
 *   bottom: number,
 *   type:   'TIGHT'|'LOOSE'|'DRIFT',
 *   score:  number,
 *   timeStart: string,  // ISO time of ohlc[start]
 *   timeEnd:   string,
 * }>}
 */
export function detectAllConsolidationBoxes(ohlc, opts = {}) {
  const {
    minBars        = 6,
    fvgThreshold   = 0.4,
    useTimeFilter  = true,
    istOffsetHours = 5.5,
    maxConsecDir   = 4,    // Gate 1: max consecutive same-direction closes allowed
    maxNetMove     = 0.60, // Gate 2: max |close_last-close_first|/box_height allowed
  } = opts;

  const n = ohlc.length;
  if (n < 3) return [];

  // Pre-extract arrays for O(1) indexing
  const highArr  = ohlc.map(c => c.high);
  const lowArr   = ohlc.map(c => c.low);
  const openArr  = ohlc.map(c => c.open);
  const closeArr = ohlc.map(c => c.close);

  // IST hour array for time filter
  const istOffsetMs = istOffsetHours * 3600 * 1000;
  const hourArr = ohlc.map(c => {
    if (!useTimeFilter) return 0;
    try {
      const ms = candleTimeMs(c.time) + istOffsetMs;
      return new Date(ms).getUTCHours();
    } catch { return 0; }
  });

  const boxes = [];

  let searchingSwings = true;
  let anchorIndex     = 0;
  let gotSwingHigh    = false, gotSwingLow = false;
  let swingHighVal    = NaN,   swingLowVal = NaN;
  let firstSwingIndex = null;
  let active          = false;
  let activeBox       = null;
  let rangeTop        = NaN,  rangeBottom = NaN;
  let fvgBlocked      = false;
  let boxStarted      = false;

  for (let i = 2; i < n; i++) {
    const h  = highArr[i],  l  = lowArr[i];
    const o  = openArr[i],  c  = closeArr[i];
    const h1 = highArr[i-1], l1 = lowArr[i-1];
    const h2 = highArr[i-2], l2 = lowArr[i-2];

    const isBlockedTime = useTimeFilter && hourArr[i] >= 0 && hourArr[i] < 6;
    const isSwingHigh   = h1 > h2 && h1 >= h;
    const isSwingLow    = l1 < l2 && l1 <= l;

    // Fair Value Gap detection
    const bullishFVG  = l > h2;
    const bearishFVG  = h < l2;
    const bullFvgSize = bullishFVG ? l - h2 : 0;
    const bearFvgSize = bearishFVG ? l2 - h  : 0;
    const bodySize    = Math.abs(c - o);
    const smallBull   = bullishFVG && bullFvgSize < bodySize * fvgThreshold;
    const smallBear   = bearishFVG && bearFvgSize < bodySize * fvgThreshold;
    const validFVG    = (bullishFVG && !smallBull) || (bearishFVG && !smallBear);

    // ── Active box: extend or terminate ──
    if (active) {
      if (c > rangeTop || c < rangeBottom || isBlockedTime) {
        // Terminate one candle before breakout
        activeBox.end    = i - 1;
        activeBox.top    = Math.max(...highArr.slice(activeBox.start, activeBox.end + 1));
        activeBox.bottom = Math.min(...lowArr.slice(activeBox.start, activeBox.end + 1));
        boxes.push(activeBox);

        active          = false;
        activeBox       = null;
        rangeTop        = NaN; rangeBottom = NaN;
        searchingSwings = true;
        boxStarted      = false;
        gotSwingHigh    = false; gotSwingLow = false;
        swingHighVal    = NaN;  swingLowVal = NaN;
        firstSwingIndex = null;
        anchorIndex     = i;
      } else {
        const age = i - activeBox.start + 1;
        if (age <= 5) {
          if (h > rangeTop)    rangeTop    = h;
          if (l < rangeBottom) rangeBottom = l;
        }
        activeBox.end    = i;
        activeBox.top    = rangeTop;
        activeBox.bottom = rangeBottom;
      }
    }

    // Reset state in blocked time
    if (!active && isBlockedTime) {
      anchorIndex     = i;
      gotSwingHigh    = false; gotSwingLow = false;
      swingHighVal    = NaN;  swingLowVal = NaN;
      firstSwingIndex = null;
      rangeTop        = NaN;  rangeBottom = NaN;
      fvgBlocked      = false;
      boxStarted      = false;
      continue;
    }

    // Mark FVG blocker
    if (!boxStarted && validFVG && !isBlockedTime) fvgBlocked = true;

    // ── Search phase ──
    if (searchingSwings && !active && i > anchorIndex && !isBlockedTime) {
      const swingBarIndex = i - 1;
      if (swingBarIndex > anchorIndex) {
        if (!gotSwingHigh && isSwingHigh) {
          gotSwingHigh = true; swingHighVal = h1;
          if (firstSwingIndex === null) firstSwingIndex = swingBarIndex;
        }
        if (!gotSwingLow && isSwingLow) {
          gotSwingLow = true; swingLowVal = l1;
          if (firstSwingIndex === null) firstSwingIndex = swingBarIndex;
        }
      }

      // FVG blocker: flush current search
      if (fvgBlocked) {
        anchorIndex     = i;
        gotSwingHigh    = false; gotSwingLow = false;
        swingHighVal    = NaN;  swingLowVal = NaN;
        firstSwingIndex = null;
        rangeTop        = NaN;  rangeBottom = NaN;
        fvgBlocked      = false;
        continue;
      }

      // ── Validate potential box ──
      if (gotSwingHigh && gotSwingLow && firstSwingIndex !== null) {
        let allInside   = true;
        let tempHigh    = swingHighVal;
        let tempLow     = swingLowVal;
        let currentCount = 0;

        for (let j = firstSwingIndex; j <= i; j++) {
          const posInBox = j - firstSwingIndex + 1;
          if (tempLow <= closeArr[j] && closeArr[j] <= tempHigh) {
            if (posInBox <= 5) {
              if (lowArr[j]  < tempLow)  tempLow  = lowArr[j];
              if (highArr[j] > tempHigh) tempHigh = highArr[j];
            }
            currentCount++;
          } else {
            allInside = false;
            break;
          }
        }

        if (allInside && currentCount >= minBars) {
          // ── Gate 1: Max consecutive directional closes ─────────────────────
          // Walk the box chronologically and find the longest unbroken run of
          // same-direction closes. A true range oscillates; a trend runs straight.
          let maxRun = 0, curRun = 0, curDir = 0;
          for (let jj = 1; jj < currentCount; jj++) {
            // jj-th bar in the box  →  offset from end = (span-1) - jj
            // (span-1)-jj bars back = jj-th bar from firstSwingIndex
            const bOff1 = span - 1 - jj;       // bar jj
            const bOff0 = span - 1 - (jj - 1); // bar jj-1
            const diff = closeArr[closeArr.length - 1 - bOff1] -
                         closeArr[closeArr.length - 1 - bOff0];
            if (diff !== 0) {
              const dir = diff < 0 ? -1 : 1;
              if (dir === curDir) { curRun++; } else { curRun = 1; curDir = dir; }
              if (curRun > maxRun) maxRun = curRun;
            } else {
              curRun = 0;
            }
          }

          // ── Gate 2: Net displacement ratio ────────────────────────────────
          // |close_last - close_first| / box_height
          const boxHeight  = tempHigh - tempLow;
          const netMove    = Math.abs(closeArr[closeArr.length - 1] -
                                      closeArr[firstSwingIndex]);
          const netRatio   = boxHeight > 0 ? netMove / boxHeight : 0;

          const trendingBox = (maxRun >= maxConsecDir) || (netRatio > maxNetMove);

          if (!trendingBox) {
            swingHighVal = tempHigh;
            swingLowVal  = tempLow;
            rangeTop     = swingHighVal;
            rangeBottom  = swingLowVal;
            active          = true;
            searchingSwings = false;
            boxStarted      = true;

            // ── Classification & Scoring (mirrors Python logic) ──
            const sl  = closeArr.slice(firstSwingIndex, i + 1);
            const sop = openArr.slice(firstSwingIndex, i + 1);
            const shi = highArr.slice(firstSwingIndex, i + 1);
            const slo = lowArr.slice(firstSwingIndex, i + 1);

            const rng         = rangeTop - rangeBottom;
            const tightness   = rng / (sl[sl.length - 1] + 1e-9);
            const displacement = Math.abs(sl[sl.length - 1] - sl[0]);
            const pathLength  = sl.slice(1).reduce((acc, v, k) => acc + Math.abs(v - sl[k]), 0) + 1e-9;
            const efficiency  = displacement / pathLength;
            const bodyAvg     = sl.reduce((acc, v, k) => acc + Math.abs(v - sop[k]), 0) / sl.length;
            const bias        = bodyAvg / (rng + 1e-9);
            const touchThresh = rng * 0.05;
            const touches     = shi.filter(v => rangeTop - v < touchThresh).length
                              + slo.filter(v => v - rangeBottom < touchThresh).length;
            const score       = touches * 0.5 + efficiency * 3.0 - bias * 2.0;

            let boxType = 'LOOSE';
            if (tightness < 0.005 && touches >= 4) boxType = 'TIGHT';
            else if (efficiency < 0.4 && bias > 0.3) boxType = 'DRIFT';

            activeBox = {
              start:     firstSwingIndex,
              end:       i,
              top:       rangeTop,
              bottom:    rangeBottom,
              type:      boxType,
              score:     Math.round(score * 100) / 100,
              timeStart: ohlc[firstSwingIndex]?.time ?? null,
              timeEnd:   ohlc[i]?.time ?? null,
            };
          } // end !trendingBox
        } // end allInside check
      }
    }
  }

  // Flush any still-active box at end of data
  if (active && activeBox) {
    boxes.push(activeBox);
  }

  return boxes;
}

// ══════════════════════════════════════════════════════════════════════════════
// 4.  BOX DRAWING FUNCTIONS
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Internal helper — applies a colour spec from BOX_COLORS to the canvas context.
 * @param {CanvasRenderingContext2D} ctx
 * @param {{ stroke, fill, dash, lineWidth }} spec
 */
function _applyColorSpec(ctx, spec) {
  ctx.strokeStyle = spec.stroke;
  ctx.fillStyle   = spec.fill;
  ctx.lineWidth   = spec.lineWidth;
  ctx.setLineDash(spec.dash);
}

/**
 * Internal helper — draws a single box rectangle (fill + stroke).
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} bx  left x
 * @param {number} by  top y
 * @param {number} bw  width
 * @param {number} bh  height
 */
function _drawRect(ctx, bx, by, bw, bh) {
  ctx.fillRect(bx, by, bw, bh);
  ctx.strokeRect(bx, by, bw, bh);
}

/**
 * DRAW THE ORIGINAL / GROUND-TRUTH BOX
 * Yellow dashed rectangle — represents the machine-detected heuristic box
 * that was captured into the training DB.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object}   meta       – { priceHigh, priceLow, timeStart, timeEnd }
 * @param {object}   coords     – { sx, cw, cg, toY, relStart, relEnd }
 */
export function drawOriginalBox(ctx, meta, coords) {
  if (!meta) return;
  const { sx, cw, cg, toY, relStart, relEnd } = coords;

  const bx1 = sx + relStart * (cw + cg) + cw / 2;
  const bx2 = sx + relEnd   * (cw + cg) + cw / 2 + cw;
  const by1 = toY(meta.priceHigh);
  const by2 = toY(meta.priceLow);

  const bx = Math.min(bx1, bx2);
  const bw = Math.abs(bx2 - bx1);
  const by = Math.min(by1, by2);
  const bh = Math.abs(by2 - by1);

  ctx.save();
  _applyColorSpec(ctx, BOX_COLORS.ORIGINAL);
  _drawRect(ctx, bx, by, bw, bh);
  ctx.restore();
}

/**
 * DRAW THE ML2 PREDICTION BOX (light-blue dashed)
 * Shows where the ML pipeline thinks the consolidation zone is.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object}   ml2Result  – { timeStart, timeEnd, priceHigh, priceLow, confidence }
 * @param {object}   coords     – { sx, cw, cg, toY }
 * @param {object[]} ohlc       – filtered OHLC slice currently rendered
 * @param {number}   winStart   – index offset of ohlc[0] within the full array
 */
export function drawML2PredictionBox(ctx, ml2Result, coords, ohlc, winStart) {
  if (!ml2Result || ml2Result.timeStart == null || ml2Result.timeEnd == null) return;
  const { sx, cw, cg, toY } = coords;

  const times   = ohlc.map(c => candleTimeMs(c.time));
  const tsStart = candleTimeMs(ml2Result.timeStart);
  const tsEnd   = candleTimeMs(ml2Result.timeEnd);

  const mRelStart = findNearestIndex(times, tsStart) - (winStart || 0);
  const mRelEnd   = findNearestIndex(times, tsEnd)   - (winStart || 0);

  if (mRelStart < 0 || mRelEnd >= ohlc.length) return;

  const bx1 = sx + mRelStart * (cw + cg) + cw / 2;
  const bx2 = sx + mRelEnd   * (cw + cg) + cw / 2 + cw;
  const by1 = toY(ml2Result.priceHigh);
  const by2 = toY(ml2Result.priceLow);

  const bx = Math.min(bx1, bx2);
  const bw = Math.abs(bx2 - bx1);
  const by = Math.min(by1, by2);
  const bh = Math.abs(by2 - by1);

  ctx.save();
  _applyColorSpec(ctx, BOX_COLORS.ML_PREDICT);
  _drawRect(ctx, bx, by, bw, bh);
  ctx.restore();
}

/**
 * DRAW THE ML2 REFINEMENT BOX (teal solid, thicker border)
 * Only drawn when ml2Result.confidence > 0.3.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object}   ml2Result  – { timeStart, timeEnd, priceHigh, priceLow, confidence }
 * @param {object}   coords     – { sx, cw, cg, toY }
 * @param {object[]} allFiltered – the FULL (unsliced) filtered OHLC array
 * @param {number}   winStart   – index offset of the visible window within allFiltered
 */
export function drawML2RefinementBox(ctx, ml2Result, coords, allFiltered, winStart) {
  if (!ml2Result || !ml2Result.confidence || ml2Result.confidence <= 0.3) return;
  const { sx, cw, cg, toY } = coords;

  const times   = allFiltered.map(c => candleTimeMs(c.time));
  const tsStart = candleTimeMs(ml2Result.timeStart);
  const tsEnd   = candleTimeMs(ml2Result.timeEnd);

  const sIdx = findNearestIndex(times, tsStart) - (winStart || 0);
  const eIdx = findNearestIndex(times, tsEnd)   - (winStart || 0);

  const mx1 = sx + sIdx * (cw + cg) + cw / 2;
  const mx2 = sx + eIdx * (cw + cg) + cw / 2 + cw;
  const my1 = toY(ml2Result.priceHigh);
  const my2 = toY(ml2Result.priceLow);

  ctx.save();
  _applyColorSpec(ctx, BOX_COLORS.ML_REFINED);
  ctx.strokeRect(
    Math.min(mx1, mx2), Math.min(my1, my2),
    Math.abs(mx2 - mx1), Math.abs(my2 - my1)
  );
  ctx.restore();
}

/**
 * DRAW THE NEURAL SEGMENTATION HEATMAP STRIP
 * A colour-coded bar below the chart indicating ML attention per candle.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number[]} heatmap – probability values [0..1], one per candle
 * @param {object[]} ohlc    – rendered OHLC slice
 * @param {number}   W       – canvas width
 * @param {number}   H       – canvas height
 * @param {number}   sx      – x-origin of the first candle
 * @param {number}   cw      – candle width
 * @param {number}   cg      – candle gap
 */
export function drawHeatmap(ctx, heatmap, ohlc, W, H, sx, cw, cg) {
  if (!heatmap || heatmap.length === 0) return;
  const { b: padB } = CHART_CONSTANTS.PAD;
  const hH = 20;
  const hY = H - padB + 15;
  const hMax = Math.max(...heatmap);

  // Container background
  ctx.fillStyle = '#0B0E14';
  ctx.fillRect(sx - 4, hY - 4, ohlc.length * (cw + cg) + 8, hH + 8);
  ctx.strokeStyle = '#363A45';
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.strokeRect(sx - 4, hY - 4, ohlc.length * (cw + cg) + 8, hH + 8);

  // Bars
  heatmap.slice(0, ohlc.length).forEach((val, i) => {
    const hX = sx + i * (cw + cg);
    let r, g, b;
    if (val < 0.5) {
      r = Math.floor(50 + val * 410); g = Math.floor(val * 100); b = 0;
    } else {
      r = 255; g = Math.floor((val - 0.5) * 510); b = Math.floor((val - 0.7) * 850);
    }
    ctx.fillStyle = `rgb(${r}, ${Math.max(0, g)}, ${Math.max(0, b)})`;
    ctx.fillRect(hX, hY, cw + cg, hH);
  });

  // Label
  ctx.fillStyle = '#D1D4DC';
  ctx.font = 'bold 10px Inter, sans-serif';
  ctx.setLineDash([]);
  ctx.fillText(`NEURAL SEGMENTATION (MAX: ${hMax.toFixed(2)})`, sx, hY - 10);
}

/**
 * DRAW HEURISTIC BOXES (output of detectAllConsolidationBoxes)
 * Renders each box with a colour matching its type (TIGHT / LOOSE / DRIFT).
 * Adds a small type label in the top-left corner of each box.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object[]} boxes  – from detectAllConsolidationBoxes()
 * @param {object[]} ohlc   – rendered OHLC slice
 * @param {Function} toY    – price → pixel-y converter
 * @param {number}   sx     – x-origin
 * @param {number}   cw     – candle width
 * @param {number}   cg     – candle gap
 */
export function drawHeuristicBoxes(ctx, boxes, ohlc, toY, sx, cw, cg) {
  if (!boxes || boxes.length === 0) return;

  boxes.forEach(box => {
    if (box.start == null || box.end == null) return;
    const si = Math.max(0, Math.min(box.start, ohlc.length - 1));
    const ei = Math.max(0, Math.min(box.end,   ohlc.length - 1));

    const bx1 = sx + si * (cw + cg) + cw / 2;
    const bx2 = sx + ei * (cw + cg) + cw / 2 + cw;
    const by1 = toY(box.top);
    const by2 = toY(box.bottom);

    const bx = Math.min(bx1, bx2);
    const bw = Math.abs(bx2 - bx1);
    const by = Math.min(by1, by2);
    const bh = Math.abs(by2 - by1);

    const spec = BOX_COLORS[box.type] ?? BOX_COLORS.HEURISTIC;

    ctx.save();
    _applyColorSpec(ctx, spec);
    _drawRect(ctx, bx, by, bw, bh);

    // Type label
    ctx.setLineDash([]);
    ctx.font = 'bold 9px monospace';
    ctx.fillStyle = spec.stroke;
    const label = `${box.type || 'ZONE'}${box.score != null ? ` (${box.score})` : ''}`;
    ctx.fillText(label, bx + 4, by + 11);
    ctx.restore();
  });
}

/**
 * DRAW USER-DRAWN (INTERACTIVE) BOXES
 * Renders the boxes the user has drawn on the drag overlay canvas.
 * The active box gets resize handles; idle boxes are dimmer.
 *
 * @param {CanvasRenderingContext2D} ctx         – drag canvas context
 * @param {object[]}  drawBoxes                  – array of { i1, p1, i2, p2 }
 * @param {Function}  getPixelCoords             – (idx, price) → { pxX, pxY }
 * @param {number}    [activeIdx=-1]             – index of the selected box
 */
export function drawUserBoxes(ctx, drawBoxes, getPixelCoords, activeIdx = -1) {
  if (!drawBoxes || drawBoxes.length === 0) return;
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

  drawBoxes.forEach((b, i) => {
    if (!b) return;
    const isActive = i === activeIdx;
    const spec     = isActive ? BOX_COLORS.USER_ACTIVE : BOX_COLORS.USER_IDLE;

    const p1 = getPixelCoords(b.i1, b.p1);
    const p2 = getPixelCoords(b.i2, b.p2);

    const lx = Math.min(p1.pxX, p2.pxX);
    const ly = Math.min(p1.pxY, p2.pxY);
    const lw = Math.abs(p2.pxX - p1.pxX);
    const lh = Math.abs(p2.pxY - p1.pxY);

    ctx.save();
    _applyColorSpec(ctx, spec);
    ctx.fillRect(lx, ly, lw, lh);
    ctx.strokeRect(lx + 0.5, ly + 0.5, lw - 1, lh - 1);

    // Box number label
    ctx.fillStyle = spec.stroke;
    ctx.font      = 'bold 10px monospace';
    ctx.fillText(`#${i + 1}`, lx + 4, ly + 12);

    // Resize handles (active box only)
    if (isActive) {
      const hs = 5;
      const handles = [
        [p1.pxX, p1.pxY], [p2.pxX, p1.pxY],
        [p1.pxX, p2.pxY], [p2.pxX, p2.pxY],
        [(p1.pxX + p2.pxX) / 2, p1.pxY],
        [(p1.pxX + p2.pxX) / 2, p2.pxY],
        [p1.pxX, (p1.pxY + p2.pxY) / 2],
        [p2.pxX, (p1.pxY + p2.pxY) / 2],
      ];
      ctx.fillStyle   = '#ffffff';
      ctx.strokeStyle = '#2962FF';
      ctx.lineWidth   = 1;
      ctx.setLineDash([]);
      for (const [hx, hy] of handles) {
        ctx.beginPath();
        ctx.arc(hx, hy, hs, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    }

    ctx.restore();
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// 5.  CONVENIENCE: DETECT + DRAW IN ONE CALL
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Run `detectAllConsolidationBoxes` on the given OHLC slice and immediately
 * draw the results on `ctx`. Useful when you want everything in a single line.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object[]} ohlc
 * @param {Function} toY   – price → pixel-y
 * @param {number}   sx    – x-origin
 * @param {number}   cw    – candle width
 * @param {number}   cg    – candle gap
 * @param {object}  [opts] – detectAllConsolidationBoxes options
 * @returns {object[]} detected boxes (for further use)
 */
export function detectAndDrawBoxes(ctx, ohlc, toY, sx, cw, cg, opts = {}) {
  const boxes = detectAllConsolidationBoxes(ohlc, opts);
  drawHeuristicBoxes(ctx, boxes, ohlc, toY, sx, cw, cg);
  return boxes;
}
