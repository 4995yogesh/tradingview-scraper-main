import React, { useState, useEffect, useRef } from 'react';
import { Activity, X, Terminal } from 'lucide-react';

const API = 'http://localhost:8000/api/ml';

export default function MLTrainingMonitor() {
  const [isOpen, setIsOpen] = useState(false);
  const [data, setData] = useState(null);
  const logsEndRef = useRef(null);

  useEffect(() => {
    const fetchProgress = async () => {
      try {
        const res = await fetch(`${API}/training_progress`);
        if (res.ok) setData(await res.json());
      } catch (e) { }
    };
    
    fetchProgress();
    const iv = setInterval(fetchProgress, 1000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (isOpen && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [data?.logs, isOpen]);

  const isTraining = data?.is_training;

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
      </button>

      {isOpen && (
        <div className="absolute top-[40px] right-[200px] w-[340px] bg-[#1E222D] border border-[#363A45] rounded-md shadow-2xl z-50 flex flex-col font-mono text-[11px] overflow-hidden">
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
                    style={{
                      width: `${data?.max_iterations > 0 ? (data.iteration / data.max_iterations) * 100 : 0}%`
                    }}
                  />
                </div>
                <div className="flex justify-between text-[#787B86]">
                  <span>Val LogLoss:</span>
                  <span className="text-[#26A69A]">{data?.val_logloss?.toFixed(4)}</span>
                </div>
              </>
            )}
          </div>

          <div className="flex-1 h-[200px] overflow-y-auto p-3 bg-[#0A0E17] text-[#A0A3AB] font-mono leading-relaxed space-y-1">
            {data?.logs?.length === 0 && <div className="italic text-[#4A4E59]">No logs available...</div>}
            {data?.logs?.map((msg, idx) => {
              const isErr = msg.toLowerCase().includes('failed') || msg.toLowerCase().includes('error');
              const isWarn = msg.toLowerCase().includes('warning') || msg.toLowerCase().includes('abort');
              
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
        </div>
      )}
    </>
  );
}
