"""
PDF text extractor using PyMuPDF.
Per-page extraction with image detection and word-count for OCR trigger.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class PageData:
    page_number: int         # 1-indexed
    text: str
    word_count: int
    has_images: bool
    needs_ocr: bool          # True when word_count < threshold
    image_count: int = 0


def extract_pages(pdf_path: str | Path, ocr_threshold: int = 50) -> list[PageData]:
    """
    Extract text from every page of a PDF.
    Returns list of PageData objects.

    Args:
        pdf_path: Path to the PDF file.
        ocr_threshold: Pages with fewer words than this trigger OCR flag.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages: list[PageData] = []

    try:
        doc = fitz.open(str(pdf_path))
        logger.info(f"Opened PDF: {pdf_path.name} ({len(doc)} pages)")

        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text("text")
            images = page.get_images(full=False)

            word_count = len(text.split()) if text else 0
            has_images = len(images) > 0
            needs_ocr = word_count < ocr_threshold

            pages.append(PageData(
                page_number=i + 1,
                text=text.strip(),
                word_count=word_count,
                has_images=has_images,
                needs_ocr=needs_ocr,
                image_count=len(images),
            ))

        doc.close()
        scanned_count = sum(1 for p in pages if p.needs_ocr)
        logger.info(
            f"Extracted {len(pages)} pages. "
            f"{scanned_count} pages below OCR threshold ({ocr_threshold} words)."
        )

    except Exception as e:
        logger.error(f"Failed to extract PDF {pdf_path}: {e}")
        raise

    return pages


def get_page_image(pdf_path: str | Path, page_number: int, dpi: int = 150) -> bytes:
    """
    Render a PDF page as a PNG image (for OCR or display).

    Args:
        page_number: 1-indexed page number.
        dpi: Resolution for rendering.
    Returns:
        PNG bytes.
    """
    doc = fitz.open(str(pdf_path))
    page = doc[page_number - 1]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def get_pdf_metadata(pdf_path: str | Path) -> dict:
    """Return basic PDF metadata dict."""
    doc = fitz.open(str(pdf_path))
    meta = doc.metadata or {}
    page_count = len(doc)
    doc.close()
    return {
        "page_count": page_count,
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "subject": meta.get("subject", ""),
        "creator": meta.get("creator", ""),
        "producer": meta.get("producer", ""),
    }
