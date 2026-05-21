"""
Reports API — generate and retrieve full validation reports.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.deps import get_db
from models.db_models import (
    Document, ValidationRun, Finding, Report, DocumentNode, ExtractedTable, NodeType
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{doc_id}")
async def get_report(doc_id: int, db: AsyncSession = Depends(get_db)):
    """
    Generate and return a full validation report for a document.
    Includes: document metadata, scores, chapter results, findings, table summary.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Latest validation run
    run_result = await db.execute(
        select(ValidationRun)
        .where(ValidationRun.document_id == doc_id)
        .order_by(desc(ValidationRun.run_at))
        .limit(1)
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="No validation run found. Run validation first.")

    # Findings
    findings_result = await db.execute(
        select(Finding).where(Finding.run_id == run.id).order_by(Finding.severity)
    )
    findings = findings_result.scalars().all()

    # Chapter nodes
    nodes_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type == NodeType.CHAPTER,
        ).order_by(DocumentNode.sequence)
    )
    chapters = nodes_result.scalars().all()

    # Tables
    tables_result = await db.execute(
        select(ExtractedTable).where(ExtractedTable.document_id == doc_id)
    )
    tables = tables_result.scalars().all()

    # Build report
    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document": {
            "id": doc.id,
            "name": doc.original_name,
            "pages": doc.page_count,
            "size_bytes": doc.file_size,
            "project_name": doc.project_name,
            "project_route": doc.project_route,
            "division": doc.division,
            "length_km": doc.length_km,
            "report_date": doc.report_date,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "parsed_at": doc.parsed_at.isoformat() if doc.parsed_at else None,
        },
        "validation": {
            "run_id": run.id,
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
        },
        "chapters_detected": [
            {
                "number": c.number,
                "title": c.title,
                "page_start": c.page_start,
            }
            for c in chapters
        ],
        "tables_summary": {
            "total": len(tables),
            "by_category": _group_by_category(tables),
        },
        "findings": [
            {
                "category": f.category,
                "severity": f.severity,
                "issue": f.issue,
                "detail": f.detail,
                "page": f.page,
                "confidence": f.confidence,
                "snippet": f.snippet,
            }
            for f in findings
        ],
    }

    return report_data


def _group_by_category(tables) -> dict:
    counts: dict[str, int] = {}
    for t in tables:
        cat = str(t.category)
        counts[cat] = counts.get(cat, 0) + 1
    return counts
