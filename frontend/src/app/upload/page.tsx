'use client';
import { useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, FileText, X, CheckCircle, AlertCircle, Loader2, HardDrive } from 'lucide-react';
import { api } from '@/lib/api';
import { formatBytes } from '@/lib/store';

interface QueueItem {
  file: File;
  status: 'pending' | 'uploading' | 'parsing' | 'done' | 'error';
  docId?: number;
  error?: string;
  progress: number;
}

export default function UploadPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (files: FileList | File[]) => {
    const newItems: QueueItem[] = Array.from(files)
      .filter((f) => f.name.endsWith('.pdf'))
      .map((f) => ({ file: f, status: 'pending', progress: 0 }));
    setQueue((q) => [...q, ...newItems]);
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  }, []);

  const uploadAll = async () => {
    for (let i = 0; i < queue.length; i++) {
      const item = queue[i];
      if (item.status !== 'pending') continue;

      setQueue((q) => q.map((x, j) => j === i ? { ...x, status: 'uploading', progress: 30 } : x));

      try {
        const res = await api.uploadDocument(item.file);
        setQueue((q) => q.map((x, j) => j === i ? { ...x, status: 'parsing', progress: 60, docId: res.id } : x));

        // Poll until structured or validated
        let attempts = 0;
        while (attempts < 60) {
          await new Promise((r) => setTimeout(r, 3000));
          const doc = await api.getDocument(res.id);
          if (doc.state === 'STRUCTURED' || doc.state === 'VALIDATED') {
            setQueue((q) => q.map((x, j) => j === i ? { ...x, status: 'done', progress: 100 } : x));
            // Auto-validate
            await api.validateDocument(res.id);
            qc.invalidateQueries({ queryKey: ['documents'] });
            break;
          } else if (doc.state === 'FAILED') {
            setQueue((q) => q.map((x, j) => j === i ? { ...x, status: 'error', error: doc.error_message ?? 'Parse failed' } : x));
            break;
          }
          attempts++;
          setQueue((q) => q.map((x, j) => j === i ? { ...x, progress: Math.min(90, 60 + attempts) } : x));
        }
      } catch (err: any) {
        setQueue((q) => q.map((x, j) => j === i ? { ...x, status: 'error', error: err.message } : x));
      }
    }
  };

  const removeItem = (i: number) => setQueue((q) => q.filter((_, j) => j !== i));
  const hasPending = queue.some((q) => q.status === 'pending');

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 26, fontWeight: 800, marginBottom: 6 }}>Upload DPR</h1>
        <p style={{ color: 'var(--text-secondary)' }}>
          Upload Railway Detailed Project Report PDFs for validation. Max {150}MB per file.
        </p>
      </motion.div>

      {/* Drop zone */}
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        className={`upload-zone ${dragging ? 'drag-over' : ''}`}
        style={{ padding: '56px 32px', textAlign: 'center', marginBottom: 24 }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => e.target.files && addFiles(e.target.files)}
        />
        <motion.div
          animate={{ scale: dragging ? 1.08 : 1 }}
          transition={{ type: 'spring', stiffness: 300 }}
        >
          <div style={{
            width: 80, height: 80, borderRadius: 24, margin: '0 auto 20px',
            background: 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 8px 32px rgba(10,61,145,0.4)',
          }}>
            <Upload size={36} color="white" />
          </div>
          <h3 style={{ fontWeight: 700, fontSize: 18, marginBottom: 8 }}>
            {dragging ? 'Drop it!' : 'Drag & Drop PDF files'}
          </h3>
          <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
            or <span style={{ color: 'var(--railway-blue-light)', fontWeight: 600 }}>click to browse</span>
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            {['Volume I', 'Volume II', 'Doubling', '3rd/4th Line', 'New Line'].map((tag) => (
              <span key={tag} style={{
                padding: '4px 12px', borderRadius: 100,
                background: 'var(--surface-3)', border: '1px solid var(--border)',
                fontSize: 12, color: 'var(--text-secondary)',
              }}>{tag}</span>
            ))}
          </div>
        </motion.div>
      </motion.div>

      {/* Queue */}
      <AnimatePresence>
        {queue.map((item, i) => (
          <motion.div
            key={item.file.name + i}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="glass-sm"
            style={{ padding: '16px 20px', marginBottom: 12, overflow: 'hidden' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ padding: 10, borderRadius: 10, background: 'var(--surface-3)' }}>
                <FileText size={18} color="var(--text-secondary)" />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.file.name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {formatBytes(item.file.size)}
                  {item.docId && ` · ID: ${item.docId}`}
                </div>
                {/* Progress bar */}
                {item.status !== 'pending' && (
                  <div className="score-bar-track" style={{ marginTop: 8, height: 4 }}>
                    <motion.div
                      className="score-bar-fill"
                      initial={{ width: 0 }}
                      animate={{ width: `${item.progress}%` }}
                      style={{
                        background: item.status === 'error' ? 'var(--rose)' :
                                    item.status === 'done'  ? 'var(--emerald)' :
                                    'linear-gradient(90deg, var(--railway-blue), var(--railway-blue-light))',
                      }}
                    />
                  </div>
                )}
                {item.error && (
                  <div style={{ fontSize: 11, color: 'var(--rose)', marginTop: 4 }}>{item.error}</div>
                )}
              </div>

              {/* Status icon */}
              <div style={{ flexShrink: 0 }}>
                {item.status === 'pending'   && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Ready</span>}
                {(item.status === 'uploading' || item.status === 'parsing') && <Loader2 size={18} className="pulse-blue" color="#6BA3FF" />}
                {item.status === 'done'      && <CheckCircle size={18} color="var(--emerald)" />}
                {item.status === 'error'     && <AlertCircle size={18} color="var(--rose)" />}
              </div>

              {/* Status label */}
              <div style={{ width: 72, textAlign: 'right', fontSize: 11, fontWeight: 600 }}>
                {item.status === 'uploading' && <span style={{ color: '#6BA3FF' }}>Uploading…</span>}
                {item.status === 'parsing'   && <span style={{ color: 'var(--amber)' }}>Parsing…</span>}
                {item.status === 'done'      && (
                  <button
                    onClick={() => item.docId && router.push(`/validation/${item.docId}`)}
                    style={{ background: 'none', border: 'none', color: 'var(--emerald)', cursor: 'pointer', fontWeight: 600, fontSize: 11 }}
                  >View →</button>
                )}
                {item.status === 'error'     && <span style={{ color: 'var(--rose)' }}>Failed</span>}
              </div>

              {item.status === 'pending' && (
                <button onClick={() => removeItem(i)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
                  <X size={16} color="var(--text-muted)" />
                </button>
              )}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>

      {/* Upload button */}
      {hasPending && (
        <motion.button
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={uploadAll}
          style={{
            width: '100%', padding: '14px', borderRadius: 12, border: 'none',
            background: 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))',
            color: 'white', fontWeight: 700, fontSize: 15, cursor: 'pointer',
            boxShadow: '0 4px 20px rgba(10,61,145,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
          }}
        >
          <Upload size={18} />
          Upload & Parse {queue.filter((q) => q.status === 'pending').length} file{queue.filter((q) => q.status === 'pending').length !== 1 ? 's' : ''}
        </motion.button>
      )}
    </div>
  );
}
