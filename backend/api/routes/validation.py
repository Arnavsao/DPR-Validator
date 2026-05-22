"""
Validation API — run validation and retrieve scores/findings/evidence.
Supports two modes:
  - rag        (default): RAG pipeline using Ollama LLM + ChromaDB
  - heuristic:            Original regex/fuzzy/scoring engine (fast fallback)
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.deps import get_db
from models.db_models import (
    Document, DocumentNode, Page, ValidationRun, Finding,
    DocumentState, NodeType,
)
from validator.scoring import run_validation
from validator.rag_scoring import run_rag_validation

router = APIRouter(prefix="/api/validate", tags=["validation"])


@router.post("/{doc_id}")
async def validate_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    mode: str = Query(default="rag", description="Validation mode: 'rag' (default) or 'heuristic'"),
    db: AsyncSession = Depends(get_db),
):
    """
    Run validation on a parsed document.

    Args:
        doc_id: Document ID to validate.
        mode: 'rag' uses the full LLM+ChromaDB pipeline (slow, high accuracy).
              'heuristic' uses the original regex/fuzzy engine (fast, low accuracy).
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.state not in (
        DocumentState.STRUCTURED,
        DocumentState.VALIDATED,
        DocumentState.FAILED,
        DocumentState.VALIDATING,  # allow re-trigger to unstick hung validations
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Document must be in STRUCTURED state. Current: {doc.state}"
        )

    if mode not in ("rag", "heuristic"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{mode}'. Must be 'rag' or 'heuristic'."
        )

    background_tasks.add_task(_validate_bg, doc_id, mode)
    return {
        "message": f"Validation started for document {doc_id} in '{mode}' mode.",
        "mode": mode,
        "note": (
            "RAG validation may take 2–10 minutes depending on document size and LLM speed. "
            "Poll /api/validate/{doc_id}/result for status."
        ) if mode == "rag" else "Heuristic validation is fast (~5s).",
    }


async def _validate_bg(doc_id: int, mode: str = "rag"):
    from core.database import AsyncSessionLocal
    from sqlalchemy import update as sa_update
    import logging
    import traceback
    _log = logging.getLogger(__name__)
    async with AsyncSessionLocal() as db:
        try:
            if mode == "rag":
                await run_rag_validation(doc_id, db)
            else:
                await run_validation(doc_id, db)
            await db.commit()
            _log.info(f"Validation complete: doc={doc_id} mode={mode}")
        except Exception as e:
            await db.rollback()
            tb = traceback.format_exc()
            _log.error(f"Validation failed for doc {doc_id} (mode={mode}): {e}\n{tb}")
            # Reset document state so it can be re-triggered
            try:
                async with AsyncSessionLocal() as db2:
                    stmt = sa_update(Document).where(Document.id == doc_id).values(
                        state=DocumentState.STRUCTURED,
                        error_message=f"Validation failed: {e}",
                        current_stage=f"Validation error: {str(e)[:100]}",
                        progress_percent=0,
                        estimated_remaining_seconds=0,
                    )
                    await db2.execute(stmt)
                    await db2.commit()
                    _log.info(f"Doc {doc_id} reset to STRUCTURED after validation failure.")
            except Exception as reset_err:
                _log.error(f"Failed to reset doc {doc_id} state: {reset_err}")


@router.get("/{doc_id}/result")
async def get_validation_result(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Return the latest validation run scores."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    result = await db.execute(
        select(ValidationRun)
        .where(ValidationRun.document_id == doc_id)
        .order_by(desc(ValidationRun.run_at))
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No validation run found. Run validation first.")

    return {
        "run_id": run.id,
        "document_id": doc_id,
        "run_at": run.run_at.isoformat(),
        "validation_mode": getattr(run, "validation_mode", "heuristic"),
        "overall_score": run.overall_score,
        "grade": run.grade,
        "chapters_found": run.chapters_found,
        "chapters_total": run.chapters_total,
        "tables_found": run.tables_found,
        "scores": {
            # Primary names — match frontend ValidationResult interface
            "chapter_structure":    run.chapter_score,
            "chapter_completeness": run.subchapter_score,
            "table":                run.table_score,
            # Legacy aliases for backward compat with older frontend code
            "chapter":    run.chapter_score,
            "subchapter": run.subchapter_score,
            "traffic":    getattr(run, "traffic_score",     None),
            "engineering":getattr(run, "engineering_score", None),
            "risk":       getattr(run, "risk_score",        None),
            "cost":       getattr(run, "cost_score",        None),
        },
    }


@router.get("/{doc_id}/evidence")
async def get_validation_evidence(doc_id: int, db: AsyncSession = Depends(get_db)):
    """
    Return grounded findings/evidence for the latest validation run.
    RAG mode findings include: reference_section, evidence, suggested_correction.
    """
    result = await db.execute(
        select(ValidationRun)
        .where(ValidationRun.document_id == doc_id)
        .order_by(desc(ValidationRun.run_at))
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No validation run found.")

    findings_result = await db.execute(
        select(Finding).where(Finding.run_id == run.id).order_by(Finding.severity)
    )
    findings = findings_result.scalars().all()

    return {
        "run_id": run.id,
        "validation_mode": getattr(run, "validation_mode", "heuristic"),
        "findings": [
            {
                "id": f.id,
                "category": f.category,
                "severity": f.severity,
                "issue": f.issue,
                "detail": f.detail,
                "match_type": f.match_type,
                "confidence": f.confidence,
                "page": f.page,
                "snippet": f.snippet,
                # RAG-specific grounded evidence fields
                "reference_section": getattr(f, "reference_section", None),
                "evidence": getattr(f, "evidence", None),
                "suggested_correction": getattr(f, "suggested_correction", None),
            }
            for f in findings
        ],
    }


@router.get("/{doc_id}/rag-status")
async def get_rag_readiness(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Check whether the document and KB are ready for RAG validation."""
    from rag.chroma_store import chroma_store
    from rag.embedder import check_ollama_connection

    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    kb_ready = chroma_store.is_knowledge_base_ready()
    ollama_ok, ollama_msg = check_ollama_connection()
    doc_ready = doc.state in (DocumentState.STRUCTURED, DocumentState.VALIDATED, DocumentState.FAILED)

    return {
        "doc_id": doc_id,
        "doc_state": doc.state,
        "doc_ready_for_validation": doc_ready,
        "kb_ready": kb_ready,
        "ollama_connected": ollama_ok,
        "ollama_message": ollama_msg,
        "rag_validation_possible": kb_ready and ollama_ok and doc_ready,
    }
