'use client';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { api } from '@/lib/api';
import { gradeClass, gradeLabel, scoreColor } from '@/lib/store';
import { ArrowLeft, Download, Book, Table2, AlertTriangle, CheckCircle, XCircle } from 'lucide-react';

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);

  const { data: report, isLoading } = useQuery({
    queryKey: ['report', docId],
    queryFn: () => api.getReport(docId),
  });

  if (isLoading) return <div className="shimmer" style={{ height: 400, borderRadius: 16 }} />;
  if (!report) return <div style={{ color: 'var(--rose)', padding: 32 }}>Report not available. Run validation first.</div>;

  const { document: doc, validation: val, chapters_detected, tables_summary, findings } = report;
  const critical = findings.filter((f) => f.severity === 'critical');
  const major    = findings.filter((f) => f.severity === 'major');

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url;
    a.download = `dpr_report_${docId}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <Link href={`/validation/${docId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)', textDecoration: 'none', marginBottom: 24, fontSize: 13 }}>
        <ArrowLeft size={14} /> Back to Validation
      </Link>

      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 28, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}>Validation Report</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            Generated {new Date(report.generated_at).toLocaleString()}
          </p>
        </div>
        <button onClick={handleDownload} style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '9px 18px', borderRadius: 10,
          background: 'var(--surface-2)', border: '1px solid var(--border)',
          color: 'var(--text-secondary)', fontWeight: 600, fontSize: 13, cursor: 'pointer',
        }}>
          <Download size={14} /> Export JSON
        </button>
      </motion.div>

      {/* Document metadata */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="glass" style={{ padding: '24px 28px', marginBottom: 20 }}>
        <h2 style={{ fontWeight: 700, fontSize: 12, marginBottom: 16, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Document Information
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20 }}>
          {[
            ['Project Name',  doc.project_name  || '—'],
            ['Route',         doc.project_route || '—'],
            ['Division',      doc.division      || '—'],
            ['Length',        doc.length_km ? `${doc.length_km} km` : '—'],
            ['Report Date',   doc.report_date   || '—'],
            ['Pages',         `${doc.pages ?? '—'}`],
          ].map(([label, value]) => (
            <div key={label}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{value}</div>
            </div>
          ))}
        </div>
      </motion.div>

      {/* Score summary */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }} className="glass" style={{
        padding: '24px 28px', marginBottom: 20,
        background: 'linear-gradient(135deg, rgba(10,61,145,0.18), rgba(13,21,38,0.8))',
      }}>
        <h2 style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16 }}>
          Validation Summary
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 40, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 52, fontWeight: 900, color: scoreColor(val.overall_score), lineHeight: 1 }}>
              {val.overall_score.toFixed(1)}
            </div>
            <span className={`state-badge ${gradeClass(val.grade)}`} style={{ marginTop: 6, display: 'inline-block' }}>
              {gradeLabel(val.grade)}
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px 24px', flex: 1 }}>
            {Object.entries(val.scores).map(([key, score]) => (
              <div key={key}>
                <div style={{ fontSize: 18, fontWeight: 700, color: scoreColor(score as number) }}>
                  {(score as number).toFixed(1)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'capitalize' }}>{key}</div>
                <div className="score-bar-track" style={{ marginTop: 6 }}>
                  <div className="score-bar-fill" style={{ width: `${score}%`, background: scoreColor(score as number) }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </motion.div>

      {/* Chapters */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }} className="glass" style={{ padding: '24px 28px', marginBottom: 20 }}>
        <h2 style={{ fontWeight: 700, fontSize: 15, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Book size={16} /> Chapters Detected ({chapters_detected.length})
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
          {chapters_detected.map((ch, i) => (
            <div key={`${ch.number}-${ch.title}-${i}`} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 14px', borderRadius: 8, background: 'var(--surface-2)',
              border: '1px solid var(--border)',
            }}>
              <CheckCircle size={13} color="var(--emerald)" />
              <span style={{ fontSize: 12, fontWeight: 600, minWidth: 28, color: 'var(--text-muted)' }}>{ch.number}</span>
              <span style={{ fontSize: 12, flex: 1 }}>{ch.title}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>p{ch.page_start}</span>
            </div>
          ))}
        </div>
      </motion.div>

      {/* Tables */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }} className="glass" style={{ padding: '24px 28px', marginBottom: 20 }}>
        <h2 style={{ fontWeight: 700, fontSize: 15, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Table2 size={16} /> Tables Extracted ({tables_summary.total})
        </h2>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {Object.entries(tables_summary.by_category).map(([cat, count]) => (
            <div key={cat} style={{
              padding: '8px 16px', borderRadius: 8, background: 'var(--surface-2)',
              border: '1px solid var(--border)',
            }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{cat.replace('TableCategory.', '')}</span>
              <span style={{ fontSize: 16, fontWeight: 700, marginLeft: 10, color: 'var(--text-primary)' }}>{count as number}</span>
            </div>
          ))}
        </div>
      </motion.div>

      {/* Findings */}
      {findings.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }} className="glass" style={{ padding: '24px 28px' }}>
          <h2 style={{ fontWeight: 700, fontSize: 15, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={16} /> Findings ({findings.length})
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {findings.map((f, i) => (
              <div key={i} style={{
                padding: '14px 18px', borderRadius: 10,
                background: 'var(--surface-2)', border: '1px solid var(--border)',
                borderLeft: `3px solid ${f.severity === 'critical' ? 'var(--rose)' : f.severity === 'major' ? 'var(--amber)' : 'var(--border)'}`,
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  {f.severity === 'critical' ? <XCircle size={15} color="var(--rose)" /> : <AlertTriangle size={15} color="var(--amber)" />}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{f.issue}</div>
                    {f.detail && <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>{f.detail}</div>}
                    {f.page && <div style={{ fontSize: 11, color: 'var(--railway-blue-light)', marginTop: 6 }}>Page {f.page}</div>}
                    {f.snippet && (
                      <div style={{
                        marginTop: 10, padding: '10px 14px', borderRadius: 8,
                        background: 'var(--surface-0)', border: '1px solid var(--border)',
                        fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
                        color: 'var(--text-secondary)', lineHeight: 1.6,
                      }}>
                        {f.snippet.substring(0, 200)}{f.snippet.length > 200 ? '…' : ''}
                      </div>
                    )}
                  </div>
                  <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 6, fontWeight: 600, textTransform: 'uppercase',
                    background: f.severity === 'critical' ? 'var(--rose-dim)' : 'var(--amber-dim)',
                    color: f.severity === 'critical' ? 'var(--rose)' : 'var(--amber)',
                  }}>
                    {f.severity}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      )}
    </div>
  );
}
