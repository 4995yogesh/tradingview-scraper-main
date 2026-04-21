import React, { useState } from 'react';
import { Check, XCircle, Minus } from 'lucide-react';

const API = 'http://localhost:8000/api/ml';

const fmtPct = (n) => (n * 100).toFixed(0) + '%';

export default function LabelDialog({ zone, onLabeled }) {
  const [pending, setPending] = useState(null);

  if (!zone) return null;

  const score  = zone.score || {};
  const probs  = score.probabilities || {};
  const isFb   = score.is_fallback !== false;
  const curLabel = zone.label ?? null;

  const handleLabel = async (label) => {
    if (pending) return;
    setPending(label);
    try {
      const res = await fetch(`${API}/label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          box_id: zone.box_id,
          label,
          zone: {
            timeframe:  zone.timeframe,
            timeStart:  zone.timeStart,
            timeEnd:    zone.timeEnd,
            priceHigh:  zone.priceHigh,
            priceLow:   zone.priceLow,
            exchange:   zone.exchange || 'OANDA',
            symbol:     zone.symbol   || 'EURUSD',
          },
        }),
      });
      if (res.ok) {
        const data = await res.json();
        onLabeled?.({ zone, label, progress: data });
      }
    } catch (_) {}
    finally {
      setPending(null);
    }
  };

  return (
    <div 
      className="flex flex-col items-center gap-1 p-1 bg-[#1E222D] border border-[#363A45] rounded shadow-lg opacity-90 hover:opacity-100 transition-opacity"
      style={{ fontFamily: 'Inter, sans-serif', pointerEvents: 'auto' }}
    >
      {/* Probability bar or current label */}
      {!isFb && !curLabel && (
        <div className="flex gap-1 w-full justify-between items-center px-1">
          <span className="text-[9px] font-bold text-[#26A69A]">{fmtPct(probs.good)}</span>
          <span className="text-[9px] font-bold text-[#EF5350]">{fmtPct(probs.bad)}</span>
          <span className="text-[9px] font-bold text-[#FFA726]">{fmtPct(probs.neutral)}</span>
        </div>
      )}
      
      {curLabel && (
        <div className="text-[9px] text-[#787B86] px-1 font-medium capitalize">
          Labeled: <span className={curLabel === 'good' ? 'text-[#26A69A]' : curLabel === 'bad' ? 'text-[#EF5350]' : 'text-[#FFA726]'}>{curLabel}</span>
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-0.5">
        {[
          { label: 'good', icon: <Check size={11} />, color: '#26A69A' },
          { label: 'bad', icon: <XCircle size={11} />, color: '#EF5350' },
          { label: 'neutral', icon: <Minus size={11} />, color: '#FFA726' },
        ].map(({ label, icon, color }) => (
          <button
            key={label}
            disabled={!!pending}
            onClick={() => handleLabel(label)}
            className={`p-1 rounded transition-colors active:scale-95 ${pending === label ? 'animate-pulse' : ''}`}
            style={{ 
              color: curLabel === label ? color : '#787B86', 
              backgroundColor: curLabel === label ? `${color}20` : 'transparent' 
            }}
            onMouseEnter={e => { e.currentTarget.style.color = color; e.currentTarget.style.backgroundColor = `${color}20`; }}
            onMouseLeave={e => { e.currentTarget.style.color = curLabel === label ? color : '#787B86'; e.currentTarget.style.backgroundColor = curLabel === label ? `${color}20` : 'transparent'; }}
          >
            {icon}
          </button>
        ))}
      </div>
    </div>
  );
}
