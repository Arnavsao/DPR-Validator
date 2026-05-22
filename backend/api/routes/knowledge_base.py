"""
Knowledge Base API — status and re-ingestion endpoints.
"""
import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.config import settings
from rag.chroma_store import chroma_store
from rag.embedder import check_ollama_connection

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])
logger = logging.getLogger(__name__)

# Track ongoing ingestion
_ingestion_running = False
_ingestion_result: dict = {}


@router.get("/status")
async def get_kb_status():
    """
    Check knowledge base readiness and collection statistics.
    Returns collection-level chunk counts and Ollama connectivity.
    """
    kb_status = chroma_store.get_kb_status()
    is_ready = chroma_store.is_knowledge_base_ready()
    ok, ollama_msg = check_ollama_connection()

    return {
        "ready": is_ready,
        "ollama": {
            "connected": ok,
            "message": ollama_msg,
        },
        "collections": kb_status,
        "config": {
            "embed_model":   settings.EMBED_MODEL,
            "llm_primary":   settings.LLM_PRIMARY,
            "llm_fallback_1": settings.LLM_FALLBACK_1,
            "llm_fallback_2": settings.LLM_FALLBACK_2,
            "pdf_path":      str(settings.DPR_FORMAT_PDF),
            "pdf_exists":    settings.DPR_FORMAT_PDF.exists(),
        },
    }


@router.post("/ingest")
async def trigger_ingestion(
    background_tasks: BackgroundTasks,
    force: bool = False,
):
    """
    Trigger (re-)ingestion of DPR format Vol-I.pdf into ChromaDB.

    Args:
        force: If true, clears existing KB and re-ingests.

    This runs as a background task. Poll /api/kb/status to track progress.
    """
    global _ingestion_running

    if _ingestion_running:
        raise HTTPException(status_code=409, detail="Ingestion already in progress.")

    if not settings.DPR_FORMAT_PDF.exists():
        raise HTTPException(
            status_code=404,
            detail=f"DPR format PDF not found at: {settings.DPR_FORMAT_PDF}",
        )

    if not force and chroma_store.is_knowledge_base_ready():
        return {
            "message": "Knowledge base already populated. Use ?force=true to re-ingest.",
            "status": chroma_store.get_kb_status(),
        }

    background_tasks.add_task(_run_ingestion_bg, force=force)
    return {"message": "Ingestion started in background. Poll /api/kb/status for progress."}


async def _run_ingestion_bg(force: bool = False):
    """Background ingestion task."""
    global _ingestion_running, _ingestion_result
    _ingestion_running = True
    try:
        # Run the blocking ingestion in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _sync_ingest,
            force,
        )
        _ingestion_result = result
        logger.info(f"Background ingestion complete: {result}")
    except Exception as e:
        logger.exception(f"Background ingestion failed: {e}")
        _ingestion_result = {"error": str(e)}
    finally:
        _ingestion_running = False


def _sync_ingest(force: bool) -> dict:
    """Synchronous ingestion wrapper for executor."""
    from ingest_knowledge_base import ingest
    return ingest(
        pdf_path=settings.DPR_FORMAT_PDF,
        chunk_size=settings.CHUNK_SIZE_CHARS,
        overlap=settings.CHUNK_OVERLAP_CHARS,
        dry_run=False,
        force=force,
    )


@router.get("/ingestion-result")
async def get_ingestion_result():
    """Get the result of the last ingestion run."""
    return {
        "running": _ingestion_running,
        "result": _ingestion_result,
    }
