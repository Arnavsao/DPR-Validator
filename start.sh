#!/usr/bin/env bash
# DPR Validator — start both services (v2.0 RAG pipeline)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV="$SCRIPT_DIR/.venv"

echo "🚂 DPR Validator v2.0 — RAG Pipeline"
echo ""

# ── Activate venv ─────────────────────────────────────────────────────────────
source "$VENV/bin/activate"

# ── Knowledge Base Check ──────────────────────────────────────────────────────
CHROMA_DIR="$BACKEND_DIR/storage/chroma_db"
DPR_PDF="$SCRIPT_DIR/DPR format Vol-I.pdf"

echo "▶  Checking knowledge base..."

if [ ! -f "$DPR_PDF" ]; then
    echo "   ⚠️  DPR format Vol-I.pdf not found at: $DPR_PDF"
    echo "   RAG validation will not be available."
    echo "   Place the PDF in the project root and run:"
    echo "   python backend/ingest_knowledge_base.py"
else
    # Check if ChromaDB collections exist and are non-empty
    KB_READY=$(python3 -c "
import sys
sys.path.insert(0, '$BACKEND_DIR')
from rag.chroma_store import chroma_store
print('yes' if chroma_store.is_knowledge_base_ready() else 'no')
" 2>/dev/null || echo "error")

    if [ "$KB_READY" = "yes" ]; then
        echo "   ✓ Knowledge base already populated."
    elif [ "$KB_READY" = "error" ]; then
        echo "   ⚠️  Could not check KB status (chromadb may not be installed yet)."
        echo "   Run: pip install -r backend/requirements.txt"
    else
        echo "   First run detected — ingesting DPR format Vol-I.pdf..."
        echo "   (This takes ~5–15 minutes. Subsequent starts are instant.)"
        echo ""
        cd "$BACKEND_DIR"
        python ingest_knowledge_base.py
        cd "$SCRIPT_DIR"
        echo "   ✓ Knowledge base ready."
    fi
fi

# ── DB Migration (adds RAG columns to existing DB) ────────────────────────────
if [ -f "$BACKEND_DIR/storage/dpr_validator.db" ]; then
    echo ""
    echo "▶  Running DB migration (adds RAG fields if not present)..."
    cd "$BACKEND_DIR"
    python migrate_add_rag_fields.py 2>/dev/null && echo "   ✓ DB up to date." || echo "   ⚠️  Migration skipped (fresh DB)."
    cd "$SCRIPT_DIR"
fi

# ── Backend ───────────────────────────────────────────────────────────────────
echo ""
echo "▶  Starting FastAPI backend on http://localhost:8000"
cd "$BACKEND_DIR"

LOG_LEVEL="${LOG_LEVEL:-warning}"

uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --log-level "$LOG_LEVEL" &

BACKEND_PID=$!

# Wait for backend to be ready
for i in {1..30}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "   ✓ Backend ready (PID $BACKEND_PID)"
        break
    fi
    sleep 0.5
done

# ── Frontend ──────────────────────────────────────────────────────────────────
echo ""
echo "▶  Starting Next.js frontend on http://localhost:3000"
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "────────────────────────────────────────────────────────"
echo "  🌐 Frontend:  http://localhost:3000"
echo "  📡 Backend:   http://localhost:8000"
echo "  📚 API Docs:  http://localhost:8000/docs"
echo "  🧠 KB Status: http://localhost:8000/api/kb/status"
echo "────────────────────────────────────────────────────────"
echo "  Validation modes:"
echo "    RAG (high accuracy):  POST /api/validate/{id}?mode=rag"
echo "    Heuristic (fast):     POST /api/validate/{id}?mode=heuristic"
echo "────────────────────────────────────────────────────────"
echo "  LLM: $LLM_PRIMARY (set LLM_PRIMARY in backend/.env)"
echo "  Press Ctrl+C to stop both services"
echo ""

# Cleanup on exit
trap "echo ''; echo 'Stopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM

# Wait for either process to exit
wait $BACKEND_PID $FRONTEND_PID
