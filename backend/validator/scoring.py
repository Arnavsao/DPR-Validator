"""
Scoring engine — computes weighted validation scores for a DPR document.
All scoring is deterministic: based on chapter presence, table counts,
and keyword-based heuristics. No AI.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.db_models import (
    Document, DocumentNode, ExtractedTable, ValidationRun, Finding,
    NodeType, TableCategory, FindingSeverity, MatchType,
)
from validator.format_engine import format_engine, ChapterMatchResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score weights — must sum to 1.0
# ---------------------------------------------------------------------------
WEIGHTS = {
    "chapter_score":     0.40,
    "subchapter_score":  0.15,
    "traffic_score":     0.10,
    "engineering_score": 0.10,
    "risk_score":        0.10,
    "cost_score":        0.10,
    "table_score":       0.05,
}

GRADE_MAP = [
    (95, "Gold"),
    (85, "Acceptable"),
    (70, "Partial"),
    (50, "Legacy"),
    (0,  "Invalid"),
]


@dataclass
class ScoreResult:
    overall_score: float
    chapter_score: float
    subchapter_score: float
    traffic_score: float
    engineering_score: float
    risk_score: float
    cost_score: float
    table_score: float
    grade: str
    chapters_found: int
    chapters_total: int
    tables_found: int
    chapter_results: list[ChapterMatchResult]
    findings: list[dict]


def compute_grade(score: float) -> str:
    for threshold, grade in GRADE_MAP:
        if score >= threshold:
            return grade
    return "Invalid"


async def run_validation(doc_id: int, db: AsyncSession) -> Optional[ValidationRun]:
    """
    Run the full validation suite for a document and persist a ValidationRun.

    Returns the ValidationRun ORM object, or None on failure.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        logger.error(f"Document {doc_id} not found.")
        return None

    # ---- Fetch chapter nodes from DB ----
    nodes_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type == NodeType.CHAPTER,
        ).order_by(DocumentNode.sequence)
    )
    chapter_nodes = nodes_result.scalars().all()

    # ---- Fetch section/subsection nodes ----
    sub_result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type.in_([NodeType.SECTION, NodeType.SUBSECTION]),
        )
    )
    sub_nodes = sub_result.scalars().all()

    # ---- Fetch tables ----
    tbl_result = await db.execute(
        select(ExtractedTable).where(ExtractedTable.document_id == doc_id)
    )
    tables = tbl_result.scalars().all()

    # Build chapter list for format engine
    detected_chapters = [
        {"title": n.title, "number": n.number, "page": n.page_start}
        for n in chapter_nodes
    ]

    # ---- Run format check ----
    fmt_result = format_engine.check_document(detected_chapters)

    # ---- Individual scores ----
    chapter_score = fmt_result.chapter_score

    # Subchapter score: ratio of sections found to expected minimum (3 per chapter)
    expected_subsections = fmt_result.chapters_total * 3
    actual_subsections = len(sub_nodes)
    subchapter_score = min(100, (actual_subsections / expected_subsections) * 100) if expected_subsections > 0 else 0

    # Traffic score: traffic chapter present + traffic tables
    traffic_chapter = _chapter_found(fmt_result, "Traffic Survey")
    traffic_tables = sum(1 for t in tables if t.category in (TableCategory.TRAFFIC, TableCategory.EARNINGS))
    traffic_score = _component_score(traffic_chapter, traffic_tables, min_tables=1)

    # Engineering score: engineering survey chapter + presence of alignment data
    eng_chapter = _chapter_found(fmt_result, "Engineering Survey")
    engineering_score = 100.0 if eng_chapter else 0.0

    # Risk score: risk chapter + risk tables
    risk_chapter = _chapter_found(fmt_result, "Risk Analysis")
    risk_tables = sum(1 for t in tables if t.category == TableCategory.RISK)
    risk_score = _component_score(risk_chapter, risk_tables, min_tables=0)

    # Cost score: cost chapter + BoQ/cost tables
    cost_chapter = _chapter_found(fmt_result, "Cost Estimates")
    cost_tables = sum(1 for t in tables if t.category in (TableCategory.COST, TableCategory.BOQ))
    cost_score = _component_score(cost_chapter, cost_tables, min_tables=1)

    # Table score: total tables vs minimum expected
    min_tables = 15
    table_score = min(100, (len(tables) / min_tables) * 100) if min_tables > 0 else 0

    # ---- Overall weighted score ----
    overall_score = (
        chapter_score     * WEIGHTS["chapter_score"]     +
        subchapter_score  * WEIGHTS["subchapter_score"]  +
        traffic_score     * WEIGHTS["traffic_score"]     +
        engineering_score * WEIGHTS["engineering_score"] +
        risk_score        * WEIGHTS["risk_score"]        +
        cost_score        * WEIGHTS["cost_score"]        +
        table_score       * WEIGHTS["table_score"]
    )
    overall_score = round(overall_score, 2)
    grade = compute_grade(overall_score)

    # ---- Build findings ----
    findings = _build_findings(fmt_result, tables)

    # ---- Persist ValidationRun ----
    run = ValidationRun(
        document_id=doc_id,
        overall_score=overall_score,
        chapter_score=round(chapter_score, 2),
        subchapter_score=round(subchapter_score, 2),
        traffic_score=round(traffic_score, 2),
        engineering_score=round(engineering_score, 2),
        risk_score=round(risk_score, 2),
        cost_score=round(cost_score, 2),
        table_score=round(table_score, 2),
        grade=grade,
        chapters_found=fmt_result.chapters_found,
        chapters_total=fmt_result.chapters_total,
        tables_found=len(tables),
    )
    db.add(run)
    await db.flush()  # get run.id

    # ---- Persist Findings ----
    for f in findings:
        finding = Finding(
            run_id=run.id,
            category=f["category"],
            severity=f["severity"],
            issue=f["issue"],
            detail=f.get("detail"),
            match_type=f.get("match_type"),
            confidence=f.get("confidence", 1.0),
            page=f.get("page"),
            snippet=f.get("snippet"),
        )
        db.add(finding)

    await db.flush()

    # Update document state to VALIDATED
    from models.db_models import DocumentState
    doc.state = DocumentState.VALIDATED
    await db.flush()

    logger.info(
        f"Validation complete for doc {doc_id}: "
        f"Score={overall_score} Grade={grade} "
        f"Chapters={fmt_result.chapters_found}/{fmt_result.chapters_total}"
    )

    return run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chapter_found(fmt_result, canonical_title: str) -> bool:
    for r in fmt_result.chapter_results:
        if r.canonical_title == canonical_title:
            return r.found
    return False


def _component_score(chapter_present: bool, table_count: int, min_tables: int) -> float:
    """Compute a component score based on chapter presence and table count."""
    if not chapter_present:
        return 0.0
    if min_tables == 0:
        return 100.0
    table_ratio = min(1.0, table_count / min_tables)
    # 70% weight to chapter presence, 30% to tables
    return round(70 + (table_ratio * 30), 2)


def _build_findings(fmt_result, tables: list) -> list[dict]:
    """Generate the list of findings (issues) for the validation."""
    findings = []

    # Missing chapters
    for r in fmt_result.chapter_results:
        if not r.found:
            findings.append({
                "category": "chapter",
                "severity": FindingSeverity.CRITICAL if r.required else FindingSeverity.MAJOR,
                "issue": f"Missing chapter: '{r.canonical_title}'",
                "detail": f"Chapter {r.chapter_number} ('{r.canonical_title}') was not found in the document.",
                "match_type": MatchType.MISSING,
                "confidence": 1.0,
                "page": None,
                "snippet": None,
            })
        elif r.match_type in ("alias", "fuzzy"):
            findings.append({
                "category": "chapter",
                "severity": FindingSeverity.INFO,
                "issue": f"Chapter matched via {r.match_type}: '{r.canonical_title}' → '{r.matched_title}'",
                "detail": f"Expected '{r.canonical_title}', found '{r.matched_title}' (confidence: {r.confidence:.0%}).",
                "match_type": r.match_type,
                "confidence": r.confidence,
                "page": r.page,
                "snippet": r.matched_title,
            })

    # Missing key tables
    table_cats = {t.category for t in tables}
    required_table_cats = [
        (TableCategory.TRAFFIC, "Traffic/capacity table"),
        (TableCategory.COST,    "Cost estimate table"),
        (TableCategory.FIRR,    "FIRR calculation table"),
        (TableCategory.EIRR,    "EIRR calculation table"),
    ]
    for cat, label in required_table_cats:
        if cat not in table_cats:
            findings.append({
                "category": "table",
                "severity": FindingSeverity.MAJOR,
                "issue": f"Missing table: {label}",
                "detail": f"No {label} was detected in the document.",
                "match_type": MatchType.MISSING,
                "confidence": 0.85,
                "page": None,
                "snippet": None,
            })

    return findings
