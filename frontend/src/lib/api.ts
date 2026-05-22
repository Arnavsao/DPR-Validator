const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'API error');
  }
  return res.json();
}

// ── Documents ──────────────────────────────────────────────────────────────

export const api = {
  // Upload PDF
  async uploadDocument(file: File): Promise<{ id: number; state: string; message: string }> {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/api/documents/upload`, {
      method: 'POST',
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
    return res.json();
  },

  // List all documents
  listDocuments(): Promise<Document[]> {
    return request('/api/documents');
  },

  // Get single document
  getDocument(id: number): Promise<Document> {
    return request(`/api/documents/${id}`);
  },

  // Re-parse
  parseDocument(id: number): Promise<{ message: string }> {
    return request(`/api/documents/${id}/parse`, { method: 'POST' });
  },

  // Pause document processing
  pauseDocument(id: number): Promise<{ is_paused: boolean; message: string }> {
    return request(`/api/documents/${id}/pause`, { method: 'POST' });
  },

  // Resume document processing
  resumeDocument(id: number): Promise<{ is_paused: boolean; message: string }> {
    return request(`/api/documents/${id}/resume`, { method: 'POST' });
  },

  // Chapter tree
  getNodes(id: number): Promise<DocumentNode[]> {
    return request(`/api/documents/${id}/nodes`);
  },

  // Tables
  getTables(id: number): Promise<ExtractedTable[]> {
    return request(`/api/documents/${id}/tables`);
  },

  // ── Validation ────────────────────────────────────────────────────────────

  validateDocument(id: number): Promise<{ message: string }> {
    return request(`/api/validate/${id}`, { method: 'POST' });
  },

  getValidationResult(id: number): Promise<ValidationResult> {
    return request(`/api/validate/${id}/result`);
  },

  // Note: backend returns { run_id, validation_mode, findings: Finding[] }
  getEvidence(id: number): Promise<EvidenceResponse> {
    return request(`/api/validate/${id}/evidence`);
  },

  // ── Comparison ───────────────────────────────────────────────────────────

  getReferences(): Promise<Reference[]> {
    return request('/api/compare/references');
  },

  compare(docId: number, reference: string): Promise<CompareResult> {
    return request('/api/compare', {
      method: 'POST',
      body: JSON.stringify({ doc_id: docId, reference }),
    });
  },

  // ── Reports ──────────────────────────────────────────────────────────────

  getReport(id: number): Promise<FullReport> {
    return request(`/api/reports/${id}`);
  },
};

// ── Types ──────────────────────────────────────────────────────────────────

export interface Document {
  id: number;
  filename: string;
  file_size: number;
  page_count: number;
  state: 'UPLOADED' | 'PARSING' | 'OCR' | 'TABLES' | 'STRUCTURED' | 'VALIDATING' | 'VALIDATED' | 'FAILED';
  is_paused: boolean;
  progress_percent: number;
  current_stage: string | null;
  estimated_remaining_seconds: number;
  project_name: string | null;
  project_route: string | null;
  division: string | null;
  length_km: number | null;
  report_date: string | null;
  is_reference: boolean;
  uploaded_at: string;
  parsed_at: string | null;
  error_message: string | null;
}

export interface DocumentNode {
  id: number;
  parent_id: number | null;
  node_type: string;
  level: number;
  number: string | null;
  title: string;
  page_start: number;
  page_end: number | null;
  sequence: number;
}

export interface ExtractedTable {
  id: number;
  page_number: number;
  table_index: number;
  category: string;
  title: string | null;
  rows: number;
  cols: number;
  extractor: string;
}

export interface ValidationResult {
  run_id: number;
  document_id: number;
  run_at: string;
  validation_mode?: string;
  overall_score: number;
  grade: string;
  chapters_found: number;
  chapters_total: number;
  tables_found: number;
  scores: {
    // Backend field names (from validation.py)
    chapter_structure?: number;    // structure score
    chapter_completeness?: number; // completeness score
    table?: number;
    // Legacy / alias fields for chart compatibility
    chapter?: number;
    subchapter?: number;
    traffic?: number;
    engineering?: number;
    risk?: number;
    cost?: number;
  };
}

export interface EvidenceResponse {
  run_id: number;
  validation_mode?: string;
  findings: Finding[];
}

export interface Finding {
  id: number;
  category: string;
  severity: 'critical' | 'major' | 'minor' | 'info';
  issue: string;
  detail: string | null;
  match_type: string | null;
  confidence: number;
  page: number | null;
  snippet: string | null;
}

export interface Reference {
  key: string;
  name: string;
  classification: string;
  pages: number;
  length_km: number;
  date: string;
  expected_grade: string;
}

export interface CompareResult {
  reference_name: string;
  target_doc_name: string;
  match_score: number;
  chapters_in_both: string[];
  missing_in_target: string[];
  extra_in_target: string[];
  chapter_diffs: Array<{
    title: string;
    status: string;
    target_page: number | null;
    reference_page: number | null;
  }>;
}

export interface FullReport {
  generated_at: string;
  document: {
    id: number;
    name: string;
    pages: number;
    size_bytes: number;
    project_name: string | null;
    project_route: string | null;
    division: string | null;
    length_km: number | null;
    report_date: string | null;
    uploaded_at: string;
    parsed_at: string | null;
  };
  validation: {
    run_id: number;
    run_at: string;
    overall_score: number;
    grade: string;
    chapters_found: number;
    chapters_total: number;
    tables_found: number;
    scores: Record<string, number>;
  };
  chapters_detected: Array<{ number: string; title: string; page_start: number }>;
  tables_summary: { total: number; by_category: Record<string, number> };
  findings: Finding[];
}
