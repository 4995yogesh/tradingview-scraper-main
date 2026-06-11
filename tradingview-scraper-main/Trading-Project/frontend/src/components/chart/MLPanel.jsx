import React, { useState, useEffect, useRef } from 'react';
import { X, Bot, ChevronRight } from 'lucide-react';

const API = 'http://127.0.0.1:8000/api/ml';

const LABEL_COLORS = {
  very_good: { bg: '#00BFA520', border: '#00BFA560', text: '#00BFA5', dot: '#00BFA5' },
  good:      { bg: '#26A69A20', border: '#26A69A60', text: '#26A69A', dot: '#26A69A' },
  bad:       { bg: '#EF535020', border: '#EF535060', text: '#EF5350', dot: '#EF5350' },
  very_bad:  { bg: '#D32F2F20', border: '#D32F2F60', text: '#D32F2F', dot: '#D32F2F' },
};

const fmt = (n) => (n != null ? (n * 100).toFixed(0) + '%' : '?');
const fmtConf = (n) => (n != null ? (n * 100).toFixed(0) + '%' : '?');
const fmtPrice = (n) => (n != null ? Number(n).toFixed(5) : '?');

export default function MLPanel({ open, onClose, onLabeled }) {
  const [boxes, setBoxes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [labeling, setLabeling] = useState({});    // { box_id: 'pending' | 'done' | null }
  const intervalRef = useRef(null);

  const fetchUncertainty = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API}/uncertainty`);
      if (res.ok) {
        const data = await res.json();
        setBoxes(data.boxes || []);
      }
    } catch (_) {}
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (!open) return;
    fetchUncertainty();
    intervalRef.current = setInterval(fetchUncertainty, 15000);
    return () => clearInterval(intervalRef.current);
  }, [open]);

  const handleLabel = async (box, label) => {
    if (labeling[box.box_id]) return;
    setLabeling(prev => ({ ...prev, [box.box_id]: 'pending' }));
    try {
      await fetch(`${API}/label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          box_id: box.box_id,
          label,
          zone: {
            timeframe:  box.timeframe,
            timeStart:  box.timeStart,
            timeEnd:    box.timeEnd,
            priceHigh:  box.priceHigh,
            priceLow:   box.priceLow,
            exchange:   box.exchange || 'OANDA',
            symbol:     box.symbol   || 'EURUSD',
          },
        }),
      });
      setLabeling(prev => ({ ...prev, [box.box_id]: 'done' }));
      onLabeled?.();
      // Refresh after brief pause
      setTimeout(fetchUncertainty, 800);
    } catch (_) {
      setLabeling(prev => ({ ...prev, [box.box_id]: null }));
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed right-0 top-[62px] bottom-[26px] w-[300px] z-40
                 bg-[#1E222D] border-l border-[#2A2E39] flex flex-col shadow-2xl"
      style={{ fontFamily: 'Inter, -apple-system, sans-serif' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2A2E39] shrink-0">
        <div className="flex items-center gap-2">
          <Bot size={14} className="text-[#2962FF]" />
          <span className="text-[12px] font-semibold text-[#D1D4DC]">Active Learning Queue</span>
          <span className="text-[10px] text-[#787B86]">
            {loading ? '…' : `${boxes.length} uncertain`}
          </span>
        </div>
        <button
          onClick={onClose}
          className="w-[22px] h-[22px] flex items-center justify-center text-[#787B86]
                     hover:text-[#D1D4DC] hover:bg-[#2A2E39] rounded transition-colors"
        >
          <X size={12} />
        </button>
      </div>

      {/* Help text */}
      <div className="px-3 py-1.5 bg-[#131722] border-b border-[#2A2E39] shrink-0">
        <p className="text-[10px] text-[#4A4E59] leading-relaxed">
          Lowest-confidence boxes first. Label to improve model accuracy.
        </p>
      </div>

      {/* Box list */}
      <div className="flex-1 overflow-y-auto">
        {boxes.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-[#4A4E59]">
            <Bot size={24} className="opacity-30" />
            <span className="text-[11px]">No uncertain boxes to label</span>
          </div>
        )}

        {boxes.map((box, idx) => {
          const score = box.score || {};
          const probs = score.probabilities || {};
          const isFallback = score.is_fallback !== false;
          const isDone = labeling[box.box_id] === 'done';
          const isPending = labeling[box.box_id] === 'pending';

          return (
            <div
              key={box.box_id || idx}
              onClick={() => window.dispatchEvent(new CustomEvent('ml-goto-box', { detail: box }))}
              title="Click to navigate chart to this box"
              className={`px-3 py-2.5 border-b border-[#2A2E39] transition-all cursor-pointer hover:bg-[#2A2E3940] ${
                isDone ? 'opacity-40' : ''
              }`}
            >
              {/* Box info row */}
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded
                                   bg-[#2962FF20] text-[#2962FF] border border-[#2962FF30]">
                    {box.timeframe?.toUpperCase()}
                  </span>
                  <span className="text-[10px] text-[#787B86]">
                    {fmtPrice(box.priceLow)} – {fmtPrice(box.priceHigh)}
                  </span>
                </div>
                {isFallback ? (
                  <span className="text-[9px] text-[#FFA726] font-medium">? unscored</span>
                ) : (
                  <span className="text-[9px] text-[#787B86]">
                    conf {fmtConf(score.confidence)}
                  </span>
                )}
              </div>

              {/* Probability bars */}
              {!isFallback && (
                <div className="flex gap-1 mb-2">
                  {[
                    { k: 'very_good', label: 'VG', color: '#00BFA5' },
                    { k: 'good',      label: 'G',  color: '#26A69A' },
                    { k: 'bad',       label: 'B',  color: '#EF5350' },
                    { k: 'very_bad',  label: 'VB', color: '#D32F2F' },
                  ].map(({ k, label, color }) => (
                    <div key={k} className="flex-1 flex flex-col gap-0.5">
                      <div className="h-[3px] rounded-full bg-[#2A2E39] overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${((probs[k] || 0) * 100).toFixed(0)}%`,
                            backgroundColor: color,
                          }}
                        />
                      </div>
                      <span className="text-[8px] text-center" style={{ color }}>
                        {label} {fmt(probs[k])}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Label buttons */}
              {isDone ? (
                <div className="text-[10px] text-[#26A69A] text-center">✓ Labeled</div>
              ) : (
                <div className="flex gap-1">
                  {[
                    { label: 'very_good', display: '++ VG', cls: 'hover:bg-[#00BFA520] hover:text-[#00BFA5] hover:border-[#00BFA560]' },
                    { label: 'good',      display: '+ G',   cls: 'hover:bg-[#26A69A20] hover:text-[#26A69A] hover:border-[#26A69A60]' },
                    { label: 'bad',       display: '- B',   cls: 'hover:bg-[#EF535020] hover:text-[#EF5350] hover:border-[#EF535060]' },
                    { label: 'very_bad',  display: '-- VB', cls: 'hover:bg-[#D32F2F20] hover:text-[#D32F2F] hover:border-[#D32F2F60]' },
                  ].map(({ label, display, cls }) => (
                    <button
                      key={label}
                      disabled={isPending}
                      onClick={() => handleLabel(box, label)}
                      className={`flex-1 text-[9px] font-medium py-1 rounded border border-[#363A45]
                                  text-[#787B86] transition-all active:scale-95 ${cls}
                                  ${isPending ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      {isPending ? '…' : display}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-[#2A2E39] shrink-0">
        <button
          onClick={fetchUncertainty}
          className="w-full text-[10px] text-[#787B86] hover:text-[#D1D4DC]
                     flex items-center justify-center gap-1 transition-colors"
        >
          Refresh queue
          <ChevronRight size={10} />
        </button>
      </div>
    </div>
  );
}
