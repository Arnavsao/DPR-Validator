"""
ChromaDB store — singleton client + collection management.

Collections (one per hierarchy level):
  dpr_spec_volume   — volume-level overview chunks
  dpr_spec_chapter  — chapter-level chunks (primary retrieval target)
  dpr_spec_section  — section/subsection-level chunks
  dpr_spec_table    — table requirement chunks

All collections use cosine distance with mxbai-embed-large embeddings.
"""
from __future__ import annotations
import logging
import threading
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from core.config import settings

logger = logging.getLogger(__name__)

# Collection name constants
COLLECTION_VOLUME  = "dpr_spec_volume"
COLLECTION_CHAPTER = "dpr_spec_chapter"
COLLECTION_SECTION = "dpr_spec_section"
COLLECTION_TABLE   = "dpr_spec_table"

ALL_COLLECTIONS = [
    COLLECTION_VOLUME,
    COLLECTION_CHAPTER,
    COLLECTION_SECTION,
    COLLECTION_TABLE,
]


class ChromaStore:
    """
    Thread-safe singleton wrapper around a persistent ChromaDB client.
    Uses cosine similarity (via chromadb's hnsw:space=cosine metadata).
    """

    _instance: Optional["ChromaStore"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ChromaStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def _init_client(self):
        if self._initialized:
            return
        chroma_path = str(settings.CHROMA_DIR)
        logger.info(f"Initializing ChromaDB at {chroma_path}")
        self._client = chromadb.PersistentClient(
            path=chroma_path,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )
        self._initialized = True
        logger.info("ChromaDB client initialized.")

    @property
    def client(self) -> chromadb.ClientAPI:
        self._init_client()
        return self._client

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        """Get or create a collection with cosine similarity metric."""
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def get_collection(self, name: str) -> Optional[chromadb.Collection]:
        """Get an existing collection; returns None if not found."""
        try:
            return self.client.get_collection(name=name)
        except Exception:
            return None

    def collection_exists_and_populated(self, name: str) -> bool:
        """Return True if the collection exists and has at least 1 document."""
        col = self.get_collection(name)
        if col is None:
            return False
        try:
            return col.count() > 0
        except Exception:
            return False

    def is_knowledge_base_ready(self) -> bool:
        """Check whether all required collections are populated."""
        return all(
            self.collection_exists_and_populated(c)
            for c in ALL_COLLECTIONS
        )

    def get_kb_status(self) -> dict:
        """Return detailed status of each collection."""
        status = {}
        for name in ALL_COLLECTIONS:
            col = self.get_collection(name)
            if col is None:
                status[name] = {"exists": False, "count": 0}
            else:
                try:
                    count = col.count()
                    status[name] = {"exists": True, "count": count}
                except Exception as e:
                    status[name] = {"exists": True, "count": -1, "error": str(e)}
        return status

    def query_collection(
        self,
        name: str,
        query_embeddings: list[list[float]],
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> dict:
        """
        Query a collection by embedding vectors.

        Returns chromadb query result dict with keys:
          ids, documents, metadatas, distances
        """
        col = self.get_collection(name)
        if col is None:
            logger.warning(f"Collection '{name}' not found. Is the KB ingested?")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        try:
            kwargs: dict = {
                "query_embeddings": query_embeddings,
                "n_results": min(n_results, col.count() or 1),
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                kwargs["where"] = where
            return col.query(**kwargs)
        except Exception as e:
            logger.error(f"ChromaDB query failed on '{name}': {e}")
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def upsert(
        self,
        name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        """Upsert documents into a collection."""
        col = self.get_or_create_collection(name)
        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.debug(f"Upserted {len(ids)} chunks into '{name}'.")

    def delete_collection(self, name: str) -> None:
        """Delete a collection (used for re-ingestion)."""
        try:
            self.client.delete_collection(name)
            logger.info(f"Deleted collection '{name}'.")
        except Exception as e:
            logger.warning(f"Could not delete '{name}': {e}")


# Module-level singleton
chroma_store = ChromaStore()
