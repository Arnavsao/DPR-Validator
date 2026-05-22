"""
Application configuration using python-dotenv.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings:
    # App
    APP_NAME: str = "DPR Validator"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{BASE_DIR}/storage/dpr_validator.db"
    )
    
    # Storage
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
    
    # References
    REFERENCES_DIR: Path = BASE_DIR / "references"
    GROUND_TRUTH_DIR: Path = BASE_DIR / "ground_truth"
    
    # Reference DPR paths
    REFERENCE_DPRS_DIR: Path = BASE_DIR.parent / "DPRs"
    
    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "150"))
    MAX_UPLOAD_SIZE_BYTES: int = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    
    # Parsing
    OCR_TEXT_THRESHOLD: int = int(os.getenv("OCR_TEXT_THRESHOLD", "50"))  # words below this triggers OCR
    FUZZY_MATCH_THRESHOLD: int = 85  # RapidFuzz score threshold (kept for section_detector)
    
    # CORS
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ]

    # ── RAG / Ollama ─────────────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Embedding model — mxbai-embed-large via Ollama
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "mxbai-embed-large")

    # LLM validation models (primary + fallbacks)
    LLM_PRIMARY: str  = os.getenv("LLM_PRIMARY",    "qwen3:32b")
    LLM_FALLBACK_1: str = os.getenv("LLM_FALLBACK_1", "qwen2.5:32b")
    LLM_FALLBACK_2: str = os.getenv("LLM_FALLBACK_2", "gemma3:27b")

    # Gemini Fallback
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # ChromaDB persistence directory
    CHROMA_DIR: Path = BASE_DIR / "storage" / "chroma_db"

    # Source-of-truth PDF
    DPR_FORMAT_PDF: Path = BASE_DIR.parent / "DPR format Vol-I.pdf"

    # Retrieval
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))           # spec chunks per query
    LLM_TIMEOUT_SECS: int = int(os.getenv("LLM_TIMEOUT_SECS", "600"))  # 10 min

    # Chunk sizes for ingestion
    CHUNK_SIZE_CHARS: int = int(os.getenv("CHUNK_SIZE_CHARS", "1500"))
    CHUNK_OVERLAP_CHARS: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "200"))


settings = Settings()

# Ensure dirs exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
