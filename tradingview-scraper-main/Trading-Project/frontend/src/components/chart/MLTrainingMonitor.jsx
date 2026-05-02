import React, { useState, useEffect, useRef } from 'react';
import { Activity, X, Terminal, AlertTriangle, Search } from 'lucide-react';

const API = 'http://localhost:8000/api/ml';

function formatDt(dtStr, timeStartMs) {
  if (!timeStartMs) return dtStr || 'unknown';
  // Chart displays IST (UTC+5:30), convert for consistency
  const ist = new Date(timeStartMs + 5.5 * 60 * 60 * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${ist.getUTCFullYear()}-${pad(ist.getUTCMonth()+1)}-${pad(ist.getUTCDate())} ${pad(ist.getUTCHours())}:${pad(ist.getUTCMinutes())} IST`;
}

const ErrorBoxRow = ({ box, type, onSaved }) => {
  const [isExpanding, setIsExpanding] = useState(false);
  const [lesson, setLesson] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const handleSaveLesson = async (e) => {
    e.stopPropagation();
    if (!lesson.trim()) return;
    setIsSaving(true);
    try {
      const payload = {
        box_id: box.box_id,
        label: box.true_label,
        zone: {
          exchange: box.exchange || 'OANDA',
          symbol: box.symbol || 'EURUSD',
          timeframe: box.timeframe || '',
          timeStart: Math.round(Number(box.time_start_ms) || 0),
          timeEnd: Math.round(Number(box.time_end_ms) || 0),
          priceHigh: Number(box.price_high) || 0,
          priceLow: Number(box.price_low) || 0
        },
        lesson: lesson.trim()
      };
      
      console.log('ML Label submitting payload:', payload);

      const res = await fetch(`${API}/label`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        console.log('ML Label saved successfully:', box.box_id);
        setLesson('');
        setIsExpanding(false);
        setIsSuccess(true);
        if (onSaved) onSaved();
        setTimeout(() => setIsSuccess(false), 2000);
      } else {
        let errText = '';
        try { errText = await res.text(); } catch (e) { errText = '(body unavailable)'; }
        console.error('ML Label save failed:', res.status, errText);
        alert(`Save failed (Status ${res.status}): ${errText}`);
      }
    } catch (err) {
      console.error('ML Label save fetch error:', err);
      alert(`Save error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div
      className="flex flex-col gap-0.5 px-2 py-1.5 rounded bg-[#131722] border border-[#2A2E39] hover:border-[#363A45] cursor-pointer group transition-colors"
      onClick={() => {
        window.dispatchEvent(new CustomEvent('ml-goto-box', { detail: box }));
      }}
      title={`Click to navigate chart and highlight this box`}
    >
      <div className="flex items-center justify-between">
        <span className={`text-[9px] font-bold uppercase px-1 rounded ${
          type === 'fp'
            ? 'bg-[#EF535020] text-[#EF5350]'
            : 'bg-[#FFA72620] text-[#FFA726]'
        }`}>
          {type === 'fp' ? 'FP' : 'FN'}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-[#787B86] font-mono">{box.timeframe?.toUpperCase()}</span>
          {isSuccess && (
            <span className="text-[9px] text-[#26A69A] font-bold">
              Saved!
            </span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); setIsExpanding(!isExpanding); }}
            className="text-[9px] bg-[#2962FF20] text-[#2962FF] px-1.5 rounded hover:bg-[#2962FF40] transition-colors"
          >
            Lesson
          </button>
        </div>
      </div>
      <div className="flex items-center gap-1 text-[9px] font-mono text-[#D1D4DC]">
        <Search size={8} className="text-[#2962FF] shrink-0 group-hover:scale-110 transition-transform" />
        {formatDt(box.datetime, box.time_start_ms)}
      </div>
      <div className="flex items-center justify-between text-[9px] font-mono text-[#787B86]">
        <span>True: <span className="text-[#26A69A]">{box.true_label}</span></span>
        <span>Pred: <span className="text-[#EF5350]">{box.pred_label}</span></span>
      </div>
      
      {isExpanding && (
        <div className="mt-2 flex flex-col gap-1.5" onClick={e => e.stopPropagation()}>
          <textarea
            className="w-full bg-[#1e222d] border border-[#363a45] rounded p-1.5 text-[10px] text-[#D1D4DC] focus:outline-none focus:border-[#2962FF] min-h-[50px] resize-none font-mono"
            placeholder="Why was this a mistake? (e.g. Too big, during news...)"
            value={lesson}
            onChange={e => setLesson(e.target.value)}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setIsExpanding(false)}
              className="text-[9px] text-[#787B86] hover:text-[#D1D4DC]"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveLesson}
              disabled={isSaving || !lesson.trim()}
              className="bg-[#2962FF] text-white px-2 py-0.5 rounded text-[9px] hover:bg-[#1E88E5] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSaving ? 'Saving...' : 'Save Lesson'}
            </button>
          </div>
        </div>
      )}

      <div className="text-[8px] font-mono text-[#4A4E59]">
        H:{Number(box.price_high).toFixed(5)} L:{Number(box.price_low).toFixed(5)}
      </div>
    </div>
  );
};

export default function MLTrainingMonitor() {
  const [isOpen, setIsOpen] = useState(false);
  const [data, setData] = useState(null);
  const [tab, setTab] = useState('logs'); // 'logs' | 'fp' | 'fn'
  const logsEndRef = useRef(null);

  const fetchProgress = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/training/training_progress_nn');
      if (res.ok) setData(await res.json());
    } catch (e) { }
  };

  useEffect(() => {
    fetchProgress();
    const iv = setInterval(fetchProgress, 1000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (isOpen && tab === 'logs' && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [data?.logs, isOpen, tab]);

  const isTraining = data?.is_training;
  const fp = data?.error_boxes?.fp || [];
  const fn = data?.error_boxes?.fn || [];

  return (
    <>
      <button
        onClick={() => setIsOpen(!isOpen)}
        title="Training Monitor"
        className={`flex items-center gap-1.5 h-[26px] px-2 rounded-[4px] border transition-all 
          ${isTraining ? 'border-[#26A69A40] bg-[#26A69A10] text-[#26A69A]' : 'border-[#363A45] bg-[#1E222D] text-[#787B86] hover:text-[#D1D4DC]'}
        `}
      >
        <Activity size={12} className={isTraining ? 'animate-pulse' : ''} />
        <span className="text-[10px] font-medium">Monitor</span>
        {(fp.length > 0 || fn.length > 0) && !isTraining && (
          <span className="w-4 h-4 rounded-full bg-[#EF5350] text-white text-[8px] font-bold flex items-center justify-center leading-none">
            {fp.length + fn.length}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute top-[40px] right-[200px] w-[360px] bg-[#1E222D] border border-[#363A45] rounded-md shadow-2xl z-50 flex flex-col font-mono text-[11px] overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 bg-[#2A2E39] border-b border-[#363A45]">
            <div className="flex items-center gap-2 text-[#D1D4DC]">
              <Terminal size={14} className="text-[#2962FF]" />
              <span className="font-semibold">Training Logs</span>
              {isTraining && <span className="w-2 h-2 rounded-full bg-[#26A69A] animate-pulse ml-1" />}
            </div>
            <button onClick={() => setIsOpen(false)} className="text-[#787B86] hover:text-white">
              <X size={14} />
            </button>
          </div>

          {/* Status bar */}
          <div className="p-3 bg-[#131722] flex flex-col gap-2">
            <div className="flex justify-between items-center text-[#787B86]">
              <div className="flex items-center gap-2">
                <span>Status:</span>
                <span className={isTraining ? 'text-[#26A69A]' : 'text-[#FFA726]'}>
                  {isTraining ? 'TRAINING RUNNING' : 'IDLE'}
                </span>
              </div>
              {!isTraining && (
                <button
                  onClick={async () => {
                    try { await fetch(`${API}/retrain`, { method: 'POST' }); } catch (e) { }
                  }}
                  className="px-2 py-1 bg-[#2962FF] text-white rounded-[4px] hover:bg-[#1E88E5] transition-colors"
                >
                  Force Train
                </button>
              )}
            </div>
            {isTraining && (
              <>
                <div className="flex justify-between text-[#787B86]">
                  <span>Iteration:</span>
                  <span className="text-[#D1D4DC]">
                    {data?.iteration} / {data?.max_iterations}
                    {data?.max_iterations > 0 && ` (${Math.round((data.iteration / data.max_iterations) * 100)}%)`}
                  </span>
                </div>
                <div className="h-[4px] w-full bg-[#2A2E39] rounded-full overflow-hidden my-1">
                  <div
                    className="h-full bg-[#2962FF] transition-all duration-300"
                    style={{ width: `${data?.max_iterations > 0 ? (data.iteration / data.max_iterations) * 100 : 0}%` }}
                  />
                </div>
                <div className="flex justify-between text-[#787B86]">
                  <span>Val LogLoss:</span>
                  <span className="text-[#26A69A]">{data?.val_logloss?.toFixed(4)}</span>
                </div>
              </>
            )}
          </div>

          {/* Tab bar */}
          <div className="flex border-b border-[#363A45]">
            {[
              { id: 'logs', label: 'Logs' },
              { id: 'fp', label: `FP (${fp.length})`, color: fp.length ? '#EF5350' : null },
              { id: 'fn', label: `FN (${fn.length})`, color: fn.length ? '#FFA726' : null },
            ].map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex-1 py-1.5 text-[10px] font-semibold transition-colors ${
                  tab === t.id
                    ? 'bg-[#2A2E39] text-[#D1D4DC] border-b-2 border-[#2962FF]'
                    : 'text-[#787B86] hover:text-[#D1D4DC] hover:bg-[#1A1E2A]'
                }`}
                style={tab !== t.id && t.color ? { color: t.color } : {}}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {tab === 'logs' && (
            <div className="flex-1 h-[200px] overflow-y-auto p-3 bg-[#0A0E17] text-[#A0A3AB] font-mono leading-relaxed space-y-1">
              {data?.logs?.length === 0 && <div className="italic text-[#4A4E59]">No logs available...</div>}
              {data?.logs?.map((msg, idx) => {
                const lower = msg.toLowerCase();
                const isErr = (lower.includes('failed') || lower.includes('error')) && !lower.includes('error analysis');
                const isWarn = lower.includes('warning') || lower.includes('abort');
                let color = 'text-[#D1D4DC]';
                if (isErr) color = 'text-[#EF5350] font-semibold';
                else if (isWarn) color = 'text-[#FFA726]';
                else if (msg.includes('===') || msg.includes('Promote')) color = 'text-[#2962FF] font-semibold';
                return (
                  <div key={idx} className={`${color} break-words`}>
                    <span className="text-[#4A4E59] mr-2">&gt;</span>
                    {msg}
                  </div>
                );
              })}
              <div ref={logsEndRef} />
            </div>
          )}

          {(tab === 'fp' || tab === 'fn') && (
            <div className="flex-1 h-[250px] overflow-y-auto p-2 bg-[#0A0E17] space-y-1.5">
              {tab === 'fp' && (
                <div className="flex items-center gap-1 text-[9px] text-[#787B86] mb-2">
                  <AlertTriangle size={9} className="text-[#EF5350]" />
                  Model predicted GOOD on these BAD boxes — consider relabeling
                </div>
              )}
              {tab === 'fn' && (
                <div className="flex items-center gap-1 text-[9px] text-[#787B86] mb-2">
                  <AlertTriangle size={9} className="text-[#FFA726]" />
                  Model missed these real GOOD boxes — add more similar labels
                </div>
              )}
              {(tab === 'fp' ? fp : fn).length === 0 && (
                <div className="italic text-[#4A4E59] text-[10px] text-center mt-8">
                  No {tab.toUpperCase()} boxes — run Force Train first
                </div>
              )}
              {(tab === 'fp' ? fp : fn).map((box, i) => (
                <ErrorBoxRow key={box.box_id || i} box={box} type={tab} onSaved={fetchProgress} />
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
