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

    # ── Build chapter-wise results from findings ────────────────────────────
    # The 18 mandatory DPR chapters per Vol-I spec
    MANDATORY_CHAPTERS: list[tuple[int, str]] = [
        (1,  "Executive Summary"),
        (2,  "Traffic Survey"),
        (3,  "Engineering Survey"),
        (4,  "Land Requirement"),
        (5,  "Permanent Way"),
        (6,  "Formation, Tunnels & Bridges"),
        (7,  "Stations & Yards"),
        (8,  "Service Buildings"),
        (9,  "Residential Buildings"),
        (10, "Shifting of Utilities"),
        (11, "Electrical Traction & General"),
        (12, "Signal & Telecommunication"),
        (13, "Environmental Assessment and Social Impact Assessment"),
        (14, "Statutory Clearances"),
        (15, "Cost Estimates"),
        (16, "Financial Analysis"),
        (17, "Economic Analysis"),
        (18, "Risk Analysis"),
    ]

    # Map severity enum → status string and numeric score
    _severity_to_status = {
        "FindingSeverity.INFO":     ("PASS",    100.0),
        "FindingSeverity.MAJOR":    ("WARNING",  50.0),
        "FindingSeverity.MINOR":    ("UNKNOWN",  30.0),
        "FindingSeverity.CRITICAL": ("FAIL",      0.0),
        "info":     ("PASS",    100.0),
        "major":    ("WARNING",  50.0),
        "minor":    ("UNKNOWN",  30.0),
        "critical": ("FAIL",      0.0),
    }

    # Parse chapter findings into a lookup by chapter name
    chapter_finding_map: dict[str, dict] = {}
    for f in findings:
        if f.category != "chapter":
            continue
        # issue format: "[PASS] Executive Summary" or "[FAIL] Traffic Survey"
        issue_str = f.issue or ""
        if "] " in issue_str:
            status_tag, ch_name = issue_str.split("] ", 1)
            status = status_tag.lstrip("[").upper()
        else:
            ch_name = issue_str
            status, _ = _severity_to_status.get(str(f.severity), ("UNKNOWN", 30.0))

        _sev_key = str(f.severity)
        _, score = _severity_to_status.get(_sev_key, ("UNKNOWN", 30.0))
        # Override score from parsed status for accuracy
        _status_to_score = {"PASS": 100.0, "WARNING": 50.0, "UNKNOWN": 30.0, "FAIL": 0.0}
        score = _status_to_score.get(status, score)

        chapter_finding_map[ch_name.strip()] = {
            "status":               status,
            "score":                score,
            "confidence":           f.confidence or 0.0,
            "detail":               f.detail or "",
            "reference_section":    f.reference_section or "",
            "suggested_correction": f.suggested_correction or "",
            "snippet":              (f.snippet or "")[:300],
        }

    # Build full 18-chapter results, merging findings data
    chapter_results = []
    for num, title in MANDATORY_CHAPTERS:
        # Try exact match first, then fuzzy containment
        match = chapter_finding_map.get(title)
        if match is None:
            for found_title, found_data in chapter_finding_map.items():
                if title.lower() in found_title.lower() or found_title.lower() in title.lower():
                    match = found_data
                    break

        if match:
            chapter_results.append({
                "number":               num,
                "title":                title,
                "status":               match["status"],
                "score":                match["score"],
                "confidence":           match["confidence"],
                "detail":               match["detail"],
                "reference_section":    match["reference_section"],
                "suggested_correction": match["suggested_correction"],
                "snippet":              match["snippet"],
            })
        else:
            # No finding for this chapter — fallback to FAIL (not found)
            chapter_results.append({
                "number":               num,
                "title":                title,
                "status":               "FAIL",
                "score":                0.0,
                "confidence":           1.0,
                "detail":               "Not found in uploaded document.",
                "reference_section":    f"Vol-I, Chapter {num}",
                "suggested_correction": f"Add Chapter {num}: {title} to the DPR.",
                "snippet":              "",
            })

    # Build report
    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document": {
            "id":           doc.id,
            "name":         doc.original_name,
            "pages":        doc.page_count,
            "size_bytes":   doc.file_size,
            "project_name": doc.project_name,
            "project_route":doc.project_route,
            "division":     doc.division,
            "length_km":    doc.length_km,
            "report_date":  doc.report_date,
            "uploaded_at":  doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "parsed_at":    doc.parsed_at.isoformat() if doc.parsed_at else None,
        },
        "validation": {
            "run_id":         run.id,
            "run_at":         run.run_at.isoformat(),
            "overall_score":  run.overall_score,
            "grade":          run.grade,
            "chapters_found": run.chapters_found,
            "chapters_total": run.chapters_total,
            "tables_found":   run.tables_found,
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
        "chapter_results": chapter_results,   # full 18-chapter breakdown
        "chapters_detected": [
            {
                "number":     c.number,
                "title":      c.title,
                "page_start": c.page_start,
            }
            for c in chapters
        ],
        "tables_summary": {
            "total":       len(tables),
            "by_category": _group_by_category(tables),
        },
        "findings": [
            {
                "category":   f.category,
                "severity":   f.severity,
                "issue":      f.issue,
                "detail":     f.detail,
                "page":       f.page,
                "confidence": f.confidence,
                "snippet":    f.snippet,
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
