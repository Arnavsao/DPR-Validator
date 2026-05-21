"""
Parsing pipeline — orchestrates all parsing steps for a DPR document.
Transitions the document through states: PARSING → OCR → TABLES → STRUCTURED.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from core.config import settings
from models.db_models import (
    Document, DocumentState, Page, DocumentNode, ExtractedTable,
    NodeType, TableCategory,
)
from parser.pdf_extractor import extract_pages, get_page_image, get_pdf_metadata
from parser.ocr_fallback import ocr_page_bytes, should_ocr
from parser.table_extractor import extract_tables_from_pdf
from parser.section_detector import detect_sections, DetectedNode
from parser.metadata_extractor import extract_metadata

logger = logging.getLogger(__name__)


async def run_pipeline(doc_id: int, db: AsyncSession) -> bool:
    """
    Full parsing pipeline for a document.
    Returns True on success, False on failure.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        logger.error(f"Document {doc_id} not found.")
        return False

    pdf_path = Path(doc.file_path)
    logger.info(f"Starting pipeline for doc {doc_id}: {doc.original_name}")

    try:
        # ---- STEP 1: PDF text extraction ----
        await _set_state(doc, DocumentState.PARSING, db)

        pages_raw = extract_pages(pdf_path, ocr_threshold=settings.OCR_TEXT_THRESHOLD)
        pdf_meta = get_pdf_metadata(pdf_path)

        # Update page count
        doc.page_count = len(pages_raw)
        await db.flush()

        # Save pages to DB
        page_dicts = []
        for pd in pages_raw:
            page_obj = Page(
                document_id=doc_id,
                page_number=pd.page_number,
                text=pd.text,
                word_count=pd.word_count,
                has_images=pd.has_images,
                is_ocr=False,
            )
            db.add(page_obj)
            page_dicts.append({
                "page_number": pd.page_number,
                "text": pd.text,
                "word_count": pd.word_count,
                "needs_ocr": pd.needs_ocr,
            })

        await db.flush()

        # ---- STEP 2: OCR fallback ----
        await _set_state(doc, DocumentState.OCR, db)

        ocr_pages = [p for p in pages_raw if p.needs_ocr]
        if ocr_pages:
            logger.info(f"Running OCR on {len(ocr_pages)} pages.")
            for pd in ocr_pages:
                try:
                    img_bytes = get_page_image(pdf_path, pd.page_number)
                    ocr_text = ocr_page_bytes(img_bytes)
                    if ocr_text.strip():
                        # Update the page dict and DB entry
                        page_dicts[pd.page_number - 1]["text"] = ocr_text
                        # Update DB row
                        stmt = (
                            update(Page)
                            .where(
                                Page.document_id == doc_id,
                                Page.page_number == pd.page_number,
                            )
                            .values(text=ocr_text, is_ocr=True, word_count=len(ocr_text.split()))
                        )
                        await db.execute(stmt)
                except Exception as e:
                    logger.warning(f"OCR failed for page {pd.page_number}: {e}")

            await db.flush()
        else:
            logger.info("No OCR needed.")

        # ---- STEP 3: Table extraction ----
        await _set_state(doc, DocumentState.TABLES, db)

        tables = extract_tables_from_pdf(pdf_path)
        for tbl in tables:
            tbl_obj = ExtractedTable(
                document_id=doc_id,
                page_number=tbl.page_number,
                table_index=tbl.table_index,
                category=TableCategory[tbl.category] if tbl.category in TableCategory.__members__ else TableCategory.UNKNOWN,
                title=tbl.title,
                rows=tbl.rows,
                cols=tbl.cols,
                content_json=tbl.content_json,
                extractor=tbl.extractor,
            )
            db.add(tbl_obj)

        await db.flush()
        logger.info(f"Saved {len(tables)} tables for doc {doc_id}.")

        # ---- STEP 4: Structure detection + hierarchy build ----
        await _set_state(doc, DocumentState.STRUCTURED, db)

        detected_nodes = detect_sections(page_dicts)
        await _build_hierarchy(doc_id, detected_nodes, db)

        # ---- STEP 5: Metadata extraction ----
        meta = extract_metadata(page_dicts)
        doc.project_name  = meta.project_name
        doc.project_route = meta.project_route
        doc.division      = meta.division
        doc.length_km     = meta.length_km
        doc.report_date   = meta.report_date
        doc.parsed_at     = datetime.now(timezone.utc)

        await db.flush()
        logger.info(f"Pipeline complete for doc {doc_id}: {meta.project_name}")
        return True

    except Exception as e:
        logger.exception(f"Pipeline failed for doc {doc_id}: {e}")
        await _set_state(doc, DocumentState.FAILED, db)
        doc.error_message = str(e)
        await db.flush()
        return False


async def _set_state(doc: Document, state: DocumentState, db: AsyncSession):
    doc.state = state
    await db.flush()
    logger.debug(f"Doc {doc.id} → {state}")


async def _build_hierarchy(doc_id: int, nodes: list[DetectedNode], db: AsyncSession):
    """
    Build the document_nodes hierarchy tree from detected sections.
    Creates a root DOCUMENT node, then assigns chapters as children,
    sections as chapter children, etc.
    """
    # Create root document node
    root = DocumentNode(
        document_id=doc_id,
        parent_id=None,
        node_type=NodeType.DOCUMENT,
        level=0,
        number=None,
        title="Document",
        page_start=1,
        sequence=0,
    )
    db.add(root)
    await db.flush()  # get root.id

    chapter_node: DocumentNode | None = None
    section_node: DocumentNode | None = None
    seq = 0

    for dn in nodes:
        seq += 1
        ntype_map = {
            "CHAPTER":    NodeType.CHAPTER,
            "SECTION":    NodeType.SECTION,
            "SUBSECTION": NodeType.SUBSECTION,
            "ANNEXURE":   NodeType.ANNEXURE,
            "TABLE":      NodeType.TABLE,
            "FIGURE":     NodeType.FIGURE,
        }
        node_type = ntype_map.get(dn.node_type, NodeType.SECTION)

        if dn.node_type == "CHAPTER":
            parent_id = root.id
            chapter_node = None
            section_node = None
        elif dn.node_type in ("SECTION",):
            parent_id = chapter_node.id if chapter_node else root.id
        elif dn.node_type == "SUBSECTION":
            parent_id = section_node.id if section_node else (chapter_node.id if chapter_node else root.id)
        elif dn.node_type == "ANNEXURE":
            parent_id = root.id
        else:
            parent_id = chapter_node.id if chapter_node else root.id

        new_node = DocumentNode(
            document_id=doc_id,
            parent_id=parent_id,
            node_type=node_type,
            level=dn.level,
            number=dn.number,
            title=dn.title,
            page_start=dn.page,
            sequence=seq,
        )
        db.add(new_node)
        await db.flush()  # get new_node.id

        if dn.node_type == "CHAPTER":
            chapter_node = new_node
        elif dn.node_type == "SECTION":
            section_node = new_node

    logger.info(f"Built hierarchy: {seq} nodes for doc {doc_id}.")
