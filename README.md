# 🚂 DPR Validator

**AI-powered validation engine for Indian Railway Detailed Project Reports (DPRs)**

DPR Validator automatically parses, structures, and validates railway DPR documents against the official **DPR Format Vol-I** specification using a Retrieval-Augmented Generation (RAG) pipeline. It provides grounded, evidence-backed findings with suggested corrections — ensuring every DPR meets Indian Railways' structural and content standards.

---

## ✨ Features

- **📄 Intelligent PDF Parsing** — Multi-stage pipeline with text extraction, OCR fallback (for scanned PDFs), table extraction, and automatic chapter/section hierarchy detection
- **🧠 RAG Validation** — ChromaDB vector store + Ollama LLM (qwen3, gemma) for high-accuracy, spec-grounded validation with evidence citations
- **⚡ Heuristic Fallback** — Fast regex/fuzzy-matching validation engine when LLM is unavailable
- **📊 Scoring & Grading** — Overall compliance score (0–100) with per-category breakdowns (chapter structure, completeness, tables)
- **🔍 Evidence Engine** — Every finding is backed by page numbers, text snippets, reference sections, and suggested corrections — zero hallucination
- **📋 Report Generation** — Exportable validation reports with detailed findings
- **🔄 Document Comparison** — Compare uploaded DPRs against reference documents (Adipur, Akola, ADRA, ADTP)
- **🎛️ Real-time Progress** — Live parsing progress with pause/resume support
- **🌐 Modern Web UI** — Next.js 16 dashboard with Framer Motion animations, interactive charts (Recharts), and responsive design

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend                         │
│   Upload → Parse → Validate → Evidence → Report → Compare      │
└──────────────────────────┬──────────────────────────────────────┘
                           │  REST API (axios / fetch)
┌──────────────────────────▼──────────────────────────────────────┐
│                     FastAPI Backend (:8000)                      │
│                                                                  │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐ │
│  │  Parser   │  │  Validator   │  │  Comparator  │  │ Reports │ │
│  │ Pipeline  │  │  (RAG/Heur)  │  │  (Ref DPRs)  │  │ Engine  │ │
│  └─────┬────┘  └──────┬───────┘  └──────────────┘  └─────────┘ │
│        │               │                                         │
│  ┌─────▼────┐  ┌───────▼────────────────────────────┐           │
│  │ PDF/OCR  │  │         RAG Pipeline                │           │
│  │ Tables   │  │  Embedder → ChromaDB → Retriever   │           │
│  │ Sections │  │        → LLM Validator              │           │
│  └──────────┘  └───────┬────────────────────────────┘           │
│                        │                                         │
│               ┌────────▼────────┐  ┌─────────────────┐          │
│               │  Ollama Server  │  │  SQLite (async)  │          │
│               │  (LLM + Embed)  │  │  + ChromaDB      │          │
│               └─────────────────┘  └─────────────────┘          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Framework | **FastAPI** 0.115 + **Uvicorn** |
| Database | **SQLite** (async via aiosqlite) + **SQLAlchemy** 2.0 ORM |
| PDF Parsing | **PyMuPDF** (text extraction) + **pdfplumber** (tables) + **Pillow** (OCR images) |
| Vector Store | **ChromaDB** 0.6 (persistent, cosine similarity) |
| Embeddings | **mxbai-embed-large** via Ollama |
| LLM | **Ollama** (qwen3, gemma) with Gemini API fallback |
| Fuzzy Matching | **RapidFuzz** (section detection, comparator) |
| HTTP Client | **httpx** (async, Gemini fallback) |

### Frontend
| Component | Technology |
|-----------|-----------|
| Framework | **Next.js** 16 (App Router, TypeScript) |
| State Management | **Zustand** 5 + **TanStack React Query** 5 |
| Animations | **Framer Motion** 12 |
| Charts | **Recharts** 3 |
| Icons | **Lucide React** |
| Styling | **Tailwind CSS** 4 |
| HTTP Client | **Axios** + native `fetch` |

---

## 📁 Project Structure

```
DPR Validator/
├── start.sh                    # One-command launcher (backend + frontend)
├── .gitignore                  # Root gitignore
│
├── backend/
│   ├── main.py                 # FastAPI app entrypoint
│   ├── requirements.txt        # Python dependencies
│   ├── ingest_knowledge_base.py # ChromaDB knowledge base builder
│   ├── migrate_add_rag_fields.py # DB migration for RAG columns
│   ├── .env                    # Environment config (not committed)
│   │
│   ├── api/
│   │   ├── deps.py             # Dependency injection (DB session)
│   │   └── routes/
│   │       ├── documents.py    # Upload, parse, list, pause/resume
│   │       ├── validation.py   # Run validation (RAG or heuristic)
│   │       ├── comparison.py   # Compare against reference DPRs
│   │       ├── reports.py      # Generate & export reports
│   │       └── knowledge_base.py # KB status & management
│   │
│   ├── core/
│   │   ├── config.py           # Settings (env vars, paths, model config)
│   │   └── database.py         # SQLAlchemy async engine & session
│   │
│   ├── models/
│   │   └── db_models.py        # ORM models (Document, Page, Finding, etc.)
│   │
│   ├── parser/
│   │   ├── pipeline.py         # Multi-stage parsing orchestrator
│   │   ├── pdf_extractor.py    # PyMuPDF text extraction
│   │   ├── ocr_fallback.py     # OCR for scanned pages
│   │   ├── table_extractor.py  # pdfplumber table extraction
│   │   ├── section_detector.py # Chapter/section hierarchy detection
│   │   └── metadata_extractor.py # Project name, route, length extraction
│   │
│   ├── rag/
│   │   ├── chroma_store.py     # ChromaDB singleton (4 collections)
│   │   ├── embedder.py         # Ollama mxbai-embed-large wrapper
│   │   ├── retriever.py        # Hierarchical spec chunk retrieval
│   │   └── llm_validator.py    # LLM-based validation (structure, chapters, tables)
│   │
│   ├── validator/
│   │   ├── scoring.py          # Heuristic scoring engine (fast fallback)
│   │   ├── rag_scoring.py      # RAG scoring orchestrator
│   │   └── format_engine.py    # Format compliance checks
│   │
│   ├── comparator/
│   │   └── comparator.py       # Structural diff against reference DPRs
│   │
│   ├── evidence/
│   │   └── engine.py           # Evidence locator (page + snippet matching)
│   │
│   ├── references/
│   │   ├── dpr_format_v1.json  # DPR Vol-I chapter specs & requirements
│   │   └── railway_aliases.json # Accepted chapter title variants
│   │
│   ├── ground_truth/
│   │   ├── adipur_truth.json   # Reference DPR: Adipur
│   │   ├── akola_truth.json    # Reference DPR: Akola
│   │   ├── adra_truth.json     # Reference DPR: ADRA
│   │   ├── adtp_truth.json     # Reference DPR: ADTP
│   │   └── dpr_format_truth.json # DPR format ground truth
│   │
│   └── storage/
│       ├── uploads/            # Uploaded PDF files
│       ├── chroma_db/          # ChromaDB persistence
│       └── dpr_validator.db    # SQLite database
│
└── frontend/
    ├── package.json            # Node dependencies
    ├── next.config.ts          # Next.js configuration
    ├── tsconfig.json           # TypeScript configuration
    └── src/
        ├── app/
        │   ├── layout.tsx      # Root layout (sidebar + providers)
        │   ├── page.tsx        # Dashboard / document list
        │   ├── globals.css     # Global styles
        │   ├── upload/         # Upload page
        │   ├── validation/     # Validation results page
        │   ├── evidence/       # Evidence viewer page
        │   ├── reports/        # Report viewer page
        │   └── compare/        # Document comparison page
        ├── components/
        │   ├── Sidebar.tsx     # Navigation sidebar
        │   └── QueryProvider.tsx # React Query provider
        └── lib/
            ├── api.ts          # Backend API client
            └── store.ts        # Zustand state store
```

---

## 🚀 Getting Started

### Prerequisites

- **Python** 3.11+
- **Node.js** 18+
- **Ollama** ([install guide](https://ollama.ai)) — running locally or on a network host

### 1. Clone the Repository

```bash
git clone https://github.com/Arnavsao/DPR-Validator.git
cd DPR-Validator
```

### 2. Set Up the Backend

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows

# Install Python dependencies
pip install -r backend/requirements.txt
```

### 3. Configure Environment

Create `backend/.env` (or copy from example):

```env
DEBUG=true
DATABASE_URL=sqlite+aiosqlite:///./storage/dpr_validator.db
MAX_UPLOAD_SIZE_MB=150

# Ollama — point to your Ollama server
OLLAMA_BASE_URL=http://localhost:11434

# Embedding model
EMBED_MODEL=mxbai-embed-large

# LLM models (must be pulled in Ollama first)
LLM_PRIMARY=qwen3:8b
LLM_FALLBACK_1=gemma3:12b
LLM_FALLBACK_2=gemma3:4b

# (Optional) Gemini API fallback
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-1.5-flash

# RAG tuning
RAG_TOP_K=5
LLM_TIMEOUT_SECS=600
CHUNK_SIZE_CHARS=1500
CHUNK_OVERLAP_CHARS=200
```

### 4. Pull Ollama Models

```bash
ollama pull mxbai-embed-large
ollama pull qwen3:8b          # or your preferred model
```

### 5. Ingest the Knowledge Base

Place `DPR format Vol-I.pdf` in the project root, then:

```bash
cd backend
python ingest_knowledge_base.py
```

> **Note:** The knowledge base is built from structured JSON references, not OCR. The PDF is used as the authoritative source reference.

### 6. Set Up the Frontend

```bash
cd frontend
npm install
```

### 7. Run Everything

**Option A — Single command:**

```bash
./start.sh
```

**Option B — Manual (two terminals):**

```bash
# Terminal 1: Backend
source .venv/bin/activate
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

### 8. Open the App

| Service | URL |
|---------|-----|
| 🌐 Frontend | http://localhost:3000 |
| 📡 Backend API | http://localhost:8000 |
| 📚 API Docs (Swagger) | http://localhost:8000/docs |
| 🧠 KB Status | http://localhost:8000/api/kb/status |

---

## 📡 API Reference

### Documents
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/documents/upload` | Upload a DPR PDF |
| `GET` | `/api/documents` | List all documents |
| `GET` | `/api/documents/{id}` | Get document details |
| `POST` | `/api/documents/{id}/parse` | Trigger parsing |
| `POST` | `/api/documents/{id}/pause` | Pause processing |
| `POST` | `/api/documents/{id}/resume` | Resume processing |
| `GET` | `/api/documents/{id}/nodes` | Get chapter tree |

### Validation
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/validate/{id}?mode=rag` | Run RAG validation (default) |
| `POST` | `/api/validate/{id}?mode=heuristic` | Run heuristic validation |
| `GET` | `/api/validate/{id}/result` | Get validation scores |
| `GET` | `/api/validate/{id}/evidence` | Get grounded findings |
| `GET` | `/api/validate/{id}/rag-status` | Check RAG readiness |

### Comparison & Reports
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/compare/{id}` | Compare against reference DPRs |
| `GET` | `/api/reports/{id}` | Get validation report |
| `GET` | `/api/kb/status` | Knowledge base status |

---

## 🔄 Validation Modes

### RAG Mode (Default)
Uses the full LLM + ChromaDB pipeline for high-accuracy validation:
1. Retrieves relevant DPR Vol-I spec chunks from ChromaDB
2. LLM evaluates the document against retrieved specifications
3. Produces grounded findings with evidence citations and suggested corrections
4. **~2–10 minutes** depending on document size and LLM speed

### Heuristic Mode
Fast regex/fuzzy-matching engine for quick structural checks:
1. Pattern-based chapter detection against known DPR structures
2. Fuzzy title matching using RapidFuzz
3. Table presence checks
4. **~5 seconds** per document

---

## 🗄️ Knowledge Base

The validation knowledge base is stored in ChromaDB with 4 hierarchical collections:

| Collection | Contents |
|-----------|----------|
| `dpr_spec_volume` | Volume-level overview chunks |
| `dpr_spec_chapter` | Chapter-level specs (primary retrieval target) |
| `dpr_spec_section` | Section/subsection-level detail |
| `dpr_spec_table` | Table requirement specifications |

Built from structured JSON sources:
- `references/dpr_format_v1.json` — Chapter specs, table requirements, keywords
- `references/railway_aliases.json` — Accepted title variants per chapter
- `ground_truth/*.json` — Gold-standard real DPR examples

---

## 🧪 Development

### Knowledge Base Management

```bash
# Check KB status
python ingest_knowledge_base.py --status

# Preview chunks (no DB writes)
python ingest_knowledge_base.py --dry-run

# Force re-ingestion
python ingest_knowledge_base.py --force
```

### Database Migration

```bash
# Add RAG columns to existing DB
python migrate_add_rag_fields.py
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `true` | Enable debug logging |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `EMBED_MODEL` | `mxbai-embed-large` | Embedding model name |
| `LLM_PRIMARY` | `qwen3:32b` | Primary LLM for validation |
| `LLM_FALLBACK_1` | `qwen2.5:32b` | First fallback LLM |
| `LLM_FALLBACK_2` | `gemma3:27b` | Second fallback LLM |
| `RAG_TOP_K` | `5` | Spec chunks to retrieve per query |
| `LLM_TIMEOUT_SECS` | `600` | LLM call timeout (seconds) |
| `MAX_UPLOAD_SIZE_MB` | `150` | Maximum PDF upload size |
| `CHUNK_SIZE_CHARS` | `1500` | Ingestion chunk size |
| `CHUNK_OVERLAP_CHARS` | `200` | Ingestion chunk overlap |

---

## 📜 License

This project is proprietary. All rights reserved.

---

<p align="center">
  Built with ❤️ for Indian Railways
</p>
