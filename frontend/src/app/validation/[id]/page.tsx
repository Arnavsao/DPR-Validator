'use client';
import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { api } from '@/lib/api';
import { gradeClass, gradeLabel, scoreColor } from '@/lib/store';
import { CheckCircle, XCircle, AlertTriangle, Info, BookOpen, Table2, ArrowLeft, FileText } from 'lucide-react';

export default function ValidationPage() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);

  const { data: doc } = useQuery({
    queryKey: ['doc', docId],
    queryFn: () => api.getDocument(docId),
    // Stop polling once document reaches a terminal state
    refetchInterval: (query) => {
      const d = query.state.data as typeof doc;
      if (!d) return 3000;
      return ['VALIDATED', 'FAILED'].includes(d.state) ? false : 3000;
    },
  });
  const { data: result, isError: resultError, refetch: refetchResult } = useQuery({
    queryKey: ['validation', docId],
    queryFn: () => api.getValidationResult(docId),
    enabled: !!docId,
    retry: false,  // Don't retry 404s endlessly
    refetchInterval: (query) => {
      // If we got a result, stop polling. If error or no data, poll every 5s
      // to catch when validation finishes
      return query.state.data ? false : 5000;
    },
  });
  const { data: nodes }  = useQuery({ queryKey: ['nodes', docId],      queryFn: () => api.getNodes(docId), enabled: !!docId });
  const { data: evidenceResp }  = useQuery({
    queryKey: ['evidence', docId],
    queryFn: () => api.getEvidence(docId),
    enabled: !!docId && !!result,  // Only fetch evidence when we have a validation result
    retry: false,
  });
  // Backend wraps findings in { run_id, findings: [...] } — extract the array
  const evidence = evidenceResp?.findings ?? [];

  // No validation result yet — show appropriate state
  if (!result) {
    return <NoValidationState doc={doc} docId={docId} isError={resultError} refetch={refetchResult} />;
  }

  const radarData = [
    // Use backend field names (chapter_structure, chapter_completeness) with legacy fallbacks
    { subject: 'Structure',     value: result.scores.chapter_structure   ?? result.scores.chapter    ?? 0, fullMark: 100 },
    { subject: 'Completeness',  value: result.scores.chapter_completeness ?? result.scores.subchapter ?? 0, fullMark: 100 },
    { subject: 'Tables',        value: result.scores.table               ?? 0, fullMark: 100 },
    { subject: 'Traffic',       value: result.scores.traffic             ?? 0, fullMark: 100 },
    { subject: 'Engineering',   value: result.scores.engineering         ?? 0, fullMark: 100 },
    { subject: 'Risk',          value: result.scores.risk                ?? 0, fullMark: 100 },
    { subject: 'Cost',          value: result.scores.cost                ?? 0, fullMark: 100 },
  ];

  const barData = radarData.map((d) => ({ name: d.subject, score: d.value }));
  const chapters = (nodes ?? []).filter((n) => n.node_type === 'CHAPTER');
  const critical = evidence.filter((f) => f.severity === 'critical');
  const majors   = evidence.filter((f) => f.severity === 'major');
  const infos    = evidence.filter((f) => f.severity === 'info');

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* Back */}
      <Link href="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)', textDecoration: 'none', marginBottom: 24, fontSize: 13 }}>
        <ArrowLeft size={14} /> Dashboard
      </Link>

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}>
            {doc?.project_name || doc?.filename || 'Validation Results'}
          </h1>
          <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            {doc?.division && <span>{doc.division} · </span>}
            {doc?.length_km && <span>{doc.length_km} km · </span>}
            {doc?.report_date && <span>{doc.report_date}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Link href={`/evidence/${docId}`} style={btnStyle('#1557CC')}>Evidence Viewer</Link>
          <Link href={`/reports/${docId}`} style={btnStyle('#10B981')}>Full Report</Link>
        </div>
      </motion.div>

      {/* Score hero */}
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        className="glass"
        style={{
          padding: '32px 36px', marginBottom: 24,
          background: 'linear-gradient(135deg, rgba(10,61,145,0.2), rgba(13,21,38,0.8))',
          display: 'flex', alignItems: 'center', gap: 40,
        }}
      >
        {/* Big score */}
        <div style={{ textAlign: 'center', minWidth: 130 }}>
          <div style={{
            fontSize: 64, fontWeight: 900, lineHeight: 1,
            color: scoreColor(result.overall_score),
            filter: `drop-shadow(0 0 20px ${scoreColor(result.overall_score)}60)`,
          }}>
            {result.overall_score.toFixed(1)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>Overall Score</div>
          <span className={`state-badge ${gradeClass(result.grade)}`} style={{ marginTop: 8, display: 'inline-block' }}>
            {gradeLabel(result.grade)}
          </span>
        </div>

        <div style={{ width: 1, height: 80, background: 'var(--border)' }} />

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px 32px', flex: 1 }}>
          {[
            { label: 'Chapters Found',  value: `${result.chapters_found}/${result.chapters_total}`, color: result.chapters_found === result.chapters_total ? 'var(--emerald)' : 'var(--amber)' },
            { label: 'Tables Extracted', value: result.tables_found, color: 'var(--text-primary)' },
            { label: 'Critical Issues',  value: critical.length,     color: critical.length > 0 ? 'var(--rose)' : 'var(--emerald)' },
            { label: 'Major Issues',     value: majors.length,        color: majors.length > 0 ? 'var(--amber)' : 'var(--emerald)' },
            { label: 'Pages',            value: doc?.page_count ?? '—', color: 'var(--text-primary)' },
            { label: 'Info Notes',       value: infos.length,         color: 'var(--text-secondary)' },
          ].map(({ label, value, color }) => (
            <div key={label}>
              <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </motion.div>

      {/* Charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
        {/* Radar */}
        <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.15 }} className="glass" style={{ padding: '24px' }}>
          <h3 style={{ fontWeight: 700, marginBottom: 20, fontSize: 15 }}>Score Radar</h3>
          <ResponsiveContainer width="100%" height={260}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="var(--border)" />
              <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} />
              <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} axisLine={false} />
              <Radar name="Score" dataKey="value" stroke="var(--railway-blue-light)" fill="var(--railway-blue-light)" fillOpacity={0.25} strokeWidth={2} />
            </RadarChart>
          </ResponsiveContainer>
        </motion.div>

        {/* Bar */}
        <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 }} className="glass" style={{ padding: '24px' }}>
          <h3 style={{ fontWeight: 700, marginBottom: 20, fontSize: 15 }}>Score Breakdown</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={barData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
              <XAxis type="number" domain={[0, 100]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} />
              <YAxis dataKey="name" type="category" tick={{ fill: 'var(--text-secondary)', fontSize: 11 }} width={80} />
              <Tooltip
                formatter={(v: unknown) => [`${(v as number).toFixed(1)}`, 'Score']}
                contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text-primary)' }}
              />
              <Bar dataKey="score" fill="var(--railway-blue-light)" radius={[0, 4, 4, 0]}
                label={{ position: 'right', fill: 'var(--text-muted)', fontSize: 11, formatter: (v: unknown) => (v as number).toFixed(0) }}
              />
            </BarChart>
          </ResponsiveContainer>
        </motion.div>
      </div>

      {/* Chapters + Findings */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        {/* Chapter list */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }} className="glass" style={{ padding: '24px' }}>
          <h3 style={{ fontWeight: 700, marginBottom: 16, fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
            <BookOpen size={16} /> Chapters Detected ({chapters.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 400, overflowY: 'auto' }}>
            {chapters.map((ch, i) => (
              <motion.div
                key={ch.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.03 * i }}
                className="chapter-row chapter-found"
              >
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', minWidth: 24 }}>
                  {ch.number}
                </span>
                <span style={{ flex: 1, fontSize: 12, fontWeight: 500 }}>{ch.title}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>p{ch.page_start}</span>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Findings */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass" style={{ padding: '24px' }}>
          <h3 style={{ fontWeight: 700, marginBottom: 16, fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={16} /> Findings ({evidence.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 400, overflowY: 'auto' }}>
            {evidence.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                <CheckCircle size={32} color="var(--emerald)" style={{ margin: '0 auto 8px', display: 'block' }} />
                No findings — all checks passed!
              </div>
            ) : evidence.map((f, i) => (
              <motion.div
                key={f.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.03 * i }}
                className="glass-sm"
                style={{ padding: '12px 14px' }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  <SeverityIcon severity={f.severity} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 2 }}>{f.issue}</div>
                    {f.detail && <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>{f.detail}</div>}
                    {f.page && (
                      <div style={{ fontSize: 11, color: 'var(--railway-blue-light)', marginTop: 4 }}>Page {f.page}</div>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
          {evidence.length > 0 && (
            <Link href={`/evidence/${docId}`} style={{ display: 'block', textAlign: 'center', marginTop: 12, color: 'var(--railway-blue-light)', fontSize: 13, fontWeight: 600 }}>
              View with PDF Evidence →
            </Link>
          )}
        </motion.div>
      </div>
    </div>
  );
}

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'critical') return <XCircle size={14} color="var(--rose)" style={{ flexShrink: 0, marginTop: 1 }} />;
  if (severity === 'major')    return <AlertTriangle size={14} color="var(--amber)" style={{ flexShrink: 0, marginTop: 1 }} />;
  if (severity === 'info')     return <Info size={14} color="var(--text-muted)" style={{ flexShrink: 0, marginTop: 1 }} />;
  return <Info size={14} color="#60A5FA" style={{ flexShrink: 0, marginTop: 1 }} />;
}

function NoValidationState({ doc, docId, isError, refetch }: { doc: any; docId: number; isError: boolean; refetch: () => void }) {
  const [isTriggering, setIsTriggering] = useState(false);

  const handleValidate = async () => {
    setIsTriggering(true);
    try {
      await api.validateDocument(docId);
      // Start polling for results
      setTimeout(() => refetch(), 2000);
    } catch (err) {
      console.error('Failed to trigger validation:', err);
    } finally {
      setIsTriggering(false);
    }
  };

  const isValidating = doc?.state === 'VALIDATING';
  const isStructured = doc?.state === 'STRUCTURED';
  const isFailed = doc?.state === 'FAILED';

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Link href="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)', textDecoration: 'none', marginBottom: 24, fontSize: 13 }}>
        <ArrowLeft size={14} /> Dashboard
      </Link>

      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        className="glass"
        style={{
          padding: '48px', textAlign: 'center',
          background: 'linear-gradient(135deg, rgba(10,61,145,0.15), rgba(13,21,38,0.8))',
        }}
      >
        <h1 style={{ fontSize: 22, fontWeight: 800, marginBottom: 8 }}>
          {doc?.project_name || doc?.filename || 'Document'}
        </h1>

        {isValidating && (
          <>
            <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 16 }}>
              Validation is running... This page will update automatically.
            </div>
            {doc?.current_stage && (
              <div style={{ fontSize: 13, color: 'var(--railway-blue-light)', marginBottom: 8 }}>
                {doc.current_stage}
              </div>
            )}
            {doc?.progress_percent > 0 && (
              <div style={{ maxWidth: 300, margin: '16px auto' }}>
                <div style={{ height: 6, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}>
                  <div className="pulse-blue" style={{
                    height: '100%', width: `${doc.progress_percent}%`,
                    borderRadius: 3, background: 'linear-gradient(90deg, #1557CC, #6BA3FF)',
                    transition: 'width 0.4s ease',
                  }} />
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                  {doc.progress_percent}% complete
                  {doc.estimated_remaining_seconds > 0 && ` · ~${doc.estimated_remaining_seconds}s remaining`}
                </div>
              </div>
            )}
          </>
        )}

        {(isStructured || isFailed) && (
          <>
            <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 20 }}>
              {isError
                ? 'No validation results yet. Click below to run RAG validation.'
                : 'Waiting for validation results...'}
            </div>
            {doc?.error_message && (
              <div style={{ fontSize: 12, color: 'var(--rose)', marginBottom: 16, maxWidth: 500, margin: '0 auto 16px' }}>
                Previous error: {doc.error_message}
              </div>
            )}
            <button
              onClick={handleValidate}
              disabled={isTriggering}
              style={{
                padding: '12px 28px', borderRadius: 12,
                background: isTriggering ? 'var(--surface-3)' : 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))',
                color: 'white', fontWeight: 600, fontSize: 14,
                border: 'none', cursor: isTriggering ? 'not-allowed' : 'pointer',
                boxShadow: '0 4px 20px rgba(10,61,145,0.4)',
              }}
            >
              {isTriggering ? 'Starting...' : '🚀 Run Validation'}
            </button>
          </>
        )}

        {!isValidating && !isStructured && !isFailed && (
          <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>
            Document is in &apos;{doc?.state || 'unknown'}&apos; state.
            {doc?.state && ['PARSING', 'OCR', 'TABLES'].includes(doc.state) && (
              <span> Parsing in progress — validation will start automatically when parsing completes.</span>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}

function LoadingState() {
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div className="shimmer" style={{ height: 40, width: 300, marginBottom: 24 }} />
      <div className="shimmer" style={{ height: 180, marginBottom: 24, borderRadius: 16 }} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div className="shimmer" style={{ height: 300, borderRadius: 16 }} />
        <div className="shimmer" style={{ height: 300, borderRadius: 16 }} />
      </div>
    </div>
  );
}

const btnStyle = (color: string) => ({
  padding: '9px 18px', borderRadius: 9,
  background: `${color}18`, color,
  border: `1px solid ${color}40`,
  fontSize: 13, fontWeight: 600,
  textDecoration: 'none', display: 'inline-block',
});
