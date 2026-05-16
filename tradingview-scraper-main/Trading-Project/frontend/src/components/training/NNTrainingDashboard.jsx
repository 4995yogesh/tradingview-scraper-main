import React, { useState, useEffect, useRef } from 'react';
import { Cpu, Activity, CheckCircle, Clock } from 'lucide-react';

const NNTrainingDashboard = ({ ml2Result }) => {
  const [data, setData] = useState({
    status: 'IDLE',
    epoch: 0,
    loss: 0,
    val_loss: 0,
    max_iterations: 500,
    updated_at: null
  });

  const lastEpochRef = useRef(0);
  const trainingStartTimeRef = useRef(null);
  const startEpochRef = useRef(0);
  const [epochDuration, setEpochDuration] = useState(null);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        // training_progress_nn has live max_iterations; nn_status is DB-only
        const [liveRes, dbRes] = await Promise.all([
          fetch('http://localhost:8000/api/training/training_progress_nn'),
          fetch('http://localhost:8000/api/training/nn_status'),
        ]);
        const live = await liveRes.json();
        const db   = await dbRes.json();

        // Merge: prefer live iteration count, use DB for persistent status
        const merged = {
          status:         live.is_training ? 'TRAINING' : (db.data?.status || live.status || 'IDLE'),
          epoch:          live.is_training ? (live.iteration || 0) : (db.data?.epoch || 0),
          loss:           live.is_training ? (live.val_logloss || 0) : (db.data?.loss || 0),
          max_iterations: live.max_iterations || 500,
          total_samples:  live.total_samples || 0,
          updated_at:     db.data?.updated_at || null,
        };

        if (merged.status === 'TRAINING' && merged.epoch > lastEpochRef.current) {
          const now = Date.now();
          if (!trainingStartTimeRef.current) {
            trainingStartTimeRef.current = now;
            startEpochRef.current = merged.epoch;
          } else {
            const totalElapsed = (now - trainingStartTimeRef.current) / 1000;
            const epochsCompleted = merged.epoch - startEpochRef.current;
            if (epochsCompleted > 0) {
              const avgDuration = totalElapsed / epochsCompleted;
              setEpochDuration(avgDuration);
            }
          }
          lastEpochRef.current = merged.epoch;
        } else if (merged.status !== 'TRAINING') {
          lastEpochRef.current = 0;
          trainingStartTimeRef.current = null;
          startEpochRef.current = 0;
          setEpochDuration(null);
        }

        setData(merged);
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

  const handleStop = async () => {
    try {
      const resp = await fetch('http://localhost:8000/api/training/stop_nn', {
        method: 'POST'
      });
      const res = await resp.json();
      if (res.status === 'stop_requested') {
        alert("Stop request sent!");
      }
    } catch (error) {
      console.error("Failed to stop training:", error);
    }
  };

  const formatTime = (secs) => {
    if (!secs) return '0s';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = Math.floor(secs % 60);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  const progress = Math.min(100, (data.epoch / (data.max_iterations || 500)) * 100);
  const remainingEpochs = (data.max_iterations || 500) - data.epoch;
  const remainingSeconds = epochDuration ? remainingEpochs * epochDuration : null;

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
        
        <div className="flex items-center gap-2">
            <button 
              onClick={handleStop}
              disabled={data.status !== 'TRAINING'}
              className={`px-3 py-1.5 rounded-lg border text-[10px] font-bold uppercase tracking-wider transition-colors ${
                data.status === 'TRAINING' 
                  ? 'bg-[#EF535020] hover:bg-[#EF535040] text-[#EF5350] border-[#EF535040]' 
                  : 'bg-[#1E222D] text-[#434651] border-[#2A2E39] cursor-not-allowed'
              }`}
            >
              Stop
            </button>
          <div className="flex items-center gap-2 bg-[#1E222D] px-3 py-1.5 rounded-lg border border-[#2A2E39]">
            <div className={`w-1.5 h-1.5 rounded-full ${data.status === 'TRAINING' ? 'bg-[#00BFA5] animate-pulse' : 'bg-[#787B86]'}`} />
            <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: getStatusColor() }}>
              {data.status}
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-6">
        {/* Progress Section */}
        <div>
          <div className="flex justify-between items-end mb-2">
            <span className="text-[11px] text-[#787B86] font-medium flex items-center gap-1.5">
              <Activity size={12} /> Training Progress
            </span>
            <span className="text-xs font-mono text-white">
              Epoch: {data.epoch} <span className="text-[#434651]">/ {data.max_iterations || 300}</span>
              <span className="mx-2 text-[#2A2E39]">|</span>
              Samples: {data.total_samples || '...'}
              <span className="mx-2 text-[#2A2E39]">|</span>
              ETA: {data.status === 'TRAINING' ? formatTime(remainingSeconds) : 'N/A'}
            </span>
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


        
        {ml2Result && ml2Result.error && (
          <div className="mt-3 text-[10px] text-[#EF5350] bg-[#FF525210] p-2 rounded-lg border border-[#FF525220] font-mono">
            Error: {ml2Result.error}
          </div>
        )}

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
              <span className="text-[10px] font-medium">Trains on all available data</span>
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
