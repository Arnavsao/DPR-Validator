'use client';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/lib/api';
import { gradeClass, gradeLabel, scoreColor } from '@/lib/store';
import {
  ArrowLeft, Download, Book, Table2, AlertTriangle,
  CheckCircle, XCircle, HelpCircle, ChevronDown, ChevronUp,
} from 'lucide-react';

// ── Status helpers ──────────────────────────────────────────────────────────

type ChapterStatus = 'PASS' | 'WARNING' | 'UNKNOWN' | 'FAIL';

const STATUS_CONFIG: Record<ChapterStatus, { icon: React.ReactNode; color: string; bg: string; label: string }> = {
  PASS:    { icon: <CheckCircle  size={13} />, color: 'var(--emerald)', bg: 'rgba(16,185,129,0.10)', label: 'Pass'    },
  WARNING: { icon: <AlertTriangle size={13} />, color: 'var(--amber)',   bg: 'rgba(245,158,11,0.10)', label: 'Warning' },
  UNKNOWN: { icon: <HelpCircle   size={13} />, color: 'var(--text-muted)', bg: 'rgba(100,116,139,0.12)', label: 'Not Validated' },
  FAIL:    { icon: <XCircle      size={13} />, color: 'var(--rose)',    bg: 'rgba(239,68,68,0.10)', label: 'Fail'    },
};

function statusCfg(status: string) {
  return STATUS_CONFIG[(status as ChapterStatus)] ?? STATUS_CONFIG.UNKNOWN;
}

// ── Chapter card (expandable) ───────────────────────────────────────────────

interface ChapterResult {
  number: number;
  title: string;
  status: string;
  score: number;
  confidence: number;
  detail: string;
  reference_section: string;
  suggested_correction: string;
  snippet: string;
}

function ChapterCard({ ch, idx }: { ch: ChapterResult; idx: number }) {
  const [open, setOpen] = useState(false);
  const cfg = statusCfg(ch.status);
  const isNotFound = ch.detail === 'Not found in uploaded document.';

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: idx * 0.018 }}
      style={{
        borderRadius: 10,
        background: isNotFound ? 'var(--surface-1)' : cfg.bg,
        border: `1px solid ${isNotFound ? 'var(--border)' : cfg.color}30`,
        overflow: 'hidden',
        opacity: isNotFound ? 0.65 : 1,
      }}
    >
      {/* Header row */}
      <button
        onClick={() => !isNotFound && setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 12,
          padding: '11px 14px', background: 'transparent', border: 'none',
          cursor: isNotFound ? 'default' : 'pointer', textAlign: 'left',
        }}
      >
        {/* Chapter number badge */}
        <span style={{
          minWidth: 26, height: 26, borderRadius: 6, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontSize: 11, fontWeight: 700,
          background: `${cfg.color}22`, color: cfg.color,
        }}>
          {ch.number}
        </span>

        {/* Status icon */}
        <span style={{ color: cfg.color, display: 'flex', alignItems: 'center', flexShrink: 0 }}>
          {cfg.icon}
        </span>

        {/* Title */}
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: isNotFound ? 'var(--text-muted)' : 'var(--text-primary)' }}>
          {ch.title}
        </span>

        {/* Score bar + label */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          <div style={{ width: 80 }}>
            <div className="score-bar-track" style={{ height: 5 }}>
              <div
                className="score-bar-fill"
                style={{ width: `${ch.score}%`, background: cfg.color, transition: 'width 0.5s ease' }}
              />
            </div>
          </div>
          <span style={{ fontSize: 12, fontWeight: 700, color: cfg.color, minWidth: 36, textAlign: 'right' }}>
            {ch.score.toFixed(0)}
          </span>
          <span style={{
            fontSize: 10, padding: '2px 7px', borderRadius: 5, fontWeight: 600,
            background: `${cfg.color}22`, color: cfg.color, textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}>
            {isNotFound ? 'Not Found' : cfg.label}
          </span>
          {!isNotFound && (
            <span style={{ color: 'var(--text-muted)', display: 'flex' }}>
              {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </span>
          )}
        </div>
      </button>

      {/* Expanded detail */}
      <AnimatePresence>
        {open && !isNotFound && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{
              padding: '0 14px 14px 52px',
              display: 'flex', flexDirection: 'column', gap: 8,
            }}>
              {ch.detail && (
                <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.6 }}>
                  {ch.detail}
                </p>
              )}
              {ch.snippet && (
                <div style={{
                  padding: '8px 12px', borderRadius: 7, fontFamily: 'JetBrains Mono, monospace',
                  fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.6,
                  background: 'var(--surface-0)', border: '1px solid var(--border)',
                }}>
                  {ch.snippet}
                </div>
              )}
              {ch.suggested_correction && ch.status !== 'PASS' && (
                <div style={{
                  padding: '8px 12px', borderRadius: 7, fontSize: 12,
                  color: 'var(--amber)', background: 'rgba(245,158,11,0.08)',
                  border: '1px solid rgba(245,158,11,0.2)',
                }}>
                  <strong>Suggested fix: </strong>{ch.suggested_correction}
                </div>
              )}
              {ch.reference_section && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  Reference: {ch.reference_section}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ── Report page ─────────────────────────────────────────────────────────────

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);

  const { data: report, isLoading } = useQuery({
    queryKey: ['report', docId],
    queryFn: () => api.getReport(docId),
  });

  if (isLoading) return <div className="shimmer" style={{ height: 400, borderRadius: 16 }} />;
  if (!report)   return <div style={{ color: 'var(--rose)', padding: 32 }}>Report not available. Run validation first.</div>;

  const { document: doc, validation: val, chapter_results, chapters_detected, tables_summary, findings } = report;
  const chapterResults: ChapterResult[] = chapter_results ?? [];
  const chaptersFound = chapterResults.filter(c => c.status !== 'FAIL' || c.detail !== 'Not found in uploaded document.').length;
  const chaptersTotal = 18;

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url;
    a.download = `dpr_report_${docId}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
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

      {/* Overall score */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.06 }} className="glass" style={{
        padding: '24px 28px', marginBottom: 20,
        background: 'linear-gradient(135deg, rgba(10,61,145,0.18), rgba(13,21,38,0.8))',
      }}>
        <h2 style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 16 }}>
          Overall Score
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 40, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 56, fontWeight: 900, color: scoreColor(val.overall_score), lineHeight: 1 }}>
              {val.overall_score.toFixed(1)}
            </div>
            <span className={`state-badge ${gradeClass(val.grade)}`} style={{ marginTop: 6, display: 'inline-block' }}>
              {gradeLabel(val.grade)}
            </span>
          </div>
          {/* Chapters coverage pill */}
          <div style={{
            padding: '16px 24px', borderRadius: 12,
            background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
          }}>
            <div style={{ fontSize: 32, fontWeight: 900, color: scoreColor((chaptersFound / chaptersTotal) * 100) }}>
              {chaptersFound}<span style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-muted)' }}> / {chaptersTotal}</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Chapters Found
            </div>
          </div>
          {/* Chapter quality score */}
          {val.scores.chapter != null && (
            <div style={{
              padding: '16px 24px', borderRadius: 12,
              background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
            }}>
              <div style={{ fontSize: 32, fontWeight: 900, color: scoreColor(val.scores.chapter ?? 0) }}>
                {(val.scores.chapter ?? 0).toFixed(1)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Chapter Quality
              </div>
            </div>
          )}
        </div>
      </motion.div>

      {/* ── Chapter-wise scorecard ── */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.10 }} className="glass" style={{ padding: '24px 28px', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h2 style={{ fontWeight: 700, fontSize: 15, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Book size={16} /> Chapter-wise Scorecard
          </h2>
          <div style={{ display: 'flex', gap: 10 }}>
            {(['PASS', 'WARNING', 'UNKNOWN', 'FAIL'] as ChapterStatus[]).map(s => {
              const cfg = STATUS_CONFIG[s];
              const count = chapterResults.filter(c => c.status === s).length;
              if (!count) return null;
              return (
                <span key={s} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '3px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
                  background: `${cfg.color}18`, color: cfg.color,
                }}>
                  {cfg.icon} {count} {cfg.label}
                </span>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {chapterResults.map((ch, i) => (
            <ChapterCard key={`${ch.number}-${ch.title}`} ch={ch} idx={i} />
          ))}
        </div>
      </motion.div>

      {/* Detected chapters list (compact) */}
      {chapters_detected.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }} className="glass" style={{ padding: '24px 28px', marginBottom: 20 }}>
          <h2 style={{ fontWeight: 700, fontSize: 15, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Book size={16} /> Chapters Detected in Uploaded Document ({chapters_detected.length})
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
      )}

      {/* Tables */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.17 }} className="glass" style={{ padding: '24px 28px', marginBottom: 20 }}>
        <h2 style={{ fontWeight: 700, fontSize: 15, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Table2 size={16} /> Tables Extracted ({tables_summary.total})
        </h2>
        {tables_summary.total === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No tables extracted from this document.</div>
        ) : (
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
        )}
      </motion.div>

      {/* Findings */}
      {findings.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.20 }} className="glass" style={{ padding: '24px 28px' }}>
          <h2 style={{ fontWeight: 700, fontSize: 15, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={16} /> All Findings ({findings.length})
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
