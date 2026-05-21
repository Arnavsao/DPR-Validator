"""
Evidence engine — for each finding, locates the best matching page
and text snippet in the document. Zero hallucination: only cites
text that actually exists in the document.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


@dataclass
class Evidence:
    issue: str
    confidence: float
    page: Optional[int]
    snippet: Optional[str]
    context_window: Optional[str]    # Wider context around the snippet


def find_evidence_for_finding(
    issue: str,
    keywords: list[str],
    pages: list[dict],                # [{page_number, text}]
    context_chars: int = 300,
) -> Evidence:
    """
    Search all page texts for the best-matching evidence for a given issue.

    Args:
        issue: Human-readable issue description.
        keywords: List of keywords to search for.
        pages: All page texts from the document.
        context_chars: Characters of context to include around the match.

    Returns:
        Evidence with page, snippet, and confidence. Never hallucinated —
        only returns snippets from actual page text.
    """
    best_score = 0.0
    best_page = None
    best_snippet = None
    best_context = None

    for page_data in pages:
        text = page_data.get("text") or ""
        page_num = page_data.get("page_number", 1)

        if not text.strip():
            continue

        # Score this page against each keyword
        page_score = 0.0
        for kw in keywords:
            kw_lower = kw.lower()
            text_lower = text.lower()

            # Direct substring presence (high confidence)
            if kw_lower in text_lower:
                page_score = max(page_score, 0.95)
                idx = text_lower.find(kw_lower)
                snippet_start = max(0, idx - 50)
                snippet_end = min(len(text), idx + len(kw) + 100)
                candidate_snippet = text[snippet_start:snippet_end].strip()

                if page_score > best_score:
                    best_score = page_score
                    best_page = page_num
                    best_snippet = candidate_snippet
                    ctx_start = max(0, idx - context_chars // 2)
                    ctx_end = min(len(text), idx + context_chars // 2)
                    best_context = text[ctx_start:ctx_end].strip()
            else:
                # Fuzzy match (lower confidence)
                score = fuzz.partial_ratio(kw_lower, text_lower) / 100
                if score > page_score:
                    page_score = score
                    if score > best_score:
                        best_score = score
                        best_page = page_num
                        # Take first 200 chars of text as snippet
                        best_snippet = text[:200].strip()
                        best_context = text[:context_chars].strip()

    return Evidence(
        issue=issue,
        confidence=round(best_score, 3),
        page=best_page,
        snippet=best_snippet,
        context_window=best_context,
    )


def enrich_findings_with_evidence(
    findings: list[dict],
    pages: list[dict],
) -> list[dict]:
    """
    For each finding, find supporting evidence from the document pages.
    Mutates the finding dicts to add 'page' and 'snippet' if not already set.

    This is called ONLY on findings that lack page evidence (e.g. missing chapters
    can still have their keywords searched for partial evidence).
    """
    # Chapter → keywords mapping for evidence search
    chapter_keywords = {
        "Executive Summary":           ["executive summary", "salient features"],
        "Traffic Survey":              ["traffic survey", "line capacity", "charted capacity"],
        "Engineering Survey":          ["engineering survey", "DGPS", "alignment"],
        "Land Requirement":            ["land acquisition", "land requirement", "area of land"],
        "Permanent Way":               ["permanent way", "track structure", "sleeper", "ballast"],
        "Formation, Tunnels & Bridges":["bridge", "major bridge", "tunnel", "formation"],
        "Stations & Yards":            ["station", "yard", "platform"],
        "Service Buildings":           ["service building", "workshop", "office"],
        "Residential Buildings":       ["residential", "staff quarter", "running room"],
        "Shifting of Utilities":       ["shifting", "utility", "OHE", "relocation"],
        "Electrical Traction & General":["traction", "OHE", "25KV", "electrical"],
        "Signal & Telecommunication":  ["signal", "telecommunication", "interlocking", "MACLS"],
        "Environmental Assessment":    ["environmental", "EIA", "SIA", "ecological"],
        "Statutory Clearances":        ["statutory", "clearance", "forest clearance"],
        "Cost Estimates":              ["cost estimate", "abstract", "BoQ", "bill of quantities"],
        "Financial Analysis":          ["FIRR", "financial internal rate", "NPV"],
        "Economic Analysis":           ["EIRR", "economic internal rate", "BCR"],
        "Risk Analysis":               ["risk", "mitigation", "risk register"],
    }

    enriched = []
    for f in findings:
        if f.get("page") is not None:
            enriched.append(f)
            continue

        # Determine keywords from issue text
        issue = f.get("issue", "")
        kws = []
        for chapter_name, kw_list in chapter_keywords.items():
            if chapter_name.lower() in issue.lower():
                kws = kw_list
                break

        if not kws:
            # Extract words from issue as fallback keywords
            kws = [w for w in re.findall(r"[a-zA-Z]{4,}", issue) if len(w) > 4][:3]

        if kws and pages:
            ev = find_evidence_for_finding(issue, kws, pages)
            f_copy = dict(f)
            if ev.page:
                f_copy["page"] = ev.page
                f_copy["snippet"] = ev.snippet
                f_copy["confidence"] = ev.confidence
            enriched.append(f_copy)
        else:
            enriched.append(f)

    return enriched
