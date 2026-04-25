import React, { useState, useEffect } from 'react';
import { ChevronsUp, ChevronUp, ChevronDown, ChevronsDown } from 'lucide-react';

const API = 'http://localhost:8000/api/ml';

const fmtPct = (n) => (n * 100).toFixed(0) + '%';

export default function LabelDialog({ zone, onLabeled }) {
  const [pending, setPending] = useState(null);
  const [comment, setComment] = useState(zone?.comment || "");

  useEffect(() => {
    setComment(zone?.comment || "");
  }, [zone?.box_id]);

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
          comment: comment.trim() || undefined,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        onLabeled?.({ zone, label, progress: data, comment: comment.trim() });
      }
    } catch (_) {}
    finally {
      setPending(null);
    }
  };

  return (
    <div 
      className="group flex flex-col items-center p-1 bg-[#1E222D] border border-[#363A45] rounded shadow-lg transition-all min-w-[16px] min-h-[16px]"
      style={{ fontFamily: 'Inter, sans-serif', pointerEvents: 'auto' }}
    >
      {/* COLLAPSED STATE (Tiny Dot) */}
      <div className="flex group-hover:hidden group-focus-within:hidden w-2 h-2 items-center justify-center m-[2px]">
        {curLabel ? (
          <div className={`w-2 h-2 rounded-full ${curLabel.includes('good') ? 'bg-[#00BFA5]' : 'bg-[#EF5350]'}`} />
        ) : (
          <div className="w-1.5 h-1.5 rounded-full bg-[#787B86]" />
        )}
      </div>

      {/* EXPANDED STATE (Full UI) */}
      <div className="hidden group-hover:flex group-focus-within:flex flex-col items-center gap-1 w-full min-w-[140px]">
      {isFb ? (
        <div className="text-[9px] text-[#787B86] px-1 font-medium text-center italic">
          AI Unscored (Needs 50 labels)
        </div>
      ) : (
        <div className="flex flex-col w-full px-1 border-b border-[#363A45] pb-1.5 mb-0.5">
          <div className="flex justify-between items-center text-[10px] mb-0.5">
            <span className="font-semibold text-[#D1D4DC]">AI Label:</span>
            {score.aiLabel ? (
              <span className={`font-bold capitalize ${
                score.aiLabel === 'very_good' ? 'text-[#00BFA5]' : 
                score.aiLabel === 'good' ? 'text-[#26A69A]' : 
                score.aiLabel === 'bad' ? 'text-[#EF5350]' : 'text-[#D32F2F]'
              }`}>{score.aiLabel.replace('_', ' ')}</span>
            ) : (
              <span className="text-[#787B86]">Unknown</span>
            )}
          </div>
          <div className="flex gap-1 w-full justify-between items-center bg-[#131722] rounded p-1">
            <span className="text-[8px] font-bold text-[#00BFA5]">VG {fmtPct(probs.very_good)}</span>
            <span className="text-[8px] font-bold text-[#26A69A]">G {fmtPct(probs.good)}</span>
            <span className="text-[8px] font-bold text-[#EF5350]">B {fmtPct(probs.bad)}</span>
            <span className="text-[8px] font-bold text-[#D32F2F]">VB {fmtPct(probs.very_bad)}</span>
          </div>
        </div>
      )}

      {curLabel && (
        <div className="text-[10px] text-[#D1D4DC] px-1 font-semibold capitalize flex justify-between w-full mt-1 mb-1">
          <span>Human:</span>
          <span className={curLabel === 'very_good' ? 'text-[#00BFA5]' : curLabel === 'good' ? 'text-[#26A69A]' : curLabel === 'bad' ? 'text-[#EF5350]' : 'text-[#D32F2F]'}>
            {curLabel.replace('_', ' ')}
          </span>
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-0.5">
        {[
          { label: 'very_good', icon: <ChevronsUp size={12} />, color: '#00BFA5' },
          { label: 'good', icon: <ChevronUp size={12} />, color: '#26A69A' },
          { label: 'bad', icon: <ChevronDown size={12} />, color: '#EF5350' },
          { label: 'very_bad', icon: <ChevronsDown size={12} />, color: '#D32F2F' },
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

      {/* Comment Input */}
      <textarea 
        className="w-full mt-1 p-1.5 text-[12px] bg-[#131722] text-[#D1D4DC] border border-[#363A45] rounded resize-none focus:outline-none focus:border-[#2962FF]"
        placeholder="Why is this a good/bad box?"
        rows={2}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        onKeyDown={(e) => { e.stopPropagation(); }}
        onMouseDown={(e) => { e.stopPropagation(); }}
      />
      </div>
    </div>
  );
}
