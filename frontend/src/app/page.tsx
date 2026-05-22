'use client';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { api } from '@/lib/api';
import { gradeClass, gradeLabel, formatBytes, scoreColor, stateColor } from '@/lib/store';
import { Upload, FileText, CheckCircle, AlertTriangle, TrendingUp, Clock } from 'lucide-react';
import { motion } from 'framer-motion';

export default function Dashboard() {
  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: api.listDocuments,
    refetchInterval: 5000,
  });

  const validated = docs.filter((d) => d.state === 'VALIDATED');
  const failed    = docs.filter((d) => d.state === 'FAILED');
  const pending   = docs.filter((d) => !['VALIDATED', 'FAILED'].includes(d.state));

  const stats = [
    { label: 'Total DPRs',  value: docs.length,      icon: FileText,     color: 'var(--railway-blue-light)' },
    { label: 'Validated',   value: validated.length,  icon: CheckCircle,  color: 'var(--emerald)' },
    { label: 'Processing',  value: pending.length,    icon: Clock,        color: 'var(--amber)' },
    { label: 'Failed',      value: failed.length,     icon: AlertTriangle,color: 'var(--rose)' },
  ];

  return (
    <div>
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: 'var(--text-primary)', marginBottom: 6 }}>
          DPR Validator Dashboard
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
          Railway Detailed Project Report validation — deterministic, evidence-grounded, zero hallucination.
        </p>
      </motion.div>

      {/* Stats row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 32 }}>
        {stats.map(({ label, value, icon: Icon, color }, i) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.07 }}
            className="glass glow-hover"
            style={{ padding: '20px 24px' }}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: 32, fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, fontWeight: 500 }}>{label}</div>
              </div>
              <div style={{ padding: 10, borderRadius: 10, background: `${color}18` }}>
                <Icon size={18} color={color} />
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Quick upload CTA */}
      {docs.length === 0 && !isLoading && (
        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          className="glass"
          style={{
            padding: '48px',
            textAlign: 'center',
            marginBottom: 32,
            background: 'linear-gradient(135deg, rgba(10,61,145,0.15), rgba(21,87,204,0.08))',
          }}
        >
          <div style={{
            width: 72, height: 72, borderRadius: 20, margin: '0 auto 20px',
            background: 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 8px 32px rgba(10,61,145,0.5)',
          }}>
            <Upload size={32} color="white" />
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Upload your first DPR</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: 24, maxWidth: 400, margin: '0 auto 24px' }}>
            Upload a Railway Detailed Project Report PDF to start validation.
            Supports doubling, new line, and electrification DPRs.
          </p>
          <Link href="/upload" style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '12px 28px', borderRadius: 12,
            background: 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))',
            color: 'white', fontWeight: 600, textDecoration: 'none',
            boxShadow: '0 4px 20px rgba(10,61,145,0.4)',
            transition: 'transform 0.15s, box-shadow 0.15s',
          }}>
            <Upload size={16} /> Upload DPR
          </Link>
        </motion.div>
      )}

      {/* Documents table */}
      {docs.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="glass"
          style={{ padding: 0, overflow: 'hidden' }}
        >
          <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ fontWeight: 700, fontSize: 16 }}>Recent DPRs</h2>
            <Link href="/upload" style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '8px 16px', borderRadius: 8,
              background: 'var(--railway-blue-dim)',
              color: '#6BA3FF', fontWeight: 600, fontSize: 13, textDecoration: 'none',
              border: '1px solid rgba(21,87,204,0.3)',
            }}>
              <Upload size={14} /> Upload New
            </Link>
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Document', 'Pages', 'Size', 'State', 'Score', 'Uploaded', 'Actions'].map((h) => (
                  <th key={h} style={{
                    padding: '12px 20px', textAlign: 'left',
                    fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
                    letterSpacing: '0.05em', textTransform: 'uppercase',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 7 }).map((_, j) => (
                        <td key={j} style={{ padding: '14px 20px' }}>
                          <div className="shimmer" style={{ height: 16, width: j === 0 ? 180 : 60 }} />
                        </td>
                      ))}
                    </tr>
                  ))
                : docs.map((doc) => (
                    <tr key={doc.id} style={{ borderBottom: '1px solid var(--border)', transition: 'background 0.12s' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-2)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={{ padding: '14px 20px' }}>
                        <div style={{ fontWeight: 600, fontSize: 13, maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {doc.project_name || doc.filename}
                        </div>
                        {doc.project_route && (
                          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{doc.project_route}</div>
                        )}
                      </td>
                      <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{doc.page_count || '—'}</td>
                      <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{formatBytes(doc.file_size)}</td>
                      <td style={{ padding: '14px 20px' }}>
                        <StateChip state={doc.state} />
                      </td>
                      <td style={{ padding: '14px 20px' }}>
                        {doc.state === 'VALIDATED'
                          ? <ScorePill docId={doc.id} />
                          : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>
                        }
                      </td>
                      <td style={{ padding: '14px 20px', color: 'var(--text-muted)', fontSize: 12 }}>
                        {new Date(doc.uploaded_at).toLocaleDateString()}
                      </td>
                      <td style={{ padding: '14px 20px' }}>
                        <div style={{ display: 'flex', gap: 8 }}>
                          {doc.state === 'VALIDATED' && (
                            <Link href={`/validation/${doc.id}`} style={actionStyle('#1557CC')}>
                              Results
                            </Link>
                          )}
                          {doc.state === 'STRUCTURED' && (
                            <ValidateButton docId={doc.id} />
                          )}
                          {doc.state === 'VALIDATED' && (
                            <Link href={`/reports/${doc.id}`} style={actionStyle('#10B981')}>
                              Report
                            </Link>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </motion.div>
      )}
    </div>
  );
}

function StateChip({ state }: { state: string }) {
  const stateLabels: Record<string, string> = {
    UPLOADED: 'Uploaded', PARSING: 'Parsing…', OCR: 'OCR…',
    TABLES: 'Tables…', STRUCTURED: 'Ready', VALIDATED: 'Validated', FAILED: 'Failed',
  };
  return (
    <span className={`state-badge state-${state.toLowerCase()}`}>
      {['PARSING','OCR','TABLES'].includes(state) && <span className="pulse-blue">●</span>}
      {stateLabels[state] ?? state}
    </span>
  );
}

function ScorePill({ docId }: { docId: number }) {
  const { data } = useQuery({
    queryKey: ['validation', docId],
    queryFn: () => api.getValidationResult(docId),
    staleTime: 30_000,
  });
  if (!data) return <span className="shimmer" style={{ height: 24, width: 64, display: 'inline-block' }} />;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontWeight: 700, fontSize: 15, color: scoreColor(data.overall_score) }}>
        {data.overall_score.toFixed(1)}
      </span>
      <span className={`state-badge ${gradeClass(data.grade)}`} style={{ fontSize: 10 }}>
        {data.grade}
      </span>
    </div>
  );
}

function ValidateButton({ docId }: { docId: number }) {
  const { refetch } = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments });
  const handleValidate = async () => {
    await api.validateDocument(docId);
    setTimeout(() => refetch(), 1000);
  };
  return (
    <button onClick={handleValidate} style={actionStyle('#F59E0B')}>
      Validate
    </button>
  );
}

const actionStyle = (color: string) => ({
  padding: '5px 12px',
  borderRadius: 7,
  background: `${color}18`,
  color,
  border: `1px solid ${color}40`,
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  textDecoration: 'none',
  display: 'inline-block',
  transition: 'background 0.15s',
});
