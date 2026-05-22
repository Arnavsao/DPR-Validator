"""
Retriever — hierarchical spec retrieval from ChromaDB.

Retrieves relevant DPR format Vol-I spec chunks at each hierarchy level:
  - retrieve_mandatory_structure()    → all chapter specs (for structure check)
  - retrieve_for_chapter(...)         → spec chunks for a specific chapter
  - retrieve_for_section(...)         → spec chunks for a section within a chapter
  - retrieve_for_table(...)           → spec table requirement chunks
  - retrieve_for_query(...)           → generic semantic query

All functions return list[SpecChunk] — ranked by cosine similarity.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

from rag.chroma_store import (
    chroma_store,
    COLLECTION_VOLUME,
    COLLECTION_CHAPTER,
    COLLECTION_SECTION,
    COLLECTION_TABLE,
)
from rag.embedder import embed
from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SpecChunk:
    """A retrieved chunk from the DPR format spec corpus."""
    chunk_id: str
    text: str
    score: float              # cosine similarity (0-1, higher = more relevant)
    volume: str
    chapter_number: Optional[int]
    chapter_title: Optional[str]
    section_number: Optional[str]
    section_title: Optional[str]
    is_table: bool
    page: Optional[int]
    collection: str           # which collection this came from


def _parse_results(raw: dict, collection: str) -> list[SpecChunk]:
    """Convert ChromaDB query result dict into list of SpecChunk."""
    chunks: list[SpecChunk] = []

    ids_list = raw.get("ids", [[]])[0]
    docs_list = raw.get("documents", [[]])[0]
    metas_list = raw.get("metadatas", [[]])[0]
    dists_list = raw.get("distances", [[]])[0]

    for chunk_id, doc, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
        # ChromaDB cosine distance: 0=identical, 2=opposite.
        # Convert to similarity score 0–1
        similarity = max(0.0, 1.0 - (dist / 2.0))
        chunks.append(SpecChunk(
            chunk_id=chunk_id,
            text=doc or "",
            score=round(similarity, 4),
            volume=meta.get("volume", "I"),
            chapter_number=meta.get("chapter_number"),
            chapter_title=meta.get("chapter_title"),
            section_number=meta.get("section_number"),
            section_title=meta.get("section_title"),
            is_table=bool(meta.get("is_table", False)),
            page=meta.get("page"),
            collection=collection,
        ))

    return sorted(chunks, key=lambda c: c.score, reverse=True)


def retrieve_mandatory_structure(top_k: Optional[int] = None) -> list[SpecChunk]:
    """
    Retrieve all chapter-level spec chunks.
    Used for the full structural validation (chapter order + presence check).

    Returns chunks sorted by chapter_number.
    """
    k = top_k or 30  # get all chapters (18 mandatory + some optional)
    col = chroma_store.get_collection(COLLECTION_CHAPTER)
    if col is None or col.count() == 0:
        logger.warning("Chapter collection empty — run ingest_knowledge_base.py first.")
        return []

    # Use a neutral query to get a broad retrieval of chapter specs
    query_text = "mandatory chapter requirements structure DPR format specification"
    try:
        query_vec = embed(query_text)
        raw = chroma_store.query_collection(
            COLLECTION_CHAPTER,
            query_embeddings=[query_vec],
            n_results=k,
        )
        chunks = _parse_results(raw, COLLECTION_CHAPTER)
        # Sort by chapter number for ordered structure check
        chunks.sort(key=lambda c: (c.chapter_number or 99))
        return chunks
    except Exception as e:
        logger.error(f"retrieve_mandatory_structure failed: {e}")
        return []


def retrieve_for_chapter(
    chapter_title: str,
    chapter_text: str = "",
    top_k: Optional[int] = None,
) -> list[SpecChunk]:
    """
    Retrieve spec chunks relevant to a specific chapter.

    Args:
        chapter_title: Title of the chapter from the user DPR.
        chapter_text: First ~500 chars of the chapter body (for richer query).
        top_k: Number of chunks to return.

    Returns:
        Ranked SpecChunks from the chapter-level collection.
    """
    k = top_k or settings.RAG_TOP_K
    query_text = f"{chapter_title}. {chapter_text[:400]}".strip()

    try:
        query_vec = embed(query_text)
        raw = chroma_store.query_collection(
            COLLECTION_CHAPTER,
            query_embeddings=[query_vec],
            n_results=k,
        )
        return _parse_results(raw, COLLECTION_CHAPTER)
    except Exception as e:
        logger.error(f"retrieve_for_chapter('{chapter_title}') failed: {e}")
        return []


def retrieve_for_section(
    section_title: str,
    section_text: str = "",
    chapter_number: Optional[int] = None,
    top_k: Optional[int] = None,
) -> list[SpecChunk]:
    """
    Retrieve spec chunks for a section, optionally filtered by chapter.

    Args:
        section_title: Title of the section.
        section_text: Section body text snippet.
        chapter_number: Filter to chunks within this chapter number.
        top_k: Number of results.
    """
    k = top_k or settings.RAG_TOP_K
    query_text = f"{section_title}. {section_text[:400]}".strip()

    where_filter = None
    if chapter_number is not None:
        where_filter = {"chapter_number": {"$eq": chapter_number}}

    try:
        query_vec = embed(query_text)
        raw = chroma_store.query_collection(
            COLLECTION_SECTION,
            query_embeddings=[query_vec],
            n_results=k,
            where=where_filter,
        )
        chunks = _parse_results(raw, COLLECTION_SECTION)
        # Fallback: if chapter filter returns nothing, try without filter
        if not chunks and where_filter:
            raw = chroma_store.query_collection(
                COLLECTION_SECTION,
                query_embeddings=[query_vec],
                n_results=k,
            )
            chunks = _parse_results(raw, COLLECTION_SECTION)
        return chunks
    except Exception as e:
        logger.error(f"retrieve_for_section('{section_title}') failed: {e}")
        return []


def retrieve_for_table(
    table_title: str,
    top_k: Optional[int] = None,
) -> list[SpecChunk]:
    """
    Retrieve spec chunks describing table requirements.

    Args:
        table_title: Title of the table from the user DPR.
        top_k: Number of results.
    """
    k = top_k or settings.RAG_TOP_K
    query_text = f"table requirement: {table_title}"

    try:
        query_vec = embed(query_text)
        raw = chroma_store.query_collection(
            COLLECTION_TABLE,
            query_embeddings=[query_vec],
            n_results=k,
        )
        return _parse_results(raw, COLLECTION_TABLE)
    except Exception as e:
        logger.error(f"retrieve_for_table('{table_title}') failed: {e}")
        return []


def retrieve_for_query(
    query: str,
    collection: str = COLLECTION_CHAPTER,
    top_k: Optional[int] = None,
    where: Optional[dict] = None,
) -> list[SpecChunk]:
    """
    Generic semantic retrieval for any query against any collection.

    Args:
        query: Free-text query.
        collection: Target collection name.
        top_k: Number of results.
        where: Optional ChromaDB metadata filter.
    """
    k = top_k or settings.RAG_TOP_K
    try:
        query_vec = embed(query)
        raw = chroma_store.query_collection(
            collection,
            query_embeddings=[query_vec],
            n_results=k,
            where=where,
        )
        return _parse_results(raw, collection)
    except Exception as e:
        logger.error(f"retrieve_for_query failed: {e}")
        return []


def format_chunks_as_context(chunks: list[SpecChunk], max_chars: int = 3000) -> str:
    """
    Format retrieved spec chunks into a context string for LLM prompts.

    Truncates to max_chars to stay within LLM context limits.
    """
    if not chunks:
        return "[No relevant spec sections retrieved]"

    parts: list[str] = []
    total = 0

    for chunk in chunks:
        ref = f"[Vol-I"
        if chunk.chapter_title:
            ref += f", Ch.{chunk.chapter_number}: {chunk.chapter_title}"
        if chunk.section_title:
            ref += f", §{chunk.section_number}: {chunk.section_title}"
        if chunk.page:
            ref += f", p.{chunk.page}"
        ref += "]"

        entry = f"{ref}\n{chunk.text}\n"
        if total + len(entry) > max_chars:
            # Add truncation note and stop
            parts.append("[...additional spec sections truncated for length...]")
            break
        parts.append(entry)
        total += len(entry)

    return "\n---\n".join(parts)
