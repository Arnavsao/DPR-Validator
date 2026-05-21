"""
Validation API — run validation and retrieve scores/findings/evidence.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.deps import get_db
from models.db_models import (
    Document, DocumentNode, Page, ValidationRun, Finding,
    DocumentState, NodeType,
)
from validator.scoring import run_validation

router = APIRouter(prefix="/api/validate", tags=["validation"])


@router.post("/{doc_id}")
async def validate_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Run validation on a parsed document (background task)."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.state not in (DocumentState.STRUCTURED, DocumentState.VALIDATED, DocumentState.FAILED):
        raise HTTPException(
            status_code=400,
            detail=f"Document must be in STRUCTURED state. Current: {doc.state}"
        )

    background_tasks.add_task(_validate_bg, doc_id)
    return {"message": f"Validation started for document {doc_id}."}


async def _validate_bg(doc_id: int):
    from core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            await run_validation(doc_id, db)
            await db.commit()
        except Exception as e:
            await db.rollback()
            import logging
            logging.getLogger(__name__).error(f"Validation failed for doc {doc_id}: {e}")


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
        "overall_score": run.overall_score,
        "grade": run.grade,
        "chapters_found": run.chapters_found,
        "chapters_total": run.chapters_total,
        "tables_found": run.tables_found,
        "scores": {
            "chapter":     run.chapter_score,
            "subchapter":  run.subchapter_score,
            "traffic":     run.traffic_score,
            "engineering": run.engineering_score,
            "risk":        run.risk_score,
            "cost":        run.cost_score,
            "table":       run.table_score,
        },
    }


@router.get("/{doc_id}/evidence")
async def get_validation_evidence(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Return grounded findings/evidence for the latest validation run."""
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

    return [
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
        }
        for f in findings
    ]
