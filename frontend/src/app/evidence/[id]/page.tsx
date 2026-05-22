'use client';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { api } from '@/lib/api';
import type { Finding } from '@/lib/api';
import { ArrowLeft, XCircle, AlertTriangle, Info, FileText, ChevronRight } from 'lucide-react';

export default function EvidencePage() {
  const { id } = useParams<{ id: string }>();
  const docId = Number(id);
  const [selected, setSelected] = useState<Finding | null>(null);

  const { data: doc }    = useQuery({ queryKey: ['doc', docId],      queryFn: () => api.getDocument(docId) });
  const { data: evidence = [] } = useQuery({ queryKey: ['evidence', docId], queryFn: () => api.getEvidence(docId) });

  const sorted = [...evidence].sort((a, b) => {
    const order = { critical: 0, major: 1, minor: 2, info: 3 };
    return (order[a.severity as keyof typeof order] ?? 3) - (order[b.severity as keyof typeof order] ?? 3);
  });

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Link href={`/validation/${docId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)', textDecoration: 'none', marginBottom: 24, fontSize: 13 }}>
        <ArrowLeft size={14} /> Back to Validation
      </Link>

      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, marginBottom: 4 }}>Evidence Viewer</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
          {doc?.project_name || doc?.filename} · {evidence.length} findings
        </p>
      </motion.div>

      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: 24, height: 'calc(100vh - 180px)' }}>
        {/* Left: Findings list */}
        <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="glass" style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
            <h3 style={{ fontWeight: 700, fontSize: 14 }}>Findings ({evidence.length})</h3>
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              {['critical', 'major', 'info'].map((sev) => {
                const count = evidence.filter((f) => f.severity === sev).length;
                return count > 0 ? (
                  <span key={sev} style={{ fontSize: 11, padding: '3px 9px', borderRadius: 100, fontWeight: 600,
                    background: sev === 'critical' ? 'var(--rose-dim)' : sev === 'major' ? 'var(--amber-dim)' : 'var(--surface-3)',
                    color: sev === 'critical' ? 'var(--rose)' : sev === 'major' ? 'var(--amber)' : 'var(--text-muted)',
                    border: `1px solid ${sev === 'critical' ? 'rgba(244,63,94,0.3)' : sev === 'major' ? 'rgba(245,158,11,0.3)' : 'var(--border)'}`,
                  }}>
                    {count} {sev}
                  </span>
                ) : null;
              })}
            </div>
          </div>

          <div style={{ overflowY: 'auto', flex: 1, padding: '12px' }}>
            {sorted.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                No findings — all checks passed!
              </div>
            ) : sorted.map((f, i) => (
              <motion.div
                key={f.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.02 }}
                onClick={() => setSelected(f)}
                style={{
                  padding: '12px 14px', borderRadius: 10, marginBottom: 8, cursor: 'pointer',
                  border: `1px solid ${selected?.id === f.id ? 'var(--railway-blue-light)' : 'var(--border)'}`,
                  background: selected?.id === f.id ? 'var(--railway-blue-dim)' : 'var(--surface-2)',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  <SevIcon severity={f.severity} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.3, marginBottom: 4 }}>{f.issue}</div>
                    {f.page && (
                      <div style={{ fontSize: 11, color: 'var(--railway-blue-light)', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <FileText size={10} /> Page {f.page}
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
                      Confidence: {(f.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                  <ChevronRight size={14} color="var(--text-muted)" />
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Right: Finding detail + snippet */}
        <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="glass" style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {selected ? (
            <>
              <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
                  <SevIcon severity={selected.severity} size={18} />
                  <div>
                    <h3 style={{ fontWeight: 700, fontSize: 16, marginBottom: 4 }}>{selected.issue}</h3>
                    <p style={{ color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.5 }}>{selected.detail}</p>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 16 }}>
                  {[
                    { label: 'Severity', value: selected.severity, color: selected.severity === 'critical' ? 'var(--rose)' : selected.severity === 'major' ? 'var(--amber)' : 'var(--text-secondary)' },
                    { label: 'Category', value: selected.category,   color: 'var(--text-secondary)' },
                    { label: 'Match Type', value: selected.match_type ?? 'N/A', color: 'var(--text-secondary)' },
                    { label: 'Confidence', value: `${(selected.confidence * 100).toFixed(0)}%`, color: 'var(--text-secondary)' },
                    ...(selected.page ? [{ label: 'Page', value: `${selected.page}`, color: 'var(--railway-blue-light)' }] : []),
                  ].map(({ label, value, color }) => (
                    <div key={label} style={{ padding: '8px 14px', borderRadius: 8, background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{label}</div>
                      <div style={{ fontSize: 13, fontWeight: 600, color }}>{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
                {selected.snippet ? (
                  <>
                    <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      Evidence Snippet {selected.page ? `(Page ${selected.page})` : ''}
                    </h4>
                    <div style={{
                      background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px',
                      fontFamily: 'JetBrains Mono, monospace', fontSize: 12, lineHeight: 1.8,
                      color: 'var(--text-primary)',
                      borderLeft: '3px solid var(--railway-blue-light)',
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>
                      {selected.snippet}
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 12, fontStyle: 'italic' }}>
                      ℹ This snippet is taken directly from the document. No AI-generated content.
                    </p>
                  </>
                ) : (
                  <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
                    <FileText size={40} style={{ margin: '0 auto 12px', opacity: 0.4, display: 'block' }} />
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>No page snippet available</div>
                    <div style={{ fontSize: 12 }}>
                      {selected.match_type === 'missing'
                        ? 'This chapter/table was not found in the document.'
                        : 'No specific page location was determined for this finding.'}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)' }}>
              <FileText size={48} style={{ marginBottom: 16, opacity: 0.3 }} />
              <h3 style={{ fontWeight: 700, marginBottom: 8 }}>Select a finding</h3>
              <p style={{ fontSize: 13 }}>Click a finding on the left to see its evidence.</p>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}

function SevIcon({ severity, size = 14 }: { severity: string; size?: number }) {
  if (severity === 'critical') return <XCircle size={size} color="var(--rose)" style={{ flexShrink: 0 }} />;
  if (severity === 'major')    return <AlertTriangle size={size} color="var(--amber)" style={{ flexShrink: 0 }} />;
  return <Info size={size} color="var(--text-muted)" style={{ flexShrink: 0 }} />;
}
