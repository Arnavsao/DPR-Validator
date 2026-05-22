"""
Comparator — compares a DPR's chapter tree against reference DPRs
(Adipur, Akola, ADRA, ADTP) and produces a structural diff.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process, utils

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChapterDiff:
    canonical_title: str
    in_target: bool
    in_reference: bool
    target_page: Optional[int]
    reference_page: Optional[int]
    status: str   # "present_both" | "missing_in_target" | "extra_in_target"


@dataclass
class CompareResult:
    reference_name: str
    target_doc_name: str
    missing_in_target: list[str]     # chapters in ref but not in target
    extra_in_target: list[str]       # chapters in target but not in ref
    present_in_both: list[str]
    depth_diff: list[dict]           # [{chapter, ref_depth, target_depth}]
    chapter_diffs: list[ChapterDiff]
    match_score: float               # 0-100: structural similarity


# Reference ground truth paths
_GT_DIR = settings.GROUND_TRUTH_DIR
_REFERENCES = {
    "adipur": "adipur_truth.json",
    "akola":  "akola_truth.json",
    "adra":   "adra_truth.json",
    "adtp":   "adtp_truth.json",
}

_REFERENCE_CACHE: dict[str, dict] = {}


def _load_reference(name: str) -> Optional[dict]:
    """Load and cache a reference ground truth JSON."""
    if name in _REFERENCE_CACHE:
        return _REFERENCE_CACHE[name]

    fname = _REFERENCES.get(name)
    if not fname:
        logger.warning(f"Unknown reference: {name}")
        return None

    path = _GT_DIR / fname
    if not path.exists():
        logger.warning(f"Reference file not found: {path}")
        return None

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    _REFERENCE_CACHE[name] = data
    return data


def compare_with_reference(
    target_chapters: list[dict],    # [{title, number, page}]
    reference_name: str,            # "adipur" | "akola" | "adra" | "adtp"
    target_doc_name: str = "Uploaded DPR",
    fuzzy_threshold: int = 80,
) -> Optional[CompareResult]:
    """
    Compare target DPR chapters against a reference DPR.

    Returns CompareResult or None if reference not found.
    """
    ref_data = _load_reference(reference_name)
    if not ref_data:
        return None

    ref_chapters = ref_data.get("chapters_present", [])
    ref_titles = [c["title"] for c in ref_chapters]
    target_titles = [c.get("title", "") for c in target_chapters]

    diffs: list[ChapterDiff] = []
    missing_in_target: list[str] = []
    extra_in_target: list[str] = []
    present_in_both: list[str] = []

    # For each reference chapter, check if it exists in target
    matched_target_indices: set[int] = set()

    for ref_ch in ref_chapters:
        ref_title = ref_ch["title"]
        ref_page = ref_ch.get("page")

        # Fuzzy match against target
        best = process.extractOne(
            ref_title, target_titles,
            scorer=fuzz.token_set_ratio,
            processor=utils.default_process,
            score_cutoff=fuzzy_threshold,
        )

        if best:
            matched_title, score, idx = best
            matched_target_indices.add(idx)
            target_page = target_chapters[idx].get("page")
            present_in_both.append(ref_title)
            diffs.append(ChapterDiff(
                canonical_title=ref_title,
                in_target=True,
                in_reference=True,
                target_page=target_page,
                reference_page=ref_page,
                status="present_both",
            ))
        else:
            missing_in_target.append(ref_title)
            diffs.append(ChapterDiff(
                canonical_title=ref_title,
                in_target=False,
                in_reference=True,
                target_page=None,
                reference_page=ref_page,
                status="missing_in_target",
            ))

    # Extra chapters in target not in reference
    for idx, tgt_ch in enumerate(target_chapters):
        if idx not in matched_target_indices:
            extra_title = tgt_ch.get("title", "")
            extra_in_target.append(extra_title)
            diffs.append(ChapterDiff(
                canonical_title=extra_title,
                in_target=True,
                in_reference=False,
                target_page=tgt_ch.get("page"),
                reference_page=None,
                status="extra_in_target",
            ))

    # Match score: fraction of reference chapters found in target
    total_ref = len(ref_chapters)
    match_score = (len(present_in_both) / total_ref * 100) if total_ref > 0 else 0

    logger.info(
        f"Compare {target_doc_name} vs {reference_name}: "
        f"{len(present_in_both)}/{total_ref} chapters matched. Score={match_score:.1f}"
    )

    return CompareResult(
        reference_name=ref_data.get("name", reference_name),
        target_doc_name=target_doc_name,
        missing_in_target=missing_in_target,
        extra_in_target=extra_in_target,
        present_in_both=present_in_both,
        depth_diff=[],  # Phase 6 — structural depth comparison not in scope yet
        chapter_diffs=diffs,
        match_score=round(match_score, 2),
    )


def list_references() -> list[dict]:
    """Return metadata about available reference DPRs."""
    refs = []
    for key, fname in _REFERENCES.items():
        data = _load_reference(key)
        if data:
            refs.append({
                "key": key,
                "name": data.get("name"),
                "classification": data.get("classification"),
                "pages": data.get("pages"),
                "length_km": data.get("length_km"),
                "date": data.get("date"),
                "expected_grade": data.get("expected_grade"),
            })
    return refs
