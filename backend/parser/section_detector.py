"""
Section detector — converts raw page text into a structured hierarchy of
chapters, sections, subsections, annexures, tables, and figures.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DetectedNode:
    node_type: str       # CHAPTER | SECTION | SUBSECTION | ANNEXURE | TABLE | FIGURE
    level: int           # 0=chapter, 1=section, 2=subsection
    number: Optional[str]  # "1", "1.1", "1.1.1", "A", etc.
    title: str
    page: int
    raw_match: str       # original matched string


# ---------------------------------------------------------------------------
# Compiled patterns — ordered from most-specific to least-specific
# ---------------------------------------------------------------------------
PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # CHAPTER headings: "CHAPTER 1", "CHAPTER-1", "CHAPTER – 1"
    ("CHAPTER", r"CHAPTER[\s\-–]+(\d{1,2})\s*[:\-–]?\s*(.{3,100})", re.IGNORECASE | re.MULTILINE),
    # Section: "1.1 Some Title" or "1.1. Title"
    ("SECTION", r"^(\d{1,2}\.\d{1,2})\.?\s+([A-Z][^\n]{5,100})", re.MULTILINE),
    # Subsection: "1.1.1 Title"
    ("SUBSECTION", r"^(\d{1,2}\.\d{1,2}\.\d{1,2})\.?\s+([A-Z][^\n]{3,100})", re.MULTILINE),
    # Annexure
    ("ANNEXURE", r"ANNEX(?:URE)?\s+([A-Z\d]{1,3})\s*[:\-–]?\s*(.{0,100})", re.IGNORECASE | re.MULTILINE),
    # Table reference (in-text)
    ("TABLE", r"TABLE\s+(\d+[\.\d]*)\s*[:\-–]?\s*(.{0,100})", re.IGNORECASE | re.MULTILINE),
    # Figure reference (in-text)
    ("FIGURE", r"FIG(?:URE|\.)\s+(\d+[\.\d]*)\s*[:\-–]?\s*(.{0,100})", re.IGNORECASE | re.MULTILINE),
]

_COMPILED = [
    (node_type, re.compile(pattern, flags))
    for node_type, pattern, flags in PATTERNS
]


def detect_sections(pages: list[dict]) -> list[DetectedNode]:
    """
    Scan all pages and detect structural elements.

    Args:
        pages: List of dicts with {page_number, text}
    Returns:
        Ordered list of DetectedNode (by page, then position in text).
    """
    all_nodes: list[DetectedNode] = []

    for page_data in pages:
        page_num = page_data.get("page_number", 1)
        text = page_data.get("text", "") or ""

        if not text.strip():
            continue

        page_nodes = _detect_in_text(text, page_num)
        all_nodes.extend(page_nodes)

    # Deduplicate — same title appearing on adjacent pages (e.g. from TOC + body)
    all_nodes = _deduplicate_nodes(all_nodes)

    # Compute levels
    for node in all_nodes:
        if node.node_type == "CHAPTER":
            node.level = 0
        elif node.node_type == "SECTION":
            node.level = 1
        elif node.node_type == "SUBSECTION":
            node.level = 2
        elif node.node_type == "ANNEXURE":
            node.level = 0
        else:
            node.level = 3

    logger.info(f"Detected {len(all_nodes)} structural nodes across {len(pages)} pages.")
    return all_nodes


def _detect_in_text(text: str, page_num: int) -> list[DetectedNode]:
    """Run all patterns on a single page's text."""
    nodes: list[DetectedNode] = []
    seen_spans: set[tuple[int, int]] = set()

    for node_type, pattern in _COMPILED:
        for m in pattern.finditer(text):
            # Skip if already matched by a more specific pattern
            span = (m.start(), m.end())
            if any(s[0] <= span[0] < s[1] for s in seen_spans):
                continue

            groups = m.groups()
            number = groups[0].strip() if groups else None
            title_raw = groups[1].strip() if len(groups) > 1 else (groups[0] if groups else "")

            # Clean title
            title = _clean_title(title_raw)
            if len(title) < 3:
                continue

            nodes.append(DetectedNode(
                node_type=node_type,
                level=0,
                number=number,
                title=title,
                page=page_num,
                raw_match=m.group(0)[:200],
            ))
            seen_spans.add(span)

    return nodes


def _clean_title(raw: str) -> str:
    """Normalize a detected title string."""
    # Remove common noise
    title = raw.strip()
    title = re.sub(r'\s+', ' ', title)
    title = re.sub(r'[:\-–]+$', '', title).strip()
    # Truncate if very long (likely a paragraph, not a heading)
    if len(title) > 120:
        title = title[:120].rsplit(' ', 1)[0] + "..."
    return title


def _deduplicate_nodes(nodes: list[DetectedNode]) -> list[DetectedNode]:
    """
    Remove duplicate nodes — same type + number appearing multiple times
    (e.g. from TOC and then actual chapter). Keep the LAST occurrence (body page).
    """
    seen: dict[str, DetectedNode] = {}
    for node in nodes:
        key = f"{node.node_type}_{node.number}"
        # Prefer later page (body page > TOC page)
        if key not in seen or node.page > seen[key].page:
            seen[key] = node

    # Return ordered by page
    return sorted(seen.values(), key=lambda n: (n.page, n.node_type))
