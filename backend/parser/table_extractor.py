"""
Table extractor using pdfplumber (primary) with category classification.
Camelot can be enabled via TABLE_EXTRACTOR=camelot in .env when ghostscript is installed.
"""
from __future__ import annotations
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TABLE_EXTRACTOR = os.getenv("TABLE_EXTRACTOR", "pdfplumber")  # "pdfplumber" | "camelot"

# Category keywords — order matters (more specific first)
CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("FIRR",    ["firr", "financial internal rate", "financial irr", "financial rate of return"]),
    ("EIRR",    ["eirr", "economic internal rate", "economic irr", "economic rate of return"]),
    ("BOQ",     ["bill of quantity", "boq", "bill of quantities", "abstract of cost"]),
    ("COST",    ["cost estimate", "estimated cost", "total cost", "cost summary", "cash flow"]),
    ("TRAFFIC", ["traffic", "line capacity", "charted capacity", "utilisation", "freight", "earning"]),
    ("BRIDGE",  ["bridge", "major bridge", "minor bridge", "ROB", "RUB", "viaduct"]),
    ("LAND",    ["land acquisition", "land requirement", "area of land", "land details"]),
    ("RISK",    ["risk", "risk register", "mitigation"]),
    ("EARNINGS",["earning", "gross earning", "net earning", "revenue"]),
]


@dataclass
class TableData:
    page_number: int
    table_index: int
    rows: int
    cols: int
    category: str
    title: Optional[str]
    content_json: str   # JSON string of list[list[str]]
    extractor: str


def classify_table(title: Optional[str], content_sample: str) -> str:
    """Classify a table based on its title and content keywords."""
    text = ((title or "") + " " + content_sample).lower()
    for category, keywords in CATEGORY_PATTERNS:
        if any(kw in text for kw in keywords):
            return category
    return "GENERAL"


def extract_tables_from_pdf(pdf_path: str | Path) -> list[TableData]:
    """
    Extract all tables from a PDF using pdfplumber (or Camelot if configured).
    Returns list of TableData.
    """
    pdf_path = Path(pdf_path)
    tables: list[TableData] = []

    if TABLE_EXTRACTOR == "camelot":
        tables = _extract_with_camelot(pdf_path)
        if not tables:
            logger.warning("Camelot returned no tables, falling back to pdfplumber.")
            tables = _extract_with_pdfplumber(pdf_path)
    else:
        tables = _extract_with_pdfplumber(pdf_path)

    logger.info(f"Extracted {len(tables)} tables from {pdf_path.name}")
    return tables


def _extract_with_pdfplumber(pdf_path: Path) -> list[TableData]:
    """Use pdfplumber to extract tables."""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not installed.")
        return []

    tables: list[TableData] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                page_tables = page.extract_tables()
                if not page_tables:
                    continue

                # Get page text context for title detection
                page_text = page.extract_text() or ""

                for tbl_idx, raw_table in enumerate(page_tables):
                    if not raw_table or len(raw_table) < 2:
                        continue

                    # Clean cells
                    cleaned = [
                        [str(cell).strip() if cell is not None else "" for cell in row]
                        for row in raw_table
                    ]

                    rows = len(cleaned)
                    cols = max(len(r) for r in cleaned) if cleaned else 0

                    # Use first row as potential title / header
                    header_text = " ".join(cleaned[0]) if cleaned else ""
                    content_sample = " ".join(
                        " ".join(r) for r in cleaned[:5]
                    )

                    # Try to find title from page text above table
                    title = _extract_table_title(page_text, header_text)
                    category = classify_table(title, content_sample)

                    tables.append(TableData(
                        page_number=page_idx + 1,
                        table_index=tbl_idx,
                        rows=rows,
                        cols=cols,
                        category=category,
                        title=title,
                        content_json=json.dumps(cleaned),
                        extractor="pdfplumber",
                    ))

    except Exception as e:
        logger.error(f"pdfplumber extraction failed: {e}")

    return tables


def _extract_with_camelot(pdf_path: Path) -> list[TableData]:
    """Use Camelot (lattice + stream) to extract tables."""
    try:
        import camelot
    except ImportError:
        logger.error("Camelot not installed.")
        return []

    tables: list[TableData] = []
    try:
        for flavor in ["lattice", "stream"]:
            try:
                result = camelot.read_pdf(str(pdf_path), pages="all", flavor=flavor)
                for tbl in result:
                    df = tbl.df
                    if df.empty or len(df) < 2:
                        continue
                    rows, cols = df.shape
                    content_json = json.dumps(df.values.tolist())
                    header_text = " ".join(str(c) for c in df.iloc[0])
                    category = classify_table(None, header_text)
                    tables.append(TableData(
                        page_number=tbl.page,
                        table_index=0,
                        rows=rows,
                        cols=cols,
                        category=category,
                        title=None,
                        content_json=content_json,
                        extractor=f"camelot-{flavor}",
                    ))
            except Exception as e:
                logger.warning(f"Camelot {flavor} failed: {e}")

    except Exception as e:
        logger.error(f"Camelot extraction failed: {e}")

    return tables


def _extract_table_title(page_text: str, header_row: str) -> Optional[str]:
    """Try to extract a meaningful table title from surrounding text."""
    # Look for patterns like "Table X.Y:" or "TABLE X" before the header
    patterns = [
        re.compile(r'TABLE[\s\-]+\d+[\.\d]*[:\s]+([^\n]{5,80})', re.IGNORECASE),
        re.compile(r'Table[\s\-]+\d+[\.\d]*[:\s]+([^\n]{5,80})', re.IGNORECASE),
    ]
    for pat in patterns:
        m = pat.search(page_text)
        if m:
            return m.group(1).strip()

    # Fall back to header row if it looks like a title (not all numbers)
    if header_row and not re.match(r'^[\d\s\.\,]+$', header_row):
        return header_row[:120].strip()

    return None
