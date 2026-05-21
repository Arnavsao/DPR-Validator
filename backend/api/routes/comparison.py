"""
Comparison API — compare an uploaded DPR against reference DPRs.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db
from models.db_models import Document, DocumentNode, NodeType
from comparator.comparator import compare_with_reference, list_references

router = APIRouter(prefix="/api/compare", tags=["comparison"])


@router.get("/references")
async def get_references():
    """List available reference DPRs."""
    return list_references()


@router.post("")
async def compare_documents(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Compare a document's chapters against a reference DPR.
    Body: {"doc_id": int, "reference": "adipur"|"akola"|"adra"|"adtp"}
    """
    doc_id = body.get("doc_id")
    reference = body.get("reference", "adipur")

    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required.")

    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Fetch chapter nodes
    result = await db.execute(
        select(DocumentNode).where(
            DocumentNode.document_id == doc_id,
            DocumentNode.node_type == NodeType.CHAPTER,
        ).order_by(DocumentNode.sequence)
    )
    chapter_nodes = result.scalars().all()

    if not chapter_nodes:
        raise HTTPException(
            status_code=400,
            detail="No chapters found. Make sure the document has been parsed first."
        )

    detected_chapters = [
        {"title": n.title, "number": n.number, "page": n.page_start}
        for n in chapter_nodes
    ]

    compare_result = compare_with_reference(
        target_chapters=detected_chapters,
        reference_name=reference,
        target_doc_name=doc.original_name,
    )

    if not compare_result:
        raise HTTPException(status_code=404, detail=f"Reference '{reference}' not found.")

    return {
        "reference_name": compare_result.reference_name,
        "target_doc_name": compare_result.target_doc_name,
        "match_score": compare_result.match_score,
        "chapters_in_both": compare_result.present_in_both,
        "missing_in_target": compare_result.missing_in_target,
        "extra_in_target": compare_result.extra_in_target,
        "chapter_diffs": [
            {
                "title": d.canonical_title,
                "status": d.status,
                "target_page": d.target_page,
                "reference_page": d.reference_page,
            }
            for d in compare_result.chapter_diffs
        ],
    }
