"""
Embedder — wraps Ollama's embedding API using mxbai-embed-large.

All embedding calls are synchronous (Ollama's Python client is sync).
Includes retry logic and basic batching.
"""
from __future__ import annotations
import logging
import time
from typing import Optional

import ollama

from core.config import settings

logger = logging.getLogger(__name__)

# Maximum chars to embed at once (mxbai-embed-large has a 512 token context)
# ~4 chars per token → 512*4 = 2048 chars safe limit; we use 1800 to be safe
_MAX_EMBED_CHARS = 1800
_MAX_RETRIES = 3
_RETRY_DELAY_SECS = 2.0


def _truncate(text: str) -> str:
    """Truncate text to safe embedding length."""
    return text[:_MAX_EMBED_CHARS] if len(text) > _MAX_EMBED_CHARS else text


def embed(text: str, model: Optional[str] = None) -> list[float]:
    """
    Embed a single text string using mxbai-embed-large.

    Args:
        text: Input text to embed.
        model: Override model name (defaults to settings.EMBED_MODEL).

    Returns:
        Embedding vector as list[float].

    Raises:
        RuntimeError if embedding fails after all retries.
    """
    model = model or settings.EMBED_MODEL
    text = _truncate(text.strip())
    if not text:
        raise ValueError("Cannot embed empty text.")

    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            client = ollama.Client(host=settings.OLLAMA_BASE_URL)
            response = client.embeddings(model=model, prompt=text)
            embedding = response.get("embedding") or response.get("embeddings")
            if isinstance(embedding, list) and len(embedding) > 0:
                # Handle nested list (some versions return [[...]])
                if isinstance(embedding[0], list):
                    return embedding[0]
                return embedding
            raise ValueError(f"Unexpected embedding response format: {type(embedding)}")
        except Exception as e:
            last_exc = e
            logger.warning(
                f"Embedding attempt {attempt}/{_MAX_RETRIES} failed: {e}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECS * attempt)

    raise RuntimeError(
        f"Embedding failed after {_MAX_RETRIES} attempts. "
        f"Is Ollama running? Last error: {last_exc}"
    )


def embed_batch(texts: list[str], model: Optional[str] = None) -> list[list[float]]:
    """
    Embed a list of texts. Falls back to sequential single embeds.

    Args:
        texts: List of text strings to embed.
        model: Override model name.

    Returns:
        List of embedding vectors.
    """
    model = model or settings.EMBED_MODEL
    results: list[list[float]] = []

    for i, text in enumerate(texts):
        try:
            vec = embed(text, model=model)
            results.append(vec)
        except Exception as e:
            logger.error(f"Failed to embed text[{i}]: {e}")
            # Append zero vector of same dimension as previous (fallback)
            dim = len(results[0]) if results else 1024
            results.append([0.0] * dim)

    return results


def check_ollama_connection() -> tuple[bool, str]:
    """
    Test connectivity to Ollama and check embed model availability.

    Returns:
        (ok: bool, message: str)
    """
    try:
        client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        models_response = client.list()
        available = [m.get("name", m.get("model", "")) for m in models_response.get("models", [])]
        embed_model = settings.EMBED_MODEL

        if any(embed_model in m for m in available):
            return True, f"Ollama OK. Embed model '{embed_model}' found."
        else:
            return False, (
                f"Ollama reachable but '{embed_model}' not found. "
                f"Available: {available}. Run: ollama pull {embed_model}"
            )
    except Exception as e:
        return False, f"Cannot reach Ollama at {settings.OLLAMA_BASE_URL}: {e}"
