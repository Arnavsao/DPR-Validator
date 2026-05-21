#!/usr/bin/env bash
# DPR Validator — start both services
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV="$SCRIPT_DIR/.venv"

echo "🚂 DPR Validator — Starting services..."

# ── Backend ──────────────────────────────────────────────────────────────────
echo ""
echo "▶  Starting FastAPI backend on http://localhost:8000"
source "$VENV/bin/activate"
cd "$BACKEND_DIR"

# Turn off debug SQL noise unless DEBUG=full is set
LOG_LEVEL="${LOG_LEVEL:-warning}"

uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --log-level "$LOG_LEVEL" &

BACKEND_PID=$!

# Wait for backend to be ready
for i in {1..20}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "   ✓ Backend ready (PID $BACKEND_PID)"
        break
    fi
    sleep 0.5
done

# ── Frontend ─────────────────────────────────────────────────────────────────
echo ""
echo "▶  Starting Next.js frontend on http://localhost:3000"
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "────────────────────────────────────────────────"
echo "  🌐 Frontend:  http://localhost:3000"
echo "  📡 Backend:   http://localhost:8000"
echo "  📚 API Docs:  http://localhost:8000/docs"
echo "────────────────────────────────────────────────"
echo "  Press Ctrl+C to stop both services"
echo ""

# Wait for either process to exit
wait $BACKEND_PID $FRONTEND_PID

# Cleanup on exit
trap "echo ''; echo 'Stopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
