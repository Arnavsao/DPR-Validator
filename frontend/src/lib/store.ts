import { create } from 'zustand';
import type { Document, ValidationResult, Finding } from './api';

interface AppState {
  // Selected document
  selectedDocId: number | null;
  setSelectedDocId: (id: number | null) => void;

  // Upload queue
  uploadQueue: Array<{ name: string; progress: number; status: string }>;
  addToQueue: (name: string) => void;
  updateQueue: (name: string, progress: number, status: string) => void;
  clearQueue: () => void;

  // Polling state
  pollingDocIds: Set<number>;
  addPolling: (id: number) => void;
  removePolling: (id: number) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedDocId: null,
  setSelectedDocId: (id) => set({ selectedDocId: id }),

  uploadQueue: [],
  addToQueue: (name) =>
    set((s) => ({
      uploadQueue: [...s.uploadQueue, { name, progress: 0, status: 'uploading' }],
    })),
  updateQueue: (name, progress, status) =>
    set((s) => ({
      uploadQueue: s.uploadQueue.map((q) =>
        q.name === name ? { ...q, progress, status } : q
      ),
    })),
  clearQueue: () => set({ uploadQueue: [] }),

  pollingDocIds: new Set(),
  addPolling: (id) =>
    set((s) => ({ pollingDocIds: new Set([...s.pollingDocIds, id]) })),
  removePolling: (id) =>
    set((s) => {
      const next = new Set(s.pollingDocIds);
      next.delete(id);
      return { pollingDocIds: next };
    }),
}));

// ── Grade helpers ────────────────────────────────────────────────────────────

export function gradeLabel(grade: string): string {
  const map: Record<string, string> = {
    Gold: '🥇 Gold',
    Acceptable: '✅ Acceptable',
    Partial: '🟡 Partial',
    Legacy: '🟠 Legacy',
    Invalid: '❌ Invalid',
  };
  return map[grade] ?? grade;
}

export function gradeClass(grade: string): string {
  const map: Record<string, string> = {
    Gold: 'grade-gold',
    Acceptable: 'grade-acceptable',
    Partial: 'grade-partial',
    Legacy: 'grade-legacy',
    Invalid: 'grade-invalid',
  };
  return map[grade] ?? '';
}

export function scoreColor(score: number): string {
  if (score >= 90) return '#10B981';
  if (score >= 75) return '#F59E0B';
  if (score >= 50) return '#FB923C';
  return '#F43F5E';
}

export function stateColor(state: string): string {
  const map: Record<string, string> = {
    UPLOADED:   '#8B9BBF',
    PARSING:    '#6BA3FF',
    OCR:        '#6BA3FF',
    TABLES:     '#6BA3FF',
    STRUCTURED: '#F59E0B',
    VALIDATING: '#6BA3FF',
    VALIDATED:  '#10B981',
    FAILED:     '#F43F5E',
  };
  return map[state] ?? '#8B9BBF';
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
