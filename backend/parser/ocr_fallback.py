"""
OCR fallback using available engines.
Primary: tries easyocr (lightweight, no C++ deps).
Falls back to basic PIL text extraction hint.

PaddleOCR can be enabled later by setting OCR_ENGINE=paddle in .env.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

OCR_ENGINE = os.getenv("OCR_ENGINE", "easyocr")  # "easyocr" | "paddle" | "none"

# Lazy-load OCR engine
_reader = None


def _get_reader():
    global _reader
    if _reader is not None:
        return _reader

    if OCR_ENGINE == "paddle":
        try:
            from paddleocr import PaddleOCR
            _reader = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            logger.info("PaddleOCR loaded.")
        except ImportError:
            logger.warning("PaddleOCR not installed. Falling back to easyocr.")
            OCR_ENGINE = "easyocr"  # type: ignore

    if OCR_ENGINE == "easyocr" and _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(["en"], verbose=False)
            logger.info("EasyOCR loaded.")
        except ImportError:
            logger.warning("EasyOCR not installed. OCR will be skipped.")
            _reader = "none"

    return _reader


def ocr_page_bytes(img_bytes: bytes) -> str:
    """
    Run OCR on PNG image bytes, return extracted text.
    Returns empty string if no OCR engine available.
    """
    reader = _get_reader()

    if reader is None or reader == "none":
        logger.debug("No OCR engine available, returning empty string.")
        return ""

    try:
        import numpy as np
        from PIL import Image
        import io

        # Convert bytes → numpy array
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_array = np.array(img)

        if OCR_ENGINE == "paddle" and hasattr(reader, "ocr"):
            result = reader.ocr(img_array, cls=True)
            lines = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text, conf = line[1]
                        if conf > 0.5:
                            lines.append(text)
            return "\n".join(lines)

        else:
            # EasyOCR
            result = reader.readtext(img_array, detail=1)
            lines = [text for (_, text, conf) in result if conf > 0.4]
            return "\n".join(lines)

    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return ""


def should_ocr(word_count: int, threshold: int = 50) -> bool:
    """Return True if word count is below threshold."""
    return word_count < threshold
