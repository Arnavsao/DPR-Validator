"""
RAG Scoring — Orchestrates the full RAG-based DPR validation pipeline.

This replaces scoring.py as the primary validation path.
scoring.py is kept as a heuristic fallback (mode=heuristic).

Pipeline:
  1. Load document nodes + page texts from DB
  2. Structure check (chapter order + presence)
  3. Per-chapter: retrieve spec context → LLM completeness check
  4. Table validation
  5. Section dependency checks
  6. Executive summary check
  7. Aggregate → ValidationRun + Finding rows with evidence
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from models.db_models import (
    Document, DocumentNode, Page, ExtractedTable,
    ValidationRun, Finding, DocumentState,
    NodeType, TableCategory, FindingSeverity, MatchType,
)
from rag.chroma_store import chroma_store
from rag.retriever import (
    retrieve_mandatory_structure,
    retrieve_for_chapter,
    retrieve_for_section,
    retrieve_for_table,
    retrieve_for_query,
    format_chunks_as_context,
    COLLECTION_TABLE,
)
from rag.llm_validator import (
    ValidationResult,
    validate_structure,
    validate_chapter,
    validate_tables,
    validate_section_dependencies,
    validate_executive_summary,
)

logger = logging.getLogger(__name__)


# ── Severity mapping ───────────────────────────────────────────────────────────

_STATUS_TO_SEVERITY = {
    "FAIL":    FindingSeverity.CRITICAL,
    "WARNING": FindingSeverity.MAJOR,
    "UNKNOWN": FindingSeverity.MINOR,
    "PASS":    FindingSeverity.INFO,
}

_CATEGORY_MAP = {
    "structure":  "chapter",
    "chapter":    "chapter",
    "table":      "table",
    "dependency": "dependency",
    "section":    "section",
}


# ── Grade computation ──────────────────────────────────────────────────────────

_GRADE_MAP = [
    (95, "Gold"),
    (85, "Acceptable"),
    (70, "Partial"),
    (50, "Legacy"),
    (0,  "Invalid"),
]


def _compute_grade(score: float) -> str:
    for threshold, grade in _GRADE_MAP:
        if score >= threshold:
            return grade
    return "Invalid"


def _compute_rag_score(results: list[ValidationResult]) -> dict:
    """
    Compute weighted validation score from RAG results.

    Score = weighted average of per-chapter confidence-adjusted outcomes.
    PASS = 100pts, WARNING = 50pts, FAIL = 0pts, UNKNOWN = 30pts
    """
    if not results:
        return {"overall": 0.0, "chapter": 0.0, "table": 0.0, "structure": 0.0}

    status_scores = {"PASS": 100.0, "WARNING": 50.0, "FAIL": 0.0, "UNKNOWN": 30.0}

    def _group_score(group: list[ValidationResult]) -> float:
        if not group:
            return 0.0
        total = 0.0
        weight_sum = 0.0
        for r in group:
            base = status_scores.get(r.status, 30.0)
            # Weight by confidence (high-confidence results count more)
            w = max(0.1, r.confidence)
            total += base * w
            weight_sum += w
        return round(total / weight_sum, 2) if weight_sum > 0 else 0.0

    structure_results = [r for r in results if r.category == "structure"]
    chapter_results   = [r for r in results if r.category == "chapter"]
    table_results     = [r for r in results if r.category == "table"]
    dep_results       = [r for r in results if r.category == "dependency"]
    all_non_info      = [r for r in results if r.status != "PASS"]

    structure_score = _group_score(structure_results)
    chapter_score   = _group_score(chapter_results)
    table_score     = _group_score(table_results)
    dep_score       = _group_score(dep_results) if dep_results else 100.0

    # Weighted overall (structure presence is most critical)
    overall = (
        structure_score * 0.40 +
        chapter_score   * 0.35 +
        table_score     * 0.15 +
        dep_score       * 0.10
    )
    overall = round(overall, 2)

    chapters_passed = sum(1 for r in structure_results if r.status == "PASS")
    chapters_total  = len(structure_results)

    return {
        "overall":   overall,
        "structure": structure_score,
        "chapter":   chapter_score,
        "table":     table_score,
        "dependency": dep_score,
        "chapters_found": chapters_passed,
        "chapters_total": chapters_total,
    }


# ── Main Orchestrator ──────────────────────────────────────────────────────────

async def run_rag_validation(doc_id: int, db: AsyncSession) -> Optional[ValidationRun]:
    """
    Full RAG-based validation pipeline for a document.

    Returns the ValidationRun ORM object, or None on failure.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        logger.error(f"Document {doc_id} not found.")
        return None

    logger.info(f"Starting RAG validation for doc {doc_id}: {doc.original_name}")

    # ── Check KB readiness ──────────────────────────────────────────────────
    if not chroma_store.is_knowledge_base_ready():
        logger.error(
            "ChromaDB knowledge base not populated. "
            "Run: python ingest_knowledge_base.py"
        )
        run = ValidationRun(
            document_id=doc_id,
            overall_score=0.0,
            grade="Invalid",
            chapters_found=0,
            chapters_total=0,
            tables_found=0,
            validation_mode="rag",
        )
        db.add(run)
        await db.flush()
        _add_finding(db, run.id, Finding(
            run_id=run.id,
            category="system",
            severity=FindingSeverity.CRITICAL,
            issue="Knowledge base not ready. Run ingest_knowledge_base.py first.",
            detail=(
                "ChromaDB is empty. The DPR format Vol-I.pdf must be ingested "
                "before RAG validation can run."
            ),
            confidence=1.0,
        ))
        await db.flush()
        doc.state = DocumentState.VALIDATED
        await db.flush()
        return run

    # ── Fetch document data ─────────────────────────────────────────────────
    # Chapter nodes
    chapter_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type == NodeType.CHAPTER,
        ).order_by(DocumentNode.sequence)
    )
    chapter_nodes = chapter_result.scalars().all()

    # Section nodes
    section_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type.in_([NodeType.SECTION, NodeType.SUBSECTION]),
        ).order_by(DocumentNode.sequence)
    )
    section_nodes = section_result.scalars().all()

    # All pages (for text retrieval)
    page_result = await db.execute(
        select(Page).where(Page.document_id == doc_id).order_by(Page.page_number)
    )
    all_pages = page_result.scalars().all()
    page_text_map: dict[int, str] = {p.page_number: (p.text or "") for p in all_pages}

    # Tables
    table_result = await db.execute(
        select(ExtractedTable).where(ExtractedTable.document_id == doc_id)
    )
    all_tables = table_result.scalars().all()

    detected_chapters = [
        {"title": n.title, "number": n.number, "page": n.page_start}
        for n in chapter_nodes
    ]
    detected_table_dicts = [
        {
            "title": t.title or "Untitled",
            "category": t.category,
            "page": t.page_number,
            "rows": t.rows,
            "cols": t.cols,
        }
        for t in all_tables
    ]

    all_results: list[ValidationResult] = []

    # ── Task 1: Structure validation (chapter presence + order) ─────────────
    logger.info("Task 1: Structure validation...")
    spec_structure = retrieve_mandatory_structure()
    if spec_structure:
        structure_results = validate_structure(detected_chapters, spec_structure)
        all_results.extend(structure_results)
        pass_count  = sum(1 for r in structure_results if r.status == "PASS")
        total_count = len(structure_results)
        logger.info(f"Structure: {pass_count}/{total_count} chapters passed.")
    else:
        logger.warning("No spec chunks for structure — KB may be empty.")
        all_results.append(ValidationResult(
            chapter="Structure",
            category="structure",
            status="UNKNOWN",
            reason="Knowledge base spec chunks not available.",
            confidence=0.0,
        ))

    # ── Task 2: Per-chapter completeness ────────────────────────────────────
    logger.info(f"Task 2: Chapter-level completeness ({len(chapter_nodes)} chapters)...")
    for ch_idx, ch_node in enumerate(chapter_nodes):
        ch_title = ch_node.title

        # Collect chapter text from its pages
        ch_pages_text = ""
        if ch_node.page_start:
            # Get text from chapter start page + next few pages
            for pn in range(ch_node.page_start, ch_node.page_start + 5):
                ch_pages_text += page_text_map.get(pn, "")

        # Find subsections for this chapter (by page range)
        ch_page_end = (
            chapter_nodes[ch_idx + 1].page_start
            if ch_idx + 1 < len(chapter_nodes)
            else 9999
        )
        ch_sections = [
            n.title for n in section_nodes
            if n.page_start >= ch_node.page_start and n.page_start < ch_page_end
        ]

        # Retrieve relevant spec chunks
        spec_chunks = retrieve_for_chapter(
            chapter_title=ch_title,
            chapter_text=ch_pages_text[:400],
        )

        # Special case: executive summary
        if any(kw in ch_title.lower() for kw in ("executive", "summary", "salient")):
            exec_spec = retrieve_for_chapter("Executive Summary", ch_pages_text[:400])
            result = validate_executive_summary(ch_pages_text, exec_spec)
        else:
            result = validate_chapter(
                chapter_title=ch_title,
                chapter_text=ch_pages_text,
                spec_chunks=spec_chunks,
                section_titles=ch_sections[:10] if ch_sections else None,
            )

        all_results.append(result)
        logger.info(f"  {ch_title}: {result.status} (conf={result.confidence:.2f})")

    # ── Task 3: Table validation ─────────────────────────────────────────────
    logger.info("Task 3: Table validation...")
    table_spec_chunks = retrieve_for_query(
        "mandatory tables required DPR format",
        collection=COLLECTION_TABLE,
        top_k=15,
    )
    if not table_spec_chunks:
        # Fallback: use chapter collection for table info
        table_spec_chunks = retrieve_for_query(
            "required tables FIRR EIRR traffic earnings cost land bridges",
            top_k=8,
        )

    if table_spec_chunks:
        table_results = validate_tables(detected_table_dicts, table_spec_chunks)
        all_results.extend(table_results)
        tbl_pass = sum(1 for r in table_results if r.status == "PASS")
        logger.info(f"Tables: {tbl_pass}/{len(table_results)} passed.")
    else:
        logger.warning("No table spec chunks retrieved — skipping table validation.")

    # ── Task 4: Section dependencies ─────────────────────────────────────────
    logger.info("Task 4: Section dependency checks...")
    present_chapter_titles = [n.title for n in chapter_nodes]
    dep_spec_chunks = retrieve_for_query(
        "FIRR EIRR financial economic analysis dependency traffic cost",
        top_k=5,
    )
    dep_results = validate_section_dependencies(present_chapter_titles, dep_spec_chunks)
    all_results.extend(dep_results)
    if dep_results:
        logger.info(f"Dependencies: {len(dep_results)} issues found.")

    # ── Compute scores ───────────────────────────────────────────────────────
    scores = _compute_rag_score(all_results)
    overall_score = scores["overall"]
    grade = _compute_grade(overall_score)

    logger.info(
        f"RAG Validation complete: score={overall_score} grade={grade} "
        f"chapters={scores['chapters_found']}/{scores['chapters_total']}"
    )

    # ── Persist ValidationRun ───────────────────────────────────────────────
    run = ValidationRun(
        document_id=doc_id,
        overall_score=overall_score,
        chapter_score=round(scores.get("structure", 0), 2),
        subchapter_score=round(scores.get("chapter", 0), 2),
        traffic_score=None,
        engineering_score=None,
        risk_score=None,
        cost_score=None,
        table_score=round(scores.get("table", 0), 2),
        grade=grade,
        chapters_found=scores["chapters_found"],
        chapters_total=scores["chapters_total"],
        tables_found=len(all_tables),
        validation_mode="rag",
    )
    db.add(run)
    await db.flush()  # get run.id

    # ── Persist Findings ─────────────────────────────────────────────────────
    for vr in all_results:
        severity = _STATUS_TO_SEVERITY.get(vr.status, FindingSeverity.MINOR)
        category = _CATEGORY_MAP.get(vr.category, vr.category)

        finding = Finding(
            run_id=run.id,
            category=category,
            severity=severity,
            issue=f"[{vr.status}] {vr.chapter}",
            detail=vr.reason or "",
            match_type=MatchType.MISSING if vr.status == "FAIL" else (
                MatchType.EXACT if vr.status == "PASS" else None
            ),
            confidence=vr.confidence,
            page=None,
            snippet=vr.evidence[:500] if vr.evidence else None,
            reference_section=vr.reference_section or "",
            evidence=vr.evidence or "",
            suggested_correction="\n".join(vr.missing_items) if vr.missing_items else vr.suggested_correction,
        )
        db.add(finding)

    await db.flush()

    # Update document state
    doc.state = DocumentState.VALIDATED
    await db.flush()

    logger.info(f"Persisted {len(all_results)} findings for doc {doc_id}.")
    return run


def _add_finding(db, run_id: int, finding: Finding) -> None:
    """Helper to add a finding to the session."""
    db.add(finding)
