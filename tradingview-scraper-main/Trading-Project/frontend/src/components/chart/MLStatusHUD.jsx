import React, { useState, useEffect } from 'react';
import { Bot } from 'lucide-react';

const API = 'http://127.0.0.1:8000/api/ml';

export default function MLStatusHUD({ onToggle }) {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    const fetch_ = async () => {
      try {
        const res = await fetch(`${API}/status`);
        if (res.ok) setStatus(await res.json());
      } catch (_) {}
    };
    fetch_();
    const iv = setInterval(fetch_, 10000);
    return () => clearInterval(iv);
  }, []);

  const cold   = !status || status.cold_start;
  const ver    = status?.model_version ?? null;
  const until  = status?.labels_until_retrain ?? 50;
  const total  = status?.labels_collected ?? 0;
  const prec   = status?.precision_good;

  // Progress bar fill — towards next retrain
  const unconsumed = status?.unconsumed_count ?? 0;
  const fillPct    = Math.min(100, (unconsumed / 50) * 100);

  const goodCnt = (status?.labels_by_class?.very_good || 0) + (status?.labels_by_class?.good || 0);
  const badCnt  = (status?.labels_by_class?.very_bad || 0) + (status?.labels_by_class?.bad || 0);

  return (
    <button
      id="ml-status-hud"
      onClick={onToggle}
      title="ML Scoring Panel"
      className={`flex items-center gap-1.5 h-[26px] px-2 rounded-[4px] border transition-all
                  ${cold
                    ? 'border-[#FFA72640] bg-[#FFA72610] text-[#FFA726]'
                    : 'border-[#2962FF40] bg-[#2962FF10] text-[#2962FF]'
                  } hover:brightness-125 active:scale-95`}
      style={{ fontFamily: 'Inter, monospace' }}
    >
      <Bot size={11} />
      {cold ? (
        <span className="text-[10px] font-medium whitespace-nowrap">
          {total} Lbls (<span className="text-[#00BFA5]">{goodCnt}</span>/<span className="text-[#EF5350]">{badCnt}</span>)
        </span>
      ) : (
        <span className="text-[10px] font-medium whitespace-nowrap">
          {ver} · {unconsumed}/50 (<span className="text-[#00BFA5]">{goodCnt}</span>/<span className="text-[#EF5350]">{badCnt}</span>)
          {prec != null && ` · P✓${(prec * 100).toFixed(0)}%`}
        </span>
      )}

      {/* Mini progress bar */}
      <div className="w-[28px] h-[3px] rounded-full bg-[#2A2E39] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${fillPct}%`,
            backgroundColor: cold ? '#FFA726' : '#2962FF',
          }}
        />
      </div>
    </button>
  );
}
