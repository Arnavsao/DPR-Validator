"""
RAG Scoring — Orchestrates the RAG-based DPR validation pipeline.

This replaces scoring.py as the primary validation path.
scoring.py is kept as a heuristic fallback (mode=heuristic).

── CHAPTER PILOT SCOPE ──────────────────────────────────────────────────────
Currently validating CHAPTER 1 ONLY (Executive Summary) as a pilot.
This keeps LLM calls to a minimum and lets us verify accuracy quickly.

To scale to more chapters:
  1. Add chapter numbers to ACTIVE_CHAPTER_NUMBERS below.
     e.g.  ACTIVE_CHAPTER_NUMBERS = {1, 2}   → adds Traffic Survey (Ch.2)
           ACTIVE_CHAPTER_NUMBERS = set()    → validates ALL detected chapters
  2. Each new chapter = ~1 LLM call. Budget ~5–15s per chapter (9b model).
  3. Table validation (Task 3) is disabled for now — uncomment when Ch.2+ active.
  4. Section dependency checks (Task 4) make sense only from Ch.15+ — disabled.

Pipeline (Chapter 1 pilot):
  1. Load document nodes + page texts from DB
  2. Structure check  — is Chapter 1 present at position 1?
  3. Chapter 1 completeness — is the Executive Summary complete?
  4. (Table & Dependency validation skipped in pilot — see SCALE comments below)
  5. Aggregate → ValidationRun + Finding rows with evidence
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

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


# ── Chapter Pilot Scope ────────────────────────────────────────────────────────
# Controls which chapter numbers go through LLM completeness validation.
#
# SCALE: To add more chapters, simply add their Vol-I number here.
#   {1}          → pilot:  Executive Summary only          (~1 LLM call)
#   {1, 2}       → pilot+: adds Traffic Survey             (~2 LLM calls)
#   {1, 2, 3}    → small:  adds Engineering Survey         (~3 LLM calls)
#   set()        → full:   ALL detected chapters validated  (~18 LLM calls)
#
# Note: an empty set() means "no filter" — ALL chapters are processed.
ACTIVE_CHAPTER_NUMBERS: set[int] = {1}

# Mapping from canonical chapter title → chapter number for filtering.
# This is consulted when chapter nodes don't have a numeric ID.
CHAPTER_TITLE_TO_NUMBER: dict[str, int] = {
    "Executive Summary": 1,
    "Traffic Survey": 2,
    "Engineering Survey": 3,
    "Land Requirement": 4,
    "Permanent Way": 5,
    "Formation, Tunnels & Bridges": 6,
    "Stations & Yards": 7,
    "Service Buildings": 8,
    "Residential Buildings": 9,
    "Shifting of Utilities": 10,
    "Electrical Traction & General": 11,
    "Signal & Telecommunication": 12,
    "Environmental Assessment and Social Impact Assessment": 13,
    "Statutory Clearances": 14,
    "Cost Estimates": 15,
    "Financial Analysis": 16,
    "Economic Analysis": 17,
    "Risk Analysis": 18,
}


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

async def _wait_if_paused(doc_id: int, db: AsyncSession) -> bool:
    """Blocks in asyncio.sleep loop if document is paused."""
    db.expire_all()
    first_pause = True
    prev_stage = None
    while True:
        stmt = select(Document.is_paused, Document.current_stage).where(Document.id == doc_id)
        res = await db.execute(stmt)
        row = res.fetchone()
        if not row:
            break
        is_paused, current_stage = row[0], row[1]
        
        if not is_paused:
            break
            
        if first_pause:
            logger.info(f"Document {doc_id} validation is PAUSED. Entering sleep loop...")
            prev_stage = current_stage if current_stage != "PAUSED — Click resume to continue..." else "Validating..."
            stmt_update = (
                update(Document)
                .where(Document.id == doc_id)
                .values(current_stage="PAUSED — Click resume to continue...")
            )
            await db.execute(stmt_update)
            await db.commit()
            first_pause = False
            
        await asyncio.sleep(1)
        db.expire_all()
    
    if not first_pause and prev_stage:
        stmt_restore = (
            update(Document)
            .where(Document.id == doc_id)
            .values(current_stage=prev_stage)
        )
        await db.execute(stmt_restore)
        await db.commit()
        
    return not first_pause


async def _update_progress(doc_id: int, db: AsyncSession, percent: int, stage: str, remaining_secs: int):
    """Update progress fields on Document."""
    stmt = (
        update(Document)
        .where(Document.id == doc_id)
        .values(
            progress_percent=percent,
            current_stage=stage,
            estimated_remaining_seconds=remaining_secs
        )
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(f"Doc {doc_id} validation progress: {percent}% | {stage} | ~{remaining_secs}s remaining")


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

    # Set state to VALIDATING and update initial progress
    doc.state = DocumentState.VALIDATING
    await db.commit()
    await _update_progress(doc_id, db, 2, "Starting RAG validation process...", 120)

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
        await db.commit()
        await _update_progress(doc_id, db, 100, "Validation complete (Knowledge base error)", 0)
        return run

    # ── Fetch document data ─────────────────────────────────────────────────
    # IMPORTANT: We eagerly materialize all DB objects into plain dicts here.
    # This prevents SQLAlchemy lazy-loading errors (greenlet_spawn) when
    # accessing attributes later from a different thread (asyncio.to_thread).
    await _wait_if_paused(doc_id, db)
    await _update_progress(doc_id, db, 4, "Fetching document sections and pages...", 115)
    
    # Chapter nodes → plain dicts
    chapter_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type == NodeType.CHAPTER,
        ).order_by(DocumentNode.sequence)
    )
    chapter_nodes_raw = chapter_result.scalars().all()
    chapter_nodes = [
        {"title": n.title, "number": n.number, "page_start": n.page_start, "sequence": n.sequence}
        for n in chapter_nodes_raw
    ]

    # Section nodes → plain dicts
    section_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type.in_([NodeType.SECTION, NodeType.SUBSECTION]),
        ).order_by(DocumentNode.sequence)
    )
    section_nodes_raw = section_result.scalars().all()
    section_nodes = [
        {"title": n.title, "page_start": n.page_start}
        for n in section_nodes_raw
    ]

    # All pages (for text retrieval)
    page_result = await db.execute(
        select(Page).where(Page.document_id == doc_id).order_by(Page.page_number)
    )
    all_pages = page_result.scalars().all()
    page_text_map: dict[int, str] = {p.page_number: (p.text or "") for p in all_pages}

    # Tables → plain dicts
    table_result = await db.execute(
        select(ExtractedTable).where(ExtractedTable.document_id == doc_id)
    )
    all_tables_raw = table_result.scalars().all()
    all_tables = [
        {
            "title": t.title or "Untitled",
            "category": t.category,
            "page": t.page_number,
            "rows": t.rows,
            "cols": t.cols,
        }
        for t in all_tables_raw
    ]

    detected_chapters = [
        {"title": n["title"], "number": n["number"], "page": n["page_start"]}
        for n in chapter_nodes
    ]

    all_results: list[ValidationResult] = []

    # ── Task 1: Structure validation (chapter presence + order) ─────────────
    # NOTE: All LLM and retrieval calls are synchronous (Ollama client + ChromaDB).
    # We MUST run them via asyncio.to_thread() to avoid blocking the async
    # SQLAlchemy greenlet context, which causes:
    #   "greenlet_spawn has not been called; can't call await_only()"
    await _wait_if_paused(doc_id, db)
    await _update_progress(doc_id, db, 5, "Validating document chapter structure...", 110)
    logger.info("Task 1: Structure validation...")
    
    spec_structure = await asyncio.to_thread(retrieve_mandatory_structure)
    if spec_structure:
        structure_results = await asyncio.to_thread(validate_structure, detected_chapters, spec_structure)
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
    #
    # PILOT: Only chapters whose sequence number is in ACTIVE_CHAPTER_NUMBERS
    # are validated in detail. This cuts LLM calls to the minimum needed for
    # the pilot test.
    #
    # SCALE: Expand ACTIVE_CHAPTER_NUMBERS (top of this file) to validate more.
    # SCALE: Remove the filter entirely (set ACTIVE_CHAPTER_NUMBERS = set())
    #        to validate ALL detected chapters automatically.
    #
    def _chapter_is_active(node: dict, idx: int) -> bool:
        """Return True if this chapter should be validated in detail."""
        if not ACTIVE_CHAPTER_NUMBERS:  # empty set → validate all
            return True
        # Try matching by node sequence (1-indexed) or by title lookup
        seq_num = idx + 1  # fallback: use discovery order as chapter number
        title_num = CHAPTER_TITLE_TO_NUMBER.get(node["title"], seq_num)
        return title_num in ACTIVE_CHAPTER_NUMBERS

    chapters_to_validate = [
        (idx, node) for idx, node in enumerate(chapter_nodes)
        if _chapter_is_active(node, idx)
    ]
    total_active = len(chapters_to_validate)
    total_chapters = len(chapter_nodes)
    logger.info(
        f"Task 2: Chapter completeness — validating {total_active}/{total_chapters} chapters "
        f"(active scope: {sorted(ACTIVE_CHAPTER_NUMBERS) or 'ALL'})"
    )

    for loop_idx, (ch_idx, ch_node) in enumerate(chapters_to_validate):
        # Pause check between chapters for high responsiveness
        await _wait_if_paused(doc_id, db)

        ch_title = ch_node["title"]

        # Progress: Task 2 maps to 10%–80% of validation progress.
        # Estimate ~6 seconds per chapter for a 9b model (adjust for larger models).
        # SCALE: Increase ch_remaining multiplier if using larger models:
        #   9b  model → ~6s/chapter
        #   32b model → ~12s/chapter
        ch_percent = 10 + int((loop_idx / max(total_active, 1)) * 70)
        ch_remaining = ((total_active - loop_idx) * 6) + 5  # 5s buffer for finalization
        await _update_progress(
            doc_id,
            db,
            ch_percent,
            f"Validating: {ch_title} ({loop_idx + 1}/{total_active})...",
            ch_remaining,
        )

        # Collect chapter text from its pages (start page + up to 4 following pages)
        ch_pages_text = ""
        if ch_node["page_start"]:
            for pn in range(ch_node["page_start"], ch_node["page_start"] + 5):
                ch_pages_text += page_text_map.get(pn, "")

        # Find subsections belonging to this chapter by page range
        ch_page_end = (
            chapter_nodes[ch_idx + 1]["page_start"]
            if ch_idx + 1 < len(chapter_nodes)
            else 9999
        )
        ch_sections = [
            n["title"] for n in section_nodes
            if n["page_start"] >= ch_node["page_start"] and n["page_start"] < ch_page_end
        ]

        # Retrieve matching spec chunks for this chapter (sync → thread)
        spec_chunks = await asyncio.to_thread(
            retrieve_for_chapter,
            ch_title,
            ch_pages_text[:400],
        )

        # Route: Executive Summary gets its own dedicated validator
        if any(kw in ch_title.lower() for kw in ("executive", "summary", "salient")):
            exec_spec = await asyncio.to_thread(retrieve_for_chapter, "Executive Summary", ch_pages_text[:400])
            result = await asyncio.to_thread(validate_executive_summary, ch_pages_text, exec_spec)
        else:
            # Generic chapter completeness check (sync → thread)
            result = await asyncio.to_thread(
                validate_chapter,
                ch_title,
                ch_pages_text,
                spec_chunks,
                ch_sections[:10] if ch_sections else None,
            )

        all_results.append(result)
        logger.info(f"  {ch_title}: {result.status} (conf={result.confidence:.2f})")

    # ── Task 3: Table validation ──────────────────────────────────────────────
    # PILOT: Skipped — tables are scattered across many chapters (2, 4, 6, 15–18).
    # Running table validation only makes sense once those chapters are in scope.
    #
    # SCALE: When ACTIVE_CHAPTER_NUMBERS includes {2, 4, 6, 15, 16, 17, 18},
    #   uncomment the block below to re-enable table validation:
    #
    # await _wait_if_paused(doc_id, db)
    # await _update_progress(doc_id, db, 82, "Validating mandatory table compliance...", 12)
    # logger.info("Task 3: Table validation...")
    # table_spec_chunks = retrieve_for_query(
    #     "mandatory tables required DPR format", collection=COLLECTION_TABLE, top_k=15
    # )
    # if not table_spec_chunks:
    #     table_spec_chunks = retrieve_for_query(
    #         "required tables FIRR EIRR traffic earnings cost land bridges", top_k=8
    #     )
    # if table_spec_chunks:
    #     table_results = validate_tables(detected_table_dicts, table_spec_chunks)
    #     all_results.extend(table_results)
    #     tbl_pass = sum(1 for r in table_results if r.status == "PASS")
    #     logger.info(f"Tables: {tbl_pass}/{len(table_results)} passed.")
    logger.info("Task 3: Table validation SKIPPED (pilot — Ch.1 only). "
                "SCALE: Uncomment Task 3 block when Ch.2+ chapters are in scope.")

    # ── Task 4: Section dependencies ──────────────────────────────────────────
    # PILOT: Skipped — cross-chapter dependencies (FIRR/EIRR) require Financial
    # Analysis (Ch.16–17) and Traffic (Ch.2) to be present. Meaningless for Ch.1 alone.
    #
    # SCALE: When ACTIVE_CHAPTER_NUMBERS includes {2, 15, 16, 17, 18},
    #   uncomment the block below to re-enable dependency validation:
    #
    # await _wait_if_paused(doc_id, db)
    # await _update_progress(doc_id, db, 92, "Analyzing inter-section dependencies...", 5)
    # logger.info("Task 4: Section dependency checks...")
    # present_chapter_titles = [n.title for n in chapter_nodes]
    # dep_spec_chunks = retrieve_for_query(
    #     "FIRR EIRR financial economic analysis dependency traffic cost", top_k=5
    # )
    # dep_results = validate_section_dependencies(present_chapter_titles, dep_spec_chunks)
    # all_results.extend(dep_results)
    # if dep_results:
    #     logger.info(f"Dependencies: {len(dep_results)} issues found.")
    logger.info("Task 4: Dependency checks SKIPPED (pilot — Ch.1 only). "
                "SCALE: Uncomment Task 4 block when Ch.15+ chapters are in scope.")

    # ── Compute scores ───────────────────────────────────────────────────────
    await _update_progress(doc_id, db, 95, "Synthesizing scores and final findings...", 1)
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

    # Update document state and progress
    doc.state = DocumentState.VALIDATED
    await db.commit()
    await _update_progress(doc_id, db, 100, "Validation complete", 0)

    logger.info(f"Persisted {len(all_results)} findings for doc {doc_id}.")
    return run


def _add_finding(db, run_id: int, finding: Finding) -> None:
    """Helper to add a finding to the session."""
    db.add(finding)
