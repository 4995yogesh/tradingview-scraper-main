import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Brain,
  Database,
  FlaskConical,
  Layers3,
  RefreshCw,
  Search,
  ShieldCheck,
  SquareArrowOutUpRight,
  TableProperties,
} from 'lucide-react';

const API = 'http://127.0.0.1:8000';

const STATUS_STYLE = {
  ready: 'text-[#26A69A] bg-[#26A69A]/10 border-[#26A69A]/30',
  in_progress: 'text-[#F7D060] bg-[#F7D060]/10 border-[#F7D060]/30',
  pending: 'text-[#787B86] bg-[#787B86]/10 border-[#787B86]/30',
  locked: 'text-[#EF5350] bg-[#EF5350]/10 border-[#EF5350]/30',
};

const MODULES = [
  {
    title: 'Chart Engine',
    description: 'Existing TradingView-like chart, live feed, overlays and multi-timeframe inspection.',
    icon: BarChart3,
    path: '/chart/EURUSD',
    status: 'ready',
  },
  {
    title: 'Multi-TF Canvas',
    description: 'Inspect synchronized market structure across multiple timeframes.',
    icon: Layers3,
    path: '/canvas',
    status: 'ready',
  },
  {
    title: 'Pattern Explorer',
    description: 'Existing historical motif explorer; later becomes embedding nearest-neighbour retrieval.',
    icon: Search,
    path: '/patterns',
    status: 'ready',
  },
  {
    title: 'Legacy Training Monitor',
    description: 'Existing supervised feedback tooling retained as a downstream baseline, not the new foundation model.',
    icon: FlaskConical,
    path: '/training',
    status: 'ready',
  },
  {
    title: 'SSL Pretraining',
    description: 'Transformer self-supervised pretraining. Locked until the Phase-1 leakage gate passes.',
    icon: Brain,
    status: 'locked',
  },
  {
    title: 'Embeddings & Retrieval',
    description: 'Embedding export, similarity search, clustering and nearest-market-pattern inspection.',
    icon: TableProperties,
    status: 'locked',
  },
];

function formatBytes(bytes = 0) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function statusLabel(value) {
  return String(value || 'unknown').replaceAll('_', ' ');
}

const StatusBadge = ({ value }) => (
  <span className={`inline-flex items-center px-2 py-1 rounded border text-[10px] font-semibold uppercase tracking-wide ${STATUS_STYLE[value] || STATUS_STYLE.pending}`}>
    {statusLabel(value)}
  </span>
);

const Metric = ({ label, value, sub }) => (
  <div className="bg-[#131722] border border-[#2A2E39] rounded-lg p-4 min-w-0">
    <div className="text-[11px] uppercase tracking-wide text-[#787B86]">{label}</div>
    <div className="mt-1 text-xl font-semibold text-[#D1D4DC] truncate">{value}</div>
    {sub && <div className="mt-1 text-[11px] text-[#787B86] truncate" title={sub}>{sub}</div>}
  </div>
);

export default function ResearchDashboard() {
  const navigate = useNavigate();
  const [health, setHealth] = useState(null);
  const [dbSummary, setDbSummary] = useState([]);
  const [research, setResearch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [healthResult, dbResult, researchResult] = await Promise.allSettled([
      fetch(`${API}/api/health`).then(r => r.ok ? r.json() : Promise.reject(new Error(`health ${r.status}`))),
      fetch(`${API}/api/db/summary`).then(r => r.ok ? r.json() : Promise.reject(new Error(`db ${r.status}`))),
      fetch(`${API}/api/ml/quality/research-status`).then(r => r.ok ? r.json() : Promise.reject(new Error(`research ${r.status}`))),
    ]);

    setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null);
    setDbSummary(dbResult.status === 'fulfilled' ? (dbResult.value.series || []) : []);
    setResearch(researchResult.status === 'fulfilled' ? researchResult.value : null);
    setLastRefresh(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const totalOperationalCandles = useMemo(
    () => dbSummary.reduce((sum, row) => sum + Number(row.candle_count || 0), 0),
    [dbSummary]
  );

  const gateRows = useMemo(() => Object.entries(research?.gates || {}), [research]);
  const phaseOneLocked = research?.gates?.transformer_pretraining !== 'ready';

  return (
    <div className="min-h-screen bg-[#0B0E14] text-[#D1D4DC]">
      <header className="sticky top-0 z-30 h-14 bg-[#000000] border-b border-[#2A2E39] flex items-center justify-between px-5">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-md bg-[#2962FF]/15 border border-[#2962FF]/40 flex items-center justify-center">
            <Brain size={18} className="text-[#5B8CFF]" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-bold text-white truncate">Candlestick Representation Learning</div>
            <div className="text-[10px] text-[#787B86] truncate">Unified local control center</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/home')}
            className="hidden sm:inline-flex px-3 py-1.5 rounded text-xs text-[#A8ADB8] hover:text-white hover:bg-[#1E222D]"
          >
            Original Home
          </button>
          <button
            onClick={refresh}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded border border-[#2A2E39] bg-[#131722] text-xs hover:border-[#5B8CFF]"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </header>

      <main className="max-w-[1500px] mx-auto p-4 md:p-6 space-y-5">
        <section className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <Metric
            label="Backend"
            value={health?.status === 'ok' ? 'Online' : 'Offline'}
            sub="FastAPI + market pipeline"
          />
          <Metric
            label="Project Phase"
            value={research?.phase || 'Phase 1'}
            sub="Data and leakage gate"
          />
          <Metric
            label="Operational Candles"
            value={totalOperationalCandles.toLocaleString()}
            sub={`${dbSummary.length} exchange/symbol/timeframe series`}
          />
          <Metric
            label="Research Partitions"
            value={(research?.canonical_partitions ?? 0).toLocaleString()}
            sub={formatBytes(research?.canonical_bytes || 0)}
          />
          <Metric
            label="Pretraining"
            value={phaseOneLocked ? 'Locked' : 'Ready'}
            sub={phaseOneLocked ? 'Pass Phase-1 gate first' : 'Data gate passed'}
          />
        </section>

        <section className="grid xl:grid-cols-[1.35fr_0.65fr] gap-4">
          <div className="bg-[#0F131B] border border-[#2A2E39] rounded-xl p-4">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="text-sm font-semibold text-white">Workspace</h2>
                <p className="text-[11px] text-[#787B86] mt-1">Open every existing and future project surface from here.</p>
              </div>
              <Activity size={18} className="text-[#5B8CFF]" />
            </div>

            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
              {MODULES.map(module => {
                const Icon = module.icon;
                const disabled = !module.path;
                return (
                  <button
                    key={module.title}
                    disabled={disabled}
                    onClick={() => module.path && navigate(module.path)}
                    className={`text-left rounded-lg border p-4 transition-all ${
                      disabled
                        ? 'border-[#242936] bg-[#11151D] cursor-not-allowed opacity-70'
                        : 'border-[#2A2E39] bg-[#131722] hover:border-[#5B8CFF] hover:-translate-y-0.5'
                    }`}
                  >
                    <div className="flex justify-between gap-3">
                      <div className="w-8 h-8 rounded bg-[#1B2130] flex items-center justify-center">
                        <Icon size={16} className="text-[#9CB5FF]" />
                      </div>
                      <StatusBadge value={module.status} />
                    </div>
                    <div className="mt-3 text-sm font-semibold text-[#E4E7ED]">{module.title}</div>
                    <div className="mt-1 text-[11px] leading-relaxed text-[#787B86]">{module.description}</div>
                    {module.path && (
                      <div className="mt-3 flex items-center gap-1 text-[10px] font-semibold text-[#5B8CFF]">
                        Open <SquareArrowOutUpRight size={11} />
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="bg-[#0F131B] border border-[#2A2E39] rounded-xl p-4">
            <div className="flex items-center gap-2 mb-4">
              <ShieldCheck size={17} className="text-[#F7D060]" />
              <div>
                <h2 className="text-sm font-semibold text-white">Research Gates</h2>
                <p className="text-[10px] text-[#787B86] mt-0.5">No model stage is marked ready unless its prerequisite exists.</p>
              </div>
            </div>

            <div className="space-y-2">
              {gateRows.length ? gateRows.map(([name, status]) => (
                <div key={name} className="flex items-center justify-between gap-3 py-2 border-b border-[#202530] last:border-0">
                  <span className="text-[11px] text-[#A8ADB8] capitalize">{statusLabel(name)}</span>
                  <StatusBadge value={status} />
                </div>
              )) : (
                <div className="text-xs text-[#787B86]">Research status endpoint is not available yet.</div>
              )}
            </div>
          </div>
        </section>

        <section className="grid lg:grid-cols-2 gap-4">
          <div className="bg-[#0F131B] border border-[#2A2E39] rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Database size={17} className="text-[#26A69A]" />
              <h2 className="text-sm font-semibold text-white">Data Architecture</h2>
            </div>
            <div className="grid sm:grid-cols-2 gap-3 text-[11px]">
              <div className="rounded-lg bg-[#131722] border border-[#2A2E39] p-3">
                <div className="text-[#787B86]">Canonical pretraining source</div>
                <div className="mt-1 font-semibold text-[#26A69A]">{research?.training_source || 'Dukascopy BID 1m'}</div>
                <div className="mt-2 text-[#787B86]">UTC Parquet → research model pipeline</div>
              </div>
              <div className="rounded-lg bg-[#131722] border border-[#2A2E39] p-3">
                <div className="text-[#787B86]">Operational/live chart source</div>
                <div className="mt-1 font-semibold text-[#5B8CFF]">{research?.live_chart_source || 'TradingView/OANDA'}</div>
                <div className="mt-2 text-[#787B86]">RAM + SQLite → FastAPI → chart UI</div>
              </div>
            </div>
            <div className="mt-3 rounded-lg bg-[#11151D] border border-[#242936] p-3">
              <div className="text-[10px] uppercase tracking-wide text-[#787B86]">Research data root</div>
              <div className="mt-1 text-[11px] text-[#C5CAD3] break-all">{research?.research_data_root || 'Set RESEARCH_DATA_ROOT to your local/Drive-backed research data folder'}</div>
            </div>
          </div>

          <div className="bg-[#0F131B] border border-[#2A2E39] rounded-xl p-4 overflow-hidden">
            <div className="flex items-center gap-2 mb-3">
              <Database size={17} className="text-[#5B8CFF]" />
              <h2 className="text-sm font-semibold text-white">Operational Candle Store</h2>
            </div>
            <div className="max-h-64 overflow-auto border border-[#242936] rounded-lg">
              <table className="w-full text-[10px]">
                <thead className="sticky top-0 bg-[#171B24] text-[#787B86]">
                  <tr>
                    <th className="text-left px-3 py-2">Symbol</th>
                    <th className="text-left px-3 py-2">TF</th>
                    <th className="text-right px-3 py-2">Candles</th>
                  </tr>
                </thead>
                <tbody>
                  {dbSummary.map((row, idx) => (
                    <tr key={`${row.exchange}-${row.symbol}-${row.timeframe}-${idx}`} className="border-t border-[#202530]">
                      <td className="px-3 py-2 text-[#C5CAD3]">{row.exchange}:{row.symbol}</td>
                      <td className="px-3 py-2 text-[#A8ADB8]">{row.timeframe}</td>
                      <td className="px-3 py-2 text-right text-[#D1D4DC]">{Number(row.candle_count || 0).toLocaleString()}</td>
                    </tr>
                  ))}
                  {!dbSummary.length && (
                    <tr><td colSpan="3" className="px-3 py-6 text-center text-[#787B86]">No operational candle series reported.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <footer className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[10px] text-[#5F6570] pb-3">
          <span>Engine branch: {research?.engine_branch || 'agent/representation-learning-integration'}</span>
          <span>{lastRefresh ? `Last dashboard refresh: ${lastRefresh.toLocaleTimeString()}` : 'Loading status…'}</span>
        </footer>
      </main>
    </div>
  );
}
