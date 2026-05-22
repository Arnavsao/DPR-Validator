"""
Parsing pipeline — orchestrates all parsing steps for a DPR document.
Transitions the document through states: PARSING → OCR → TABLES → STRUCTURED.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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

# Dedicated thread pool for blocking parser/OCR work
# (keeps FastAPI's event loop free to serve other requests)
_PARSE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dpr-parse")


async def _in_thread(func, *args):
    """Run a synchronous, blocking function in the dedicated thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_PARSE_POOL, func, *args)


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
            logger.info(f"Document {doc_id} is PAUSED. Entering sleep loop...")
            prev_stage = current_stage if current_stage != "PAUSED — Click resume to continue..." else "Processing..."
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
    logger.info(f"Doc {doc_id} progress: {percent}% | {stage} | ~{remaining_secs}s remaining")


async def run_pipeline(doc_id: int, db: AsyncSession) -> bool:
    """
    Full parsing pipeline for a document.
    Returns True on success, False on failure.

    All CPU-bound / blocking I/O calls are offloaded to a thread pool via
    run_in_executor so they never block the async event loop.
    """
    doc = await db.get(Document, doc_id)
    if not doc:
        logger.error(f"Document {doc_id} not found.")
        return False

    pdf_path = Path(doc.file_path)
    logger.info(f"Starting pipeline for doc {doc_id}: {doc.original_name}")

    try:
        # Check pause state before starting
        await _wait_if_paused(doc_id, db)
        
        # ---- STEP 1: PDF text extraction (blocking — run in thread) ----
        await _update_progress(doc_id, db, 2, "Preparing document parser...", 45)
        await _set_state(doc, DocumentState.PARSING, db)
        await _update_progress(doc_id, db, 5, "Extracting text from PDF pages...", 40)

        pages_raw, pdf_meta = await asyncio.gather(
            _in_thread(extract_pages, pdf_path, settings.OCR_TEXT_THRESHOLD),
            _in_thread(get_pdf_metadata, pdf_path),
        )

        # Update page count
        page_count = len(pages_raw)
        doc.page_count = page_count
        await db.commit()

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

        await db.commit()

        # Check pause state before OCR
        await _wait_if_paused(doc_id, db)

        # ---- STEP 2: OCR fallback (blocking — run each page in thread) ----
        await _set_state(doc, DocumentState.OCR, db)

        ocr_pages = [p for p in pages_raw if p.needs_ocr]
        total_ocr_pages = len(ocr_pages)
        
        if ocr_pages:
            logger.info(f"Running OCR on {total_ocr_pages} pages (in thread pool).")
            # Calculate initial time estimate for OCR (approx ~3s per page)
            ocr_est_remaining = total_ocr_pages * 3
            await _update_progress(doc_id, db, 15, f"Running OCR on {total_ocr_pages} pages...", ocr_est_remaining + 20)
            
            for idx, pd in enumerate(ocr_pages):
                # Check pause state between pages for high responsiveness
                await _wait_if_paused(doc_id, db)
                
                try:
                    # Both get_page_image and ocr_page_bytes are synchronous —
                    # run them in the executor so the event loop stays free.
                    img_bytes = await _in_thread(get_page_image, pdf_path, pd.page_number)
                    ocr_text = await _in_thread(ocr_page_bytes, img_bytes)
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
                
                # Update progress per page
                ocr_percent = 15 + int(((idx + 1) / total_ocr_pages) * 45) # OCR is up to 60% of parsing
                ocr_est_remaining = max(1, (total_ocr_pages - (idx + 1)) * 3)
                await _update_progress(
                    doc_id, 
                    db, 
                    ocr_percent, 
                    f"OCR running on page {pd.page_number} ({idx + 1}/{total_ocr_pages})...", 
                    ocr_est_remaining + 15
                )

            await db.commit()
        else:
            logger.info("No OCR needed.")
            await _update_progress(doc_id, db, 60, "OCR skipped (selectable text detected)...", 15)

        # Check pause state before Tables
        await _wait_if_paused(doc_id, db)

        # ---- STEP 3: Table extraction (blocking — run in thread) ----
        tbl_est_remaining = int(page_count * 0.2) + 5
        await _update_progress(doc_id, db, 65, f"Extracting tables across {page_count} pages...", tbl_est_remaining + 5)
        await _set_state(doc, DocumentState.TABLES, db)

        tables = await _in_thread(extract_tables_from_pdf, pdf_path)
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

        await db.commit()
        logger.info(f"Saved {len(tables)} tables for doc {doc_id}.")

        # Check pause state before Structure
        await _wait_if_paused(doc_id, db)

        # ---- STEP 4: Structure detection + hierarchy build (blocking — run in thread) ----
        await _update_progress(doc_id, db, 85, "Reconstructing chapter and section structure...", 8)
        await _set_state(doc, DocumentState.STRUCTURED, db)

        detected_nodes = await _in_thread(detect_sections, page_dicts)
        await _build_hierarchy(doc_id, detected_nodes, db)

        # Check pause state before Metadata
        await _wait_if_paused(doc_id, db)

        # ---- STEP 5: Metadata extraction (blocking — run in thread) ----
        await _update_progress(doc_id, db, 95, "Extracting project metadata...", 3)
        meta = await _in_thread(extract_metadata, page_dicts)
        doc.project_name  = meta.project_name
        doc.project_route = meta.project_route
        doc.division      = meta.division
        doc.length_km     = meta.length_km
        doc.report_date   = meta.report_date
        doc.parsed_at     = datetime.now(timezone.utc)

        await db.commit()
        await _update_progress(doc_id, db, 100, "Parsing complete", 0)
        logger.info(f"Pipeline complete for doc {doc_id}: {meta.project_name}")
        return True

    except Exception as e:
        logger.exception(f"Pipeline failed for doc {doc_id}: {e}")
        await _set_state(doc, DocumentState.FAILED, db)
        doc.error_message = str(e)
        await db.commit()
        return False


async def _set_state(doc: Document, state: DocumentState, db: AsyncSession):
    doc.state = state
    await db.commit()
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
    await db.commit()  # get root.id

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
        await db.commit()  # get new_node.id

        if dn.node_type == "CHAPTER":
            chapter_node = new_node
        elif dn.node_type == "SECTION":
            section_node = new_node

    logger.info(f"Built hierarchy: {seq} nodes for doc {doc_id}.")
