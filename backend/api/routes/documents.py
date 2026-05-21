"""
Documents API — upload, list, retrieve, parse.
"""
import asyncio
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.deps import get_db
from core.config import settings
from models.db_models import Document, DocumentState, DocumentNode, ExtractedTable, NodeType
from parser.pipeline import run_pipeline

router = APIRouter(prefix="/api/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a DPR PDF and trigger parsing in background."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Check size
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE_MB}MB."
        )

    # Save to disk
    safe_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    dest_path = settings.UPLOAD_DIR / safe_name

    async with aiofiles.open(dest_path, "wb") as f_out:
        await f_out.write(content)

    # Create DB record
    doc = Document(
        filename=safe_name,
        original_name=file.filename,
        file_path=str(dest_path),
        file_size=len(content),
        state=DocumentState.UPLOADED,
    )
    db.add(doc)
    await db.flush()
    doc_id = doc.id

    # Queue background parse
    background_tasks.add_task(_parse_document_bg, doc_id)

    return {
        "id": doc_id,
        "filename": file.filename,
        "size_bytes": len(content),
        "state": DocumentState.UPLOADED,
        "message": "Upload successful. Parsing started in background.",
    }


async def _parse_document_bg(doc_id: int):
    """Background task: run the full parsing pipeline."""
    from core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            await run_pipeline(doc_id, db)
            await db.commit()
        except Exception as e:
            await db.rollback()
            import logging
            logging.getLogger(__name__).error(f"Background parse failed for doc {doc_id}: {e}")


# ---------------------------------------------------------------------------
# List documents
# ---------------------------------------------------------------------------

@router.get("")
async def list_documents(db: AsyncSession = Depends(get_db)):
    """Return all uploaded documents."""
    result = await db.execute(
        select(Document).order_by(desc(Document.uploaded_at))
    )
    docs = result.scalars().all()
    return [_doc_to_dict(d) for d in docs]


# ---------------------------------------------------------------------------
# Get single document
# ---------------------------------------------------------------------------

@router.get("/{doc_id}")
async def get_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Return document metadata + current parse state."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _doc_to_dict(doc)


# ---------------------------------------------------------------------------
# Manual parse trigger
# ---------------------------------------------------------------------------

@router.post("/{doc_id}/parse")
async def parse_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger re-parsing of a document."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    doc.state = DocumentState.UPLOADED
    doc.error_message = None
    await db.flush()

    background_tasks.add_task(_parse_document_bg, doc_id)
    return {"message": f"Re-parsing started for document {doc_id}."}


# ---------------------------------------------------------------------------
# Chapter tree
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/nodes")
async def get_document_nodes(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Return the chapter/section hierarchy tree for a document."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    result = await db.execute(
        select(DocumentNode)
        .where(DocumentNode.document_id == doc_id)
        .order_by(DocumentNode.sequence)
    )
    nodes = result.scalars().all()

    return [
        {
            "id": n.id,
            "parent_id": n.parent_id,
            "node_type": n.node_type,
            "level": n.level,
            "number": n.number,
            "title": n.title,
            "page_start": n.page_start,
            "page_end": n.page_end,
            "sequence": n.sequence,
        }
        for n in nodes
    ]


# ---------------------------------------------------------------------------
# Extracted tables
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/tables")
async def get_document_tables(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Return all extracted tables for a document."""
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    result = await db.execute(
        select(ExtractedTable)
        .where(ExtractedTable.document_id == doc_id)
        .order_by(ExtractedTable.page_number)
    )
    tables = result.scalars().all()

    return [
        {
            "id": t.id,
            "page_number": t.page_number,
            "table_index": t.table_index,
            "category": t.category,
            "title": t.title,
            "rows": t.rows,
            "cols": t.cols,
            "extractor": t.extractor,
        }
        for t in tables
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc_to_dict(doc: Document) -> dict:
    return {
        "id": doc.id,
        "filename": doc.original_name,
        "file_size": doc.file_size,
        "page_count": doc.page_count,
        "state": doc.state,
        "project_name": doc.project_name,
        "project_route": doc.project_route,
        "division": doc.division,
        "length_km": doc.length_km,
        "report_date": doc.report_date,
        "is_reference": doc.is_reference,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "parsed_at": doc.parsed_at.isoformat() if doc.parsed_at else None,
        "error_message": doc.error_message,
    }
