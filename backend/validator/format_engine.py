"""
Format Engine — validates a parsed DPR's chapter tree against the
Railway DPR format specification using exact → alias → fuzzy matching.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChapterMatchResult:
    canonical_title: str
    chapter_number: int
    required: bool
    found: bool
    matched_title: Optional[str]
    match_type: str          # "exact" | "alias" | "fuzzy" | "missing"
    confidence: float        # 0.0–1.0
    page: Optional[int]


@dataclass
class FormatCheckResult:
    chapter_results: list[ChapterMatchResult]
    chapters_found: int
    chapters_total: int
    chapter_score: float     # 0–100


class FormatEngine:
    """
    Loads format spec and alias map, then evaluates a document's chapter list.
    """

    def __init__(self):
        self._spec: dict = {}
        self._aliases: dict[str, list[str]] = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return

        spec_path = settings.REFERENCES_DIR / "dpr_format_v1.json"
        alias_path = settings.REFERENCES_DIR / "railway_aliases.json"

        with open(spec_path, encoding="utf-8") as f:
            self._spec = json.load(f)

        with open(alias_path, encoding="utf-8") as f:
            alias_data = json.load(f)
            self._aliases = alias_data.get("aliases", {})

        self._loaded = True
        logger.info(
            f"Loaded format spec ({len(self._spec['volumes']['I']['mandatory_chapters'])} "
            f"mandatory chapters) and {len(self._aliases)} alias groups."
        )

    def check_document(
        self,
        detected_chapters: list[dict],  # [{title, number, page}]
        volume: str = "I",
    ) -> FormatCheckResult:
        """
        Compare detected chapters against mandatory chapter list.

        Args:
            detected_chapters: List of dicts from section_detector output.
            volume: DPR volume to validate against (default "I").
        Returns:
            FormatCheckResult with per-chapter match details.
        """
        self._load()

        mandatory = self._spec["volumes"][volume]["mandatory_chapters"]
        threshold = settings.FUZZY_MATCH_THRESHOLD

        # Build a flat list of detected chapter titles for fuzzy search
        detected_titles = [c.get("title", "").strip() for c in detected_chapters]

        results: list[ChapterMatchResult] = []

        for spec_chapter in mandatory:
            canonical = spec_chapter["canonical_title"]
            ch_num = spec_chapter["number"]
            required = spec_chapter.get("required", True)

            match_result = self._match_chapter(
                canonical, detected_chapters, detected_titles, threshold
            )
            results.append(ChapterMatchResult(
                canonical_title=canonical,
                chapter_number=ch_num,
                required=required,
                found=match_result["found"],
                matched_title=match_result.get("matched_title"),
                match_type=match_result["match_type"],
                confidence=match_result["confidence"],
                page=match_result.get("page"),
            ))

        found_count = sum(1 for r in results if r.found)
        total = len(mandatory)
        chapter_score = (found_count / total * 100) if total > 0 else 0

        logger.info(
            f"Format check: {found_count}/{total} chapters found. "
            f"Score: {chapter_score:.1f}"
        )

        return FormatCheckResult(
            chapter_results=results,
            chapters_found=found_count,
            chapters_total=total,
            chapter_score=chapter_score,
        )

    def _match_chapter(
        self,
        canonical: str,
        detected_chapters: list[dict],
        detected_titles: list[str],
        threshold: int,
    ) -> dict:
        """Try exact → alias → fuzzy matching for a single canonical chapter."""

        # 1. Exact match (case-insensitive)
        for det in detected_chapters:
            if det["title"].strip().lower() == canonical.lower():
                return {
                    "found": True,
                    "matched_title": det["title"],
                    "match_type": "exact",
                    "confidence": 1.0,
                    "page": det.get("page"),
                }

        # 2. Alias match
        aliases = self._aliases.get(canonical, [])
        for alias in aliases:
            for det in detected_chapters:
                if det["title"].strip().lower() == alias.lower():
                    return {
                        "found": True,
                        "matched_title": det["title"],
                        "match_type": "alias",
                        "confidence": 0.95,
                        "page": det.get("page"),
                    }

        # 3. Fuzzy match using RapidFuzz
        if detected_titles:
            # Use token_set_ratio to handle word-order variations
            best = process.extractOne(
                canonical,
                detected_titles,
                scorer=fuzz.token_set_ratio,
                score_cutoff=threshold,
            )
            if best:
                matched_title, score, idx = best
                return {
                    "found": True,
                    "matched_title": matched_title,
                    "match_type": "fuzzy",
                    "confidence": score / 100,
                    "page": detected_chapters[idx].get("page"),
                }

            # Also try aliases through fuzzy
            for alias in aliases:
                alias_best = process.extractOne(
                    alias,
                    detected_titles,
                    scorer=fuzz.token_set_ratio,
                    score_cutoff=threshold,
                )
                if alias_best:
                    matched_title, score, idx = alias_best
                    return {
                        "found": True,
                        "matched_title": matched_title,
                        "match_type": "fuzzy",
                        "confidence": score / 100,
                        "page": detected_chapters[idx].get("page"),
                    }

        # Not found
        return {
            "found": False,
            "matched_title": None,
            "match_type": "missing",
            "confidence": 0.0,
            "page": None,
        }


# Module-level singleton
format_engine = FormatEngine()
