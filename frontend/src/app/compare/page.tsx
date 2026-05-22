'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '@/lib/api';
import type { Document } from '@/lib/api';
import { CheckCircle, XCircle, Minus, ChevronDown, ArrowLeftRight } from 'lucide-react';

export default function ComparePage() {
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [selectedRef, setSelectedRef] = useState<string>('adipur');
  const [compareResult, setCompareResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const { data: docs = [] } = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments });
  const { data: refs = [] } = useQuery({ queryKey: ['references'], queryFn: api.getReferences });

  const validatedDocs = docs.filter((d) => d.state === 'VALIDATED');

  const runCompare = async () => {
    if (!selectedDocId) return;
    setLoading(true);
    try {
      const res = await api.compare(selectedDocId, selectedRef);
      setCompareResult(res);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 26, fontWeight: 800, marginBottom: 6 }}>Compare DPRs</h1>
        <p style={{ color: 'var(--text-secondary)' }}>
          Compare an uploaded DPR's chapter structure against a reference DPR.
        </p>
      </motion.div>

      {/* Selector */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="glass" style={{ padding: '28px 32px', marginBottom: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 24, alignItems: 'center' }}>
          {/* Target DPR */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 8 }}>
              TARGET DPR (Uploaded)
            </label>
            <select
              value={selectedDocId ?? ''}
              onChange={(e) => setSelectedDocId(Number(e.target.value) || null)}
              style={selectStyle}
            >
              <option value="">— Select DPR —</option>
              {validatedDocs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.project_name || d.filename}
                </option>
              ))}
            </select>
            {validatedDocs.length === 0 && (
              <p style={{ fontSize: 11, color: 'var(--rose)', marginTop: 6 }}>
                No validated DPRs found. Upload and validate one first.
              </p>
            )}
          </div>

          {/* vs */}
          <div style={{ textAlign: 'center', padding: '0 8px' }}>
            <div style={{
              width: 44, height: 44, borderRadius: 12, border: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--surface-2)',
            }}>
              <ArrowLeftRight size={18} color="var(--text-muted)" />
            </div>
          </div>

          {/* Reference */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 8 }}>
              REFERENCE DPR
            </label>
            <select
              value={selectedRef}
              onChange={(e) => setSelectedRef(e.target.value)}
              style={selectStyle}
            >
              {refs.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.name} ({r.expected_grade})
                </option>
              ))}
            </select>
          </div>
        </div>

        <motion.button
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.99 }}
          onClick={runCompare}
          disabled={!selectedDocId || loading}
          style={{
            marginTop: 24, width: '100%', padding: '13px', borderRadius: 12, border: 'none',
            background: selectedDocId
              ? 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))'
              : 'var(--surface-3)',
            color: selectedDocId ? 'white' : 'var(--text-muted)',
            fontWeight: 700, fontSize: 15, cursor: selectedDocId ? 'pointer' : 'not-allowed',
            boxShadow: selectedDocId ? '0 4px 20px rgba(10,61,145,0.35)' : 'none',
          }}
        >
          {loading ? 'Comparing…' : 'Run Comparison'}
        </motion.button>
      </motion.div>

      {/* Results */}
      <AnimatePresence>
        {compareResult && !loading && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            {/* Score */}
            <div className="glass" style={{
              padding: '24px 32px', marginBottom: 20,
              display: 'flex', alignItems: 'center', gap: 32,
              background: 'linear-gradient(135deg, rgba(10,61,145,0.18), rgba(13,21,38,0.8))',
            }}>
              <div>
                <div style={{ fontSize: 48, fontWeight: 900, color: compareResult.match_score >= 85 ? 'var(--emerald)' : compareResult.match_score >= 65 ? 'var(--amber)' : 'var(--rose)' }}>
                  {compareResult.match_score.toFixed(0)}%
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Structural Match</div>
              </div>
              <div style={{ width: 1, height: 60, background: 'var(--border)' }} />
              <div style={{ display: 'flex', gap: 32 }}>
                {[
                  { label: 'Chapters in Both', value: compareResult.chapters_in_both.length, color: 'var(--emerald)' },
                  { label: 'Missing in Target', value: compareResult.missing_in_target.length, color: 'var(--rose)' },
                  { label: 'Extra in Target',   value: compareResult.extra_in_target.length,   color: 'var(--amber)' },
                ].map(({ label, value, color }) => (
                  <div key={label}>
                    <div style={{ fontSize: 26, fontWeight: 700, color }}>{value}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 2 }}>vs</div>
                <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{compareResult.reference_name}</div>
              </div>
            </div>

            {/* Chapter diff table */}
            <div className="glass" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)' }}>
                <h3 style={{ fontWeight: 700, fontSize: 15 }}>Chapter Comparison</h3>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Chapter', 'Status', 'Target Page', 'Reference Page'].map((h) => (
                      <th key={h} style={{ padding: '10px 20px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {compareResult.chapter_diffs.map((d: any, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--surface-2)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={{ padding: '12px 20px', fontSize: 13, fontWeight: 500 }}>{d.title}</td>
                      <td style={{ padding: '12px 20px' }}>
                        <StatusBadge status={d.status} />
                      </td>
                      <td style={{ padding: '12px 20px', fontSize: 12, color: 'var(--text-secondary)' }}>
                        {d.target_page ? `p${d.target_page}` : '—'}
                      </td>
                      <td style={{ padding: '12px 20px', fontSize: 12, color: 'var(--text-secondary)' }}>
                        {d.reference_page ? `p${d.reference_page}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; color: string; Icon: any }> = {
    present_both:      { label: 'Present in Both', color: 'var(--emerald)', Icon: CheckCircle },
    missing_in_target: { label: 'Missing in Target', color: 'var(--rose)',   Icon: XCircle },
    extra_in_target:   { label: 'Extra in Target',   color: 'var(--amber)',  Icon: Minus },
  };
  const { label, color, Icon } = map[status] ?? { label: status, color: 'var(--text-muted)', Icon: Minus };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color }}>
      <Icon size={13} /> {label}
    </span>
  );
}

const selectStyle: React.CSSProperties = {
  width: '100%', padding: '11px 14px', borderRadius: 10,
  background: 'var(--surface-2)', border: '1px solid var(--border)',
  color: 'var(--text-primary)', fontSize: 13, fontWeight: 500,
  appearance: 'none', cursor: 'pointer',
};
