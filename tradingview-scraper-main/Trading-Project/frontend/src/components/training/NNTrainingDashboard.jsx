import React, { useState, useEffect } from 'react';
import { Cpu, Activity, CheckCircle, Clock } from 'lucide-react';

const NNTrainingDashboard = () => {
  const [data, setData] = useState({
    status: 'IDLE',
    epoch: 0,
    loss: 0,
    val_loss: 0,
    updated_at: null
  });

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/training/nn_status');
        const res = await response.json();
        if (res.status === 'ok' && res.data) {
          setData(res.data);
        }
      } catch (error) {
        console.error("Failed to fetch NN status:", error);
      }
    };

    fetchStatus();
    const intervalId = setInterval(fetchStatus, 3000);
    return () => clearInterval(intervalId);
  }, []);

  const getStatusColor = () => {
    switch (data.status) {
      case 'TRAINING': return '#00BFA5';
      case 'COMPLETED': return '#2962FF';
      case 'FAILED': return '#EF5350';
      default: return '#787B86';
    }
  };

  const progress = Math.min(100, (data.epoch / 100) * 100);

  return (
    <div className="bg-[#131722] border border-[#2A2E39] rounded-2xl p-5 shadow-2xl relative overflow-hidden group">
      {/* Background Glow */}
      <div className="absolute -top-24 -right-24 w-48 h-48 bg-[#2962FF] opacity-5 blur-[80px] group-hover:opacity-10 transition-opacity" />
      
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#2962FF15] flex items-center justify-center border border-[#2962FF30]">
            <Cpu size={20} className="text-[#2962FF]" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white tracking-tight">Neural Intelligence</h3>
            <p className="text-[10px] text-[#787B86] uppercase tracking-widest font-medium">Model Evolution Engine</p>
          </div>
        </div>
        
        <div className="flex items-center gap-2 bg-[#1E222D] px-3 py-1.5 rounded-lg border border-[#2A2E39]">
          <div className={`w-1.5 h-1.5 rounded-full ${data.status === 'TRAINING' ? 'bg-[#00BFA5] animate-pulse' : 'bg-[#787B86]'}`} />
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: getStatusColor() }}>
            {data.status}
          </span>
        </div>
      </div>

      <div className="space-y-6">
        {/* Progress Section */}
        <div>
          <div className="flex justify-between items-end mb-2">
            <span className="text-[11px] text-[#787B86] font-medium flex items-center gap-1.5">
              <Activity size={12} /> Training Progress
            </span>
            <span className="text-xs font-mono text-white">{data.epoch} <span className="text-[#434651]">/ 100</span></span>
          </div>
          <div className="h-1.5 w-full bg-[#1E222D] rounded-full overflow-hidden border border-[#2A2E39]">
            <div 
              className="h-full bg-gradient-to-r from-[#2962FF] to-[#00BFA5] transition-all duration-1000 ease-out shadow-[0_0_10px_rgba(41,98,255,0.4)]"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-[#0B0E14] p-3 rounded-xl border border-[#2A2E39] hover:border-[#2962FF50] transition-colors">
            <div className="text-[9px] text-[#787B86] uppercase tracking-widest mb-1 font-bold">Current Loss</div>
            <div className="text-lg font-mono font-bold text-white leading-none">
              {data.loss > 0 ? data.loss.toFixed(6) : '0.000000'}
            </div>
          </div>
          <div className="bg-[#0B0E14] p-3 rounded-xl border border-[#2A2E39] hover:border-[#2962FF50] transition-colors">
            <div className="text-[9px] text-[#787B86] uppercase tracking-widest mb-1 font-bold">Model Version</div>
            <div className="text-lg font-mono font-bold text-[#00BFA5] leading-none">
              v2.1.0
            </div>
          </div>
        </div>

        {/* Footer Info */}
        <div className="pt-4 border-t border-[#2A2E39] flex items-center justify-between">
          {data.status === 'COMPLETED' ? (
            <div className="flex items-center gap-1.5 text-[#00BFA5]">
              <CheckCircle size={14} />
              <span className="text-[10px] font-bold uppercase tracking-wider">Inference Active</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-[#787B86]">
              <Clock size={14} />
              <span className="text-[10px] font-medium">Auto-trigger at 500 labels</span>
            </div>
          )}
          <button className="text-[9px] text-[#2962FF] font-bold hover:underline uppercase tracking-widest">
            Detailed Logs
          </button>
        </div>
      </div>
    </div>
  );
};

export default NNTrainingDashboard;
