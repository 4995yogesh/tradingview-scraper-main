import React, { useMemo, useState, useEffect } from 'react';
import { X, BrainCircuit, TrendingUp, TrendingDown, Minus, Zap, ChevronDown, ChevronRight, Users } from 'lucide-react';

/**
 * MLDebugPanel v3 — Explainable ML sidebar + Human vs Model comparison.
 *
 * New in v3:
 *   - "Model vs You" collapsible section (agreement %, accuracies, disagreement count)
 *   - "Show disagreements only" filter toggle in header
 *   - ZoneCard shows user_label badge alongside ml_label
 */

const LABEL_CONFIG = {
  GOOD:    { icon: TrendingUp,   color: '#26A69A', bg: '#0d3730' },
  BAD:     { icon: TrendingDown, color: '#EF5350', bg: '#3b0d0d' },
  NEUTRAL: { icon: Minus,        color: '#90CAF9', bg: '#1a2035' },
};

// ── Score bar ─────────────────────────────────────────────────────────────────

const ScoreBar = ({ score }) => {
  const pct   = Math.round((score || 0) * 100);
  const color = score >= 0.6 ? '#26A69A' : score < 0.35 ? '#EF5350' : '#FFB86C';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <div style={{ flex: 1, height: '4px', background: '#2A2E39', borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: '2px', transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontSize: '10px', color, fontWeight: 700, minWidth: '28px', textAlign: 'right' }}>{pct}%</span>
    </div>
  );
};

// ── Feature contribution bars ─────────────────────────────────────────────────

const ContribBar = ({ name, impact, maxImpact }) => {
  const isPositive = impact >= 0;
  const color      = isPositive ? '#26A69A' : '#EF5350';
  const barPct     = maxImpact > 0 ? Math.abs(impact) / maxImpact * 100 : 0;
  const sign       = isPositive ? '+' : '';
  return (
    <div style={{ marginBottom: '5px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px', fontSize: '9px' }}>
        <span style={{ color: '#A0A4B0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '130px' }}>
          {name}
        </span>
        <span style={{ color, fontFamily: 'monospace', fontWeight: 600 }}>
          {sign}{impact.toFixed(4)}
        </span>
      </div>
      <div style={{ height: '3px', background: '#2A2E39', borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(barPct, 100)}%`, height: '100%', background: color, borderRadius: '2px', opacity: 0.85 }} />
      </div>
    </div>
  );
};

// ── User label badge ──────────────────────────────────────────────────────────

const UserBadge = ({ userLabel, mlLabel }) => {
  if (!userLabel) return null;
  const cfg    = LABEL_CONFIG[userLabel] || LABEL_CONFIG.NEUTRAL;
  const agree  = userLabel === mlLabel;
  return (
    <span style={{
      fontSize: '8px', fontWeight: 700,
      padding: '1px 5px', borderRadius: '3px',
      background: cfg.bg, color: cfg.color,
      border: `1px solid ${cfg.color}40`,
      display: 'inline-flex', alignItems: 'center', gap: '3px',
    }}>
      {agree ? '✓' : '⚠'} You: {userLabel}
    </span>
  );
};

// ── Individual zone card ──────────────────────────────────────────────────────

const ZoneCard = ({ zone }) => {
  const label     = zone.ml_label      || 'NEUTRAL';
  const score     = zone.ml_score      || 0.5;
  const conf      = zone.ml_confidence || 0;
  const cfg       = LABEL_CONFIG[label] || LABEL_CONFIG.NEUTRAL;
  const Icon      = cfg.icon;
  const topFeats  = zone.ml_top_features || [];
  const userLabel = zone.user_label || null;
  const maxImpact = topFeats.reduce((m, f) => Math.max(m, Math.abs(f.impact)), 0);

  // Pattern: prefer ML classifier output, fall back to human-labeled pattern_type
  const patternPred   = zone.pattern_prediction || null;
  const patternConf   = zone.pattern_confidence || 0;
  const patternLabel  = patternPred || zone.pattern_type || null;
  const isMLPattern   = !!patternPred;  // true if from classifier, false if from user label

  const PATTERN_CONFIG = {
    CONTINUATION:  { emoji: '➡️', color: '#26A69A', label: 'CONTINUATION' },
    LIQUIDITY_GRAB: { emoji: '🎯', color: '#FFB86C', label: 'LIQUIDITY_GRAB' },
  };
  const patternCfg = PATTERN_CONFIG[patternLabel] || null;

  return (
    <div style={{
      background: '#131722',
      border: `1px solid ${cfg.color}25`,
      borderLeft: `3px solid ${cfg.color}`,
      borderRadius: '6px',
      padding: '8px 10px',
      marginBottom: '6px',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <Icon size={11} color={cfg.color} />
          <span style={{ fontSize: '10px', fontWeight: 700, color: cfg.color }}>{label}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          {userLabel && <UserBadge userLabel={userLabel} mlLabel={label} />}
          <span style={{ fontSize: '9px', color: '#787B86' }}>conf {Math.round(conf * 100)}%</span>
        </div>
      </div>

      {/* Score bar */}
      <ScoreBar score={score} />

      {/* Pattern prediction badge */}
      {patternCfg && (
        <div style={{ marginTop: '5px', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '3px',
            fontSize: '8px', fontWeight: 700,
            padding: '1px 6px', borderRadius: '3px',
            background: `${patternCfg.color}18`,
            border: `1px solid ${patternCfg.color}40`,
            color: patternCfg.color,
          }}>
            {patternCfg.emoji} {patternCfg.label}
          </span>
          {isMLPattern && patternConf > 0 && (
            <span style={{ fontSize: '8px', color: '#4A4E59' }}>
              ML {Math.round(patternConf * 100)}%
            </span>
          )}
          {!isMLPattern && (
            <span style={{ fontSize: '8px', color: '#4A4E59' }}>you</span>
          )}
        </div>
      )}

      {/* Price range & structure type */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '5px', fontSize: '9px', color: '#787B86' }}>
        <span>H: <span style={{ color: '#D1D4DC' }}>{zone.priceHigh?.toFixed(5)}</span></span>
        <span>L: <span style={{ color: '#D1D4DC' }}>{zone.priceLow?.toFixed(5)}</span></span>
        <span style={{ color: '#363A45' }}>{zone.timeframe}</span>
      </div>
      <div style={{ marginTop: '2px', fontSize: '9px', color: '#787B86', display: 'flex', gap: '6px', alignItems: 'center' }}>
        {zone.structure_type && (() => {
          const sClr = { 'HH-HL':'#26A69A','LL-LH':'#EF5350','HH-LH':'#FFB86C','LL-HL':'#FFB86C' }[zone.structure_type] || '#787B86';
          const dir  = zone.breakout_direction === 'bullish' ? '↑ ' : zone.breakout_direction === 'bearish' ? '↓ ' : '';
          return <span style={{ background: `${sClr}18`, border: `1px solid ${sClr}40`, borderRadius: '3px', padding: '0 4px', color: sClr, fontSize: '8px', fontWeight: 700 }}>{dir}{zone.structure_type}</span>;
        })()}
      </div>

      {/* Feature contributions */}
      {topFeats.length > 0 && (
        <div style={{ borderTop: '1px solid #2A2E39', marginTop: '7px', paddingTop: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '5px', fontSize: '8px', color: '#4A4E59', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            <Zap size={8} color="#BD93F9" />
            <span>Feature Contributions</span>
          </div>
          {topFeats.map((f, i) => (
            <ContribBar key={i} name={f.name} impact={f.impact} maxImpact={maxImpact} />
          ))}
        </div>
      )}

      {topFeats.length === 0 && (
        <div style={{ marginTop: '6px', fontSize: '8px', color: '#363A45', textAlign: 'center' }}>
          No contribution data
        </div>
      )}
    </div>
  );
};

// ── Model vs You section ──────────────────────────────────────────────────────

const ModelVsYouSection = () => {
  const [open, setOpen]     = useState(true);
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const fetchStats = () => {
      fetch('http://localhost:8000/api/ml/disagreement')
        .then(r => r.json())
        .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
        .catch(() => { if (!cancelled) setLoading(false); });
    };

    fetchStats();
    const iv = setInterval(fetchStats, 30000); // 30s TTL cache refresh

    const onRefreshEvent = () => fetchStats();
    window.addEventListener('mlDebugRefresh', onRefreshEvent);

    return () => { 
      cancelled = true; 
      clearInterval(iv); 
      window.removeEventListener('mlDebugRefresh', onRefreshEvent); 
    };
  }, []);

  const stat = (label, value, color = '#D1D4DC') => (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', padding: '2px 0' }}>
      <span style={{ color: '#787B86' }}>{label}</span>
      <span style={{ color, fontWeight: 700, fontFamily: 'monospace' }}>{value ?? '—'}</span>
    </div>
  );

  return (
    <div style={{ borderTop: '1px solid #2A2E39', flexShrink: 0 }}>
      {/* Collapsible header */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: '6px',
          padding: '8px 12px', background: 'none', border: 'none', cursor: 'pointer',
          color: '#D1D4DC', textAlign: 'left',
        }}
      >
        <Users size={11} color="#BD93F9" />
        <span style={{ fontSize: '10px', fontWeight: 700, flex: 1 }}>Model vs You</span>
        {open ? <ChevronDown size={11} color="#787B86" /> : <ChevronRight size={11} color="#787B86" />}
      </button>

      {open && (
        <div style={{ padding: '0 12px 10px' }}>
          {loading && (
            <div style={{ fontSize: '9px', color: '#787B86', textAlign: 'center', padding: '8px 0' }}>
              Loading…
            </div>
          )}
          {!loading && !data && (
            <div style={{ fontSize: '9px', color: '#EF5350', textAlign: 'center', padding: '8px 0' }}>
              Backend offline
            </div>
          )}
          {!loading && data && !data.error && (
            <>
              {stat('Total rated',     data.total_rated)}
              {stat('Agreement',
                data.agreement_pct != null ? `${data.agreement_pct}%` : '—',
                data.agreement_pct >= 70 ? '#26A69A' : '#FFB86C')}
              {stat('Model accuracy',
                data.model_accuracy != null ? `${data.model_accuracy}%` : '—',
                '#90CAF9')}
              {stat('Your accuracy',
                data.user_accuracy  != null ? `${data.user_accuracy}%`  : '—',
                '#BD93F9')}
              {stat('Precision @ 0.6',
                data.precision_at_0_6 != null ? `${data.precision_at_0_6}% (${data.precision_sample_size || 0})` : '—',
                data.precision_at_0_6 >= 65 ? '#26A69A' : '#EF5350')}
              {stat('Disagreements',  data.disagreement_count, data.disagreement_count > 0 ? '#FFB86C' : '#26A69A')}

              {/* Classification breakdown */}
              {data.total_verified > 0 && (
                <div style={{ marginTop: '8px', borderTop: '1px solid #2A2E39', paddingTop: '6px' }}>
                  <div style={{ fontSize: '8px', color: '#4A4E59', textTransform: 'uppercase', letterSpacing: '0.4px', marginBottom: '5px' }}>
                    Classification
                  </div>
                  {Object.entries(data.counts || {})
                    .filter(([, v]) => v > 0)
                    .map(([k, v]) => {
                      const colorMap = {
                        AGREEMENT_CORRECT: '#26A69A',
                        MODEL_WRONG:       '#EF5350',
                        USER_WRONG:        '#FFB86C',
                        BOTH_WRONG:        '#EF5350',
                        UNVERIFIED:        '#787B86',
                        UNRATED:           '#363A45',
                      };
                      return stat(k.replace(/_/g, ' '), v, colorMap[k]);
                    })}
                </div>
              )}
            </>
          )}
          {!loading && data?.error && (
            <div style={{ fontSize: '9px', color: '#EF5350' }}>{data.error}</div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Main panel ────────────────────────────────────────────────────────────────

const MLDebugPanel = ({ zones = [], onClose, timeframe }) => {
  const [showDisagreementsOnly, setShowDisagreementsOnly] = useState(false);
  const [showPattern, setShowPattern] = useState(null); // 'CONTINUATION' | 'LIQUIDITY_GRAB' | null

  const normTf = (tf) => (tf || '').toLowerCase();

  const filtered = useMemo(() => {
    let list = zones
      .filter(z => normTf(z.timeframe) === normTf(timeframe))
      .filter(z => (z.ml_status || 'inactive') === 'active')
      .sort((a, b) => (b.ml_score || 0) - (a.ml_score || 0));

    if (showDisagreementsOnly) {
      list = list.filter(z => z.user_label && z.user_label !== z.ml_label);
    }
    if (showPattern) {
      list = list.filter(z => z.pattern_type === showPattern);
    }
    return list;
  }, [zones, timeframe, showDisagreementsOnly, showPattern]);

  const good    = filtered.filter(z => z.ml_label === 'GOOD').length;
  const bad     = filtered.filter(z => z.ml_label === 'BAD').length;
  const neutral = filtered.filter(z => z.ml_label === 'NEUTRAL').length;

  // Count total disagreements for badge
  const disagreementCount = useMemo(() =>
    zones.filter(z =>
      normTf(z.timeframe) === normTf(timeframe) &&
      z.user_label && z.user_label !== z.ml_label
    ).length,
    [zones, timeframe]
  );

  return (
    <div style={{
      position: 'absolute',
      top: 0, right: 0, bottom: 0,
      width: '252px',
      background: 'rgba(13, 17, 28, 0.95)',
      backdropFilter: 'blur(14px)',
      borderLeft: '1px solid #2A2E39',
      zIndex: 40,
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'Inter, -apple-system, sans-serif',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 12px',
        borderBottom: '1px solid #2A2E39',
        background: '#0d1117',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <BrainCircuit size={13} color="#BD93F9" />
          <span style={{ fontSize: '11px', fontWeight: 700, color: '#D1D4DC' }}>ML Explainer</span>
          <span style={{ fontSize: '9px', color: '#787B86' }}>{timeframe?.toUpperCase()}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {/* Pattern toggles */}
          <button
            onClick={() => setShowPattern(p => p === 'CONTINUATION' ? null : 'CONTINUATION')}
            title="Show only CONTINUATION"
            style={{
              display: 'flex', alignItems: 'center', gap: '3px',
              padding: '2px 6px', borderRadius: '4px', cursor: 'pointer',
              fontSize: '8px', fontWeight: 600,
              background: showPattern === 'CONTINUATION' ? '#90CAF920' : 'transparent',
              border: `1px solid ${showPattern === 'CONTINUATION' ? '#90CAF960' : '#363A45'}`,
              color: showPattern === 'CONTINUATION' ? '#90CAF9' : '#787B86',
            }}
          >➡️ C</button>
          <button
            onClick={() => setShowPattern(p => p === 'LIQUIDITY_GRAB' ? null : 'LIQUIDITY_GRAB')}
            title="Show only LIQUIDITY_GRAB"
            style={{
              display: 'flex', alignItems: 'center', gap: '3px',
              padding: '2px 6px', borderRadius: '4px', cursor: 'pointer',
              fontSize: '8px', fontWeight: 600,
              background: showPattern === 'LIQUIDITY_GRAB' ? '#FFB86C20' : 'transparent',
              border: `1px solid ${showPattern === 'LIQUIDITY_GRAB' ? '#FFB86C60' : '#363A45'}`,
              color: showPattern === 'LIQUIDITY_GRAB' ? '#FFB86C' : '#787B86',
            }}
          >🎯 L</button>
          
          {/* Disagreement filter toggle */}
          <button
            onClick={() => setShowDisagreementsOnly(v => !v)}
            title="Show disagreements only"
            style={{
              display: 'flex', alignItems: 'center', gap: '3px',
              padding: '2px 6px', borderRadius: '4px', cursor: 'pointer',
              fontSize: '8px', fontWeight: 600,
              background: showDisagreementsOnly ? '#FFB86C20' : 'transparent',
              border: `1px solid ${showDisagreementsOnly ? '#FFB86C60' : '#363A45'}`,
              color: showDisagreementsOnly ? '#FFB86C' : '#787B86',
              transition: 'all 0.15s',
            }}
          >
            ⚠ {disagreementCount > 0 && <span style={{ background: '#FFB86C', color: '#000', borderRadius: '3px', padding: '0 3px', fontSize: '7px' }}>{disagreementCount}</span>}
          </button>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#787B86', padding: '2px', lineHeight: 0 }}
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {/* Summary badges */}
      <div style={{ display: 'flex', gap: '6px', padding: '8px 12px', borderBottom: '1px solid #2A2E39', flexShrink: 0 }}>
        {[
          { label: 'GOOD',    count: good,    color: '#26A69A' },
          { label: 'BAD',     count: bad,     color: '#EF5350' },
          { label: 'NEUTRAL', count: neutral, color: '#90CAF9' },
        ].map(({ label, count, color }) => (
          <div key={label} style={{
            flex: 1, textAlign: 'center', padding: '3px 0',
            background: `${color}15`, border: `1px solid ${color}30`,
            borderRadius: '4px', fontSize: '9px', color,
          }}>
            <div style={{ fontWeight: 700, fontSize: '14px' }}>{count}</div>
            <div style={{ opacity: 0.7 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Zone list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px' }}>
        {filtered.length === 0 ? (
          <div style={{ color: '#787B86', fontSize: '11px', textAlign: 'center', marginTop: '24px' }}>
            {showDisagreementsOnly
              ? 'No disagreements — you agree with the model!'
              : `No ML-scored zones for ${timeframe}`}
          </div>
        ) : (
          filtered.map((zone, i) => <ZoneCard key={zone.box_id || i} zone={zone} />)
        )}
      </div>

      {/* Model vs You section */}
      <ModelVsYouSection />

      {/* Footer */}
      <div style={{
        padding: '5px 12px',
        borderTop: '1px solid #2A2E39',
        fontSize: '8px', color: '#363A45',
        textAlign: 'center', flexShrink: 0,
      }}>
        ConsolidationScorer v5 · pred_contribs · pattern_classifier · {filtered.length} zones
      </div>
    </div>
  );
};

export default MLDebugPanel;
