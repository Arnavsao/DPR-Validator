"""
Metadata extractor — pulls project-level info from the cover pages
of a DPR PDF: project name, route, division, length, date.
"""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DPRMetadata:
    project_name: Optional[str] = None
    project_route: Optional[str] = None
    division: Optional[str] = None
    length_km: Optional[float] = None
    report_date: Optional[str] = None
    volume: Optional[str] = None
    classification: Optional[str] = None   # "DOUBLING" | "NEW LINE" | "4TH LINE" etc.


def extract_metadata(pages: list[dict], max_cover_pages: int = 5) -> DPRMetadata:
    """
    Extract project metadata from the first few pages of the DPR.

    Args:
        pages: List of {page_number, text} dicts.
        max_cover_pages: How many pages to scan for metadata.
    Returns:
        DPRMetadata instance.
    """
    meta = DPRMetadata()

    # Combine text from first N pages
    cover_text = ""
    for page in pages[:max_cover_pages]:
        cover_text += "\n" + (page.get("text") or "")

    if not cover_text.strip():
        logger.warning("No text found in cover pages, metadata extraction skipped.")
        return meta

    # --- Project name / route ---
    # Patterns like: "FINAL LOCATION SURVEY FOR DOUBLING BETWEEN ADIPUR – NEW BHUJ SECTION (48.94 KM)"
    route_patterns = [
        re.compile(
            r'(?:SURVEY|LINE|PROJECT)\s+(?:FOR|BETWEEN|FROM)?\s*([A-Z][A-Z\s\-–&]+?)\s+'
            r'(?:SECTION|TO|–|-|AND)\s*([A-Z][A-Z\s\-–]+?)(?:\s+SECTION|\s+\(|\s*$)',
            re.IGNORECASE
        ),
        re.compile(
            r'BETWEEN\s+([A-Z][A-Z\s\-–]+?)\s+(?:TO|–|-|AND)\s+([A-Z][A-Z\s\-–]+?)\s',
            re.IGNORECASE
        ),
    ]
    for pat in route_patterns:
        m = pat.search(cover_text)
        if m:
            from_loc = m.group(1).strip()
            to_loc = m.group(2).strip()
            meta.project_route = f"{from_loc} – {to_loc}"
            break

    # --- Length in KM ---
    km_patterns = [
        re.compile(r'\((\d+[\.,]\d+)\s*KM\)', re.IGNORECASE),
        re.compile(r'(\d+[\.,]\d+)\s*KM\b', re.IGNORECASE),
        re.compile(r'length.*?(\d+[\.,]\d+)\s*km', re.IGNORECASE),
    ]
    for pat in km_patterns:
        m = pat.search(cover_text)
        if m:
            try:
                meta.length_km = float(m.group(1).replace(',', '.'))
                break
            except ValueError:
                pass

    # --- Division / Railway ---
    div_patterns = [
        re.compile(r'(\w+\s+DIVISION\s+\w+\s+RAILWAY)', re.IGNORECASE),
        re.compile(r'(\w+\s+RAILWAY)', re.IGNORECASE),
        re.compile(r'(SOUTH\s+(?:CENTRAL|EASTERN|WESTERN)\s+RAILWAY)', re.IGNORECASE),
        re.compile(r'(WESTERN\s+RAILWAY)', re.IGNORECASE),
        re.compile(r'(CENTRAL\s+RAILWAY)', re.IGNORECASE),
    ]
    for pat in div_patterns:
        m = pat.search(cover_text)
        if m:
            meta.division = m.group(1).strip()
            break

    # --- Date ---
    date_patterns = [
        re.compile(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s*[-,]?\s*(20\d{2})', re.IGNORECASE),
        re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\s\-,]+?(20\d{2})', re.IGNORECASE),
        re.compile(r'(20\d{2})'),
    ]
    for pat in date_patterns:
        m = pat.search(cover_text)
        if m:
            meta.report_date = " ".join(m.groups()).strip()
            break

    # --- Volume ---
    vol_m = re.search(r'VOLUME[\s\-]*([I|V|X|\d]+)', cover_text, re.IGNORECASE)
    if vol_m:
        meta.volume = vol_m.group(1).strip()

    # --- Classification ---
    class_map = {
        "DOUBLING": ["doubling", "double line"],
        "4TH LINE": ["4th line", "fourth line"],
        "3RD LINE": ["3rd line", "third line"],
        "NEW LINE": ["new line", "greenfield"],
        "GAUGE CONVERSION": ["gauge conversion", "BG conversion"],
        "ELECTRIFICATION": ["electrification"],
    }
    lower_text = cover_text.lower()
    for cls_name, keywords in class_map.items():
        if any(kw in lower_text for kw in keywords):
            meta.classification = cls_name
            break

    # --- Project name (best effort) ---
    if meta.project_route:
        parts = [meta.project_route]
        if meta.classification:
            parts.append(meta.classification)
        meta.project_name = " ".join(parts)
    else:
        # Take first non-empty substantive line from cover
        for line in cover_text.split("\n"):
            line = line.strip()
            if len(line) > 20 and not line.startswith("VOLUME") and not line[0].isdigit():
                meta.project_name = line[:200]
                break

    logger.info(f"Extracted metadata: {meta}")
    return meta
