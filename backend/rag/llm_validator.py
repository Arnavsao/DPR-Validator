"""
LLM Validator — Ollama-based DPR validation using the RAG pipeline.

Validation tasks:
  1. validate_structure()        — chapter order + presence vs Vol-I spec
  2. validate_chapter()          — chapter completeness vs spec context
  3. validate_tables()           — required tables presence
  4. validate_section_deps()     — cross-chapter dependency checks (FIRR needs Traffic+Cost)
  5. validate_executive_summary() — executive summary completeness

All tasks produce ValidationResult objects with structured JSON output.
Do NOT hallucinate: if evidence is missing, status = UNKNOWN.

Primary model:  settings.LLM_PRIMARY  (qwen3:32b)
Fallback chain: settings.LLM_FALLBACK_1 → settings.LLM_FALLBACK_2
"""
from __future__ import annotations
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import ollama

from core.config import settings
from rag.retriever import SpecChunk, format_chunks_as_context

logger = logging.getLogger(__name__)

# ── Data Structures ────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Single chapter/section validation result — matches required output schema."""
    chapter: str
    status: str           # "PASS" | "FAIL" | "WARNING" | "UNKNOWN"
    missing_items: list[str] = field(default_factory=list)
    reference_section: str = ""
    reason: str = ""
    confidence: float = 0.0
    evidence: str = ""         # snippet from user DPR used as evidence
    suggested_correction: str = ""
    category: str = "chapter"  # "chapter" | "table" | "section" | "structure"


# ── LLM Client ────────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, system_prompt: str) -> str:
    """
    Call Gemini API as ultimate fallback using httpx.
    """
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")

    model = settings.GEMINI_MODEL or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "systemInstruction": {
            "parts": [
                {"text": system_prompt}
            ]
        },
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json"
        }
    }

    logger.info(f"Gemini API fallback call → model={model}")
    t0 = time.time()
    response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
    response.raise_for_status()

    res_data = response.json()
    elapsed = time.time() - t0

    try:
        text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
        logger.info(f"Gemini response in {elapsed:.1f}s ({len(text)} chars)")
        return text
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse Gemini response: {res_data}")
        raise RuntimeError(f"Invalid response structure from Gemini API: {e}")


def _call_llm(
    prompt: str,
    system_prompt: str,
    model: Optional[str] = None,
) -> str:
    """
    Call Ollama LLM with fallback chain, and Gemini API as ultimate fallback.
    Returns raw response text.
    """
    model_chain = [
        model or settings.LLM_PRIMARY,
        settings.LLM_FALLBACK_1,
        settings.LLM_FALLBACK_2,
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    models_to_try: list[str] = []
    for m in model_chain:
        if m and m not in seen:
            models_to_try.append(m)
            seen.add(m)

    last_exc: Optional[Exception] = None
    for attempt_model in models_to_try:
        try:
            logger.info(f"LLM call → model={attempt_model}")
            t0 = time.time()
            client = ollama.Client(
                host=settings.OLLAMA_BASE_URL,
            )
            response = client.chat(
                model=attempt_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                options={
                    "temperature": 0.0,    # deterministic — no creative answers
                    "num_predict": 2048,
                    "top_p": 1.0,
                },
                think=False,               # disable chain-of-thought for speed
            )
            elapsed = time.time() - t0
            text = response["message"]["content"].strip()
            logger.info(f"LLM response in {elapsed:.1f}s ({len(text)} chars)")
            return text
        except TypeError:
            # Older ollama SDK doesn't support think= param; retry without it
            try:
                client = ollama.Client(host=settings.OLLAMA_BASE_URL)
                response = client.chat(
                    model=attempt_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": prompt},
                    ],
                    options={"temperature": 0.0, "num_predict": 2048},
                )
                return response["message"]["content"].strip()
            except Exception as e:
                last_exc = e
                logger.warning(f"Model '{attempt_model}' failed: {e}")
        except Exception as e:
            last_exc = e
            logger.warning(f"Model '{attempt_model}' failed: {e}")

    # If all local Ollama models fail, try Gemini fallback
    if settings.GEMINI_API_KEY:
        try:
            return _call_gemini(prompt, system_prompt)
        except Exception as e:
            last_exc = e
            logger.error(f"Gemini fallback failed: {e}")

    raise RuntimeError(
        f"All LLM models and Gemini fallback failed. Last error: {last_exc}. "
        f"Check Ollama is running: {settings.OLLAMA_BASE_URL}"
    )


def _extract_json(text: str) -> dict:
    """
    Extract the first JSON object from LLM response text.

    Returns empty dict if no valid JSON found (triggers UNKNOWN fallback).
    """
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    patterns = [
        r"```json\s*([\s\S]+?)\s*```",
        r"```\s*([\s\S]+?)\s*```",
        r"\{[\s\S]+\}",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.DOTALL)
        if match:
            candidate = match.group(1) if "```" in pat else match.group(0)
            try:
                return json.loads(candidate.strip())
            except json.JSONDecodeError:
                continue

    logger.warning(f"Could not extract JSON from LLM response: {text[:200]}")
    return {}


def _safe_result(
    chapter: str,
    category: str,
    raw: dict,
    spec_chunks: list[SpecChunk],
    fallback_evidence: str = "",
) -> ValidationResult:
    """
    Build a ValidationResult from parsed LLM JSON.
    Returns UNKNOWN status if JSON is malformed or evidence is absent.
    """
    if not raw:
        return ValidationResult(
            chapter=chapter,
            category=category,
            status="UNKNOWN",
            reason="LLM did not return parseable JSON.",
            confidence=0.0,
            evidence=fallback_evidence,
        )

    status = raw.get("status", "UNKNOWN").upper()
    if status not in ("PASS", "FAIL", "WARNING", "UNKNOWN"):
        status = "UNKNOWN"

    # Build reference from retrieved chunks
    ref_section = raw.get("reference_section", "")
    if not ref_section and spec_chunks:
        best = spec_chunks[0]
        parts = [f"Vol-I"]
        if best.chapter_number:
            parts.append(f"Ch.{best.chapter_number}")
        if best.chapter_title:
            parts.append(best.chapter_title)
        if best.section_number:
            parts.append(f"§{best.section_number}")
        ref_section = ", ".join(parts)

    return ValidationResult(
        chapter=chapter,
        category=category,
        status=status,
        missing_items=raw.get("missing_items", []),
        reference_section=ref_section,
        reason=raw.get("reason", ""),
        confidence=float(raw.get("confidence", 0.5)),
        evidence=raw.get("evidence", fallback_evidence),
        suggested_correction=raw.get("suggested_correction", ""),
    )


# ── System Prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an expert Indian Railway DPR (Detailed Project Report) validator.
You validate user DPR documents against the official Railway DPR Format Volume-I specification.

CRITICAL RULES:
1. Base ALL judgments ONLY on the provided spec context and user DPR content given.
2. Do NOT hallucinate. If you cannot find clear evidence, respond with status "UNKNOWN".
3. Return ONLY valid JSON matching the exact schema requested. No prose before or after.
4. Be strict: missing mandatory content = FAIL. Partially present = WARNING.
5. Cite the exact spec section in reference_section (e.g., "Vol-I, Ch.2, §2.3").
6. confidence: 0.0-1.0. Use high confidence (>0.85) only when evidence is clear.
"""


# ── Validation Tasks ──────────────────────────────────────────────────────────

def validate_structure(
    detected_chapters: list[dict],
    spec_chunks: list[SpecChunk],
) -> list[ValidationResult]:
    """
    Task 1: Validate overall document structure.

    Checks:
      - All mandatory chapters present (Vol-I defines 18 mandatory chapters)
      - Chapters in correct order
      - No duplicate chapters

    Args:
        detected_chapters: [{title, number, page}] from user DPR
        spec_chunks: All chapter-level chunks from retrieve_mandatory_structure()

    Returns:
        One ValidationResult per mandatory chapter.
    """
    spec_context = format_chunks_as_context(spec_chunks, max_chars=4000)
    detected_list = "\n".join(
        f"  {i+1}. \"{c.get('title','?')}\" (detected number: {c.get('number','?')}, page: {c.get('page','?')})"
        for i, c in enumerate(detected_chapters)
    )

    prompt = f"""## DPR FORMAT SPECIFICATION (Vol-I mandatory chapters):
{spec_context}

## USER DPR — DETECTED CHAPTERS (in order found):
{detected_list if detected_list else "(No chapters detected)"}

## TASK:
Compare the user DPR's chapter list against the Vol-I mandatory chapter requirements.

For EACH mandatory chapter in the spec, determine:
- Is it present in the user DPR? (PASS / FAIL)
- Is it in the correct order? (if wrong order → WARNING)
- Is it missing entirely? (FAIL)

Return a JSON array. Each element follows this EXACT schema:
{{
  "chapter": "<canonical chapter title from spec>",
  "status": "PASS | FAIL | WARNING",
  "missing_items": [],
  "reference_section": "<Vol-I chapter reference>",
  "reason": "<one sentence explanation>",
  "confidence": <0.0-1.0>,
  "evidence": "<matching title found in user DPR, or empty string if not found>",
  "suggested_correction": "<what to add/fix, or empty string if PASS>"
}}

Return ONLY the JSON array. No other text."""

    try:
        raw_text = _call_llm(prompt, _SYSTEM_PROMPT)
        # Try to extract JSON array
        raw_text = raw_text.strip()
        # Handle both array and object responses
        if raw_text.startswith("{"):
            raw_text = f"[{raw_text}]"

        # Extract array from markdown if present
        arr_match = re.search(r"\[[\s\S]+\]", raw_text, re.DOTALL)
        if arr_match:
            parsed = json.loads(arr_match.group(0))
        else:
            parsed = json.loads(raw_text)

        if not isinstance(parsed, list):
            parsed = [parsed]

        results: list[ValidationResult] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            status = item.get("status", "UNKNOWN").upper()
            if status not in ("PASS", "FAIL", "WARNING", "UNKNOWN"):
                status = "UNKNOWN"
            results.append(ValidationResult(
                chapter=item.get("chapter", "Unknown"),
                category="structure",
                status=status,
                missing_items=item.get("missing_items", []),
                reference_section=item.get("reference_section", "Vol-I"),
                reason=item.get("reason", ""),
                confidence=float(item.get("confidence", 0.5)),
                evidence=item.get("evidence", ""),
                suggested_correction=item.get("suggested_correction", ""),
            ))
        return results

    except Exception as e:
        logger.error(f"validate_structure LLM call failed: {e}")
        # Return UNKNOWN for all mandatory chapters
        return [
            ValidationResult(
                chapter="Structure Validation",
                category="structure",
                status="UNKNOWN",
                reason=f"LLM validation failed: {e}",
                confidence=0.0,
            )
        ]


def validate_chapter(
    chapter_title: str,
    chapter_text: str,
    spec_chunks: list[SpecChunk],
    section_titles: Optional[list[str]] = None,
) -> ValidationResult:
    """
    Task 2: Validate a single chapter's completeness.

    Checks:
      - Required subsections present
      - Required fields/data present
      - Sufficient content depth

    Args:
        chapter_title: Title of the chapter from user DPR.
        chapter_text: Full text of the chapter (truncated to 2000 chars).
        spec_chunks: Retrieved spec chunks for this chapter.
        section_titles: List of detected section titles within this chapter.
    """
    spec_context = format_chunks_as_context(spec_chunks, max_chars=3000)
    text_snippet = chapter_text[:2000] if chapter_text else "(No text extracted)"
    sections_str = (
        "\n".join(f"  - {s}" for s in section_titles)
        if section_titles else "  (No subsections detected)"
    )

    prompt = f"""## DPR FORMAT SPEC — Requirement for chapter "{chapter_title}":
{spec_context}

## USER DPR — Chapter "{chapter_title}" content (first 2000 chars):
{text_snippet}

## USER DPR — Subsections detected within this chapter:
{sections_str}

## TASK:
Assess whether the user DPR's chapter "{chapter_title}" satisfies the Vol-I specification.

Check for:
1. All mandatory subsections required by the spec
2. Required data/figures/analysis mentioned in the spec
3. Sufficient content depth (not just headings without substance)

Return ONLY this JSON object:
{{
  "chapter": "{chapter_title}",
  "status": "PASS | FAIL | WARNING | UNKNOWN",
  "missing_items": ["<item1>", "<item2>"],
  "reference_section": "<exact Vol-I section reference>",
  "reason": "<concise explanation of PASS/FAIL/WARNING>",
  "confidence": <0.0-1.0>,
  "evidence": "<key phrase from user DPR showing what IS present>",
  "suggested_correction": "<specific additions required, or empty if PASS>"
}}"""

    try:
        raw_text = _call_llm(prompt, _SYSTEM_PROMPT)
        parsed = _extract_json(raw_text)
        return _safe_result(chapter_title, "chapter", parsed, spec_chunks, text_snippet[:200])
    except Exception as e:
        logger.error(f"validate_chapter('{chapter_title}') failed: {e}")
        return ValidationResult(
            chapter=chapter_title,
            category="chapter",
            status="UNKNOWN",
            reason=f"LLM call failed: {e}",
            confidence=0.0,
        )


def validate_tables(
    detected_tables: list[dict],
    spec_chunks: list[SpecChunk],
) -> list[ValidationResult]:
    """
    Task 3: Validate mandatory tables against spec requirements.

    Args:
        detected_tables: [{title, category, page, rows, cols}] from user DPR.
        spec_chunks: Table-level spec chunks from retrieve_for_table().

    Returns:
        One ValidationResult per mandatory table requirement.
    """
    spec_context = format_chunks_as_context(spec_chunks, max_chars=3000)
    tables_str = "\n".join(
        f"  {i+1}. \"{t.get('title','Untitled')}\" "
        f"(category={t.get('category','?')}, page={t.get('page','?')}, "
        f"rows={t.get('rows','?')}, cols={t.get('cols','?')})"
        for i, t in enumerate(detected_tables)
    ) or "  (No tables detected)"

    prompt = f"""## DPR FORMAT SPEC — Mandatory table requirements:
{spec_context}

## USER DPR — Detected tables:
{tables_str}

## TASK:
For each MANDATORY table listed in the Vol-I spec, determine if it is present in the user DPR.

Return a JSON array. Each element:
{{
  "chapter": "<table name from spec>",
  "status": "PASS | FAIL | WARNING | UNKNOWN",
  "missing_items": [],
  "reference_section": "<Vol-I section requiring this table>",
  "reason": "<explanation>",
  "confidence": <0.0-1.0>,
  "evidence": "<matching table title from user DPR, or empty>",
  "suggested_correction": "<required table name/format, or empty if PASS>"
}}

Return ONLY the JSON array."""

    try:
        raw_text = _call_llm(prompt, _SYSTEM_PROMPT)
        raw_text = raw_text.strip()

        arr_match = re.search(r"\[[\s\S]+\]", raw_text, re.DOTALL)
        if arr_match:
            parsed = json.loads(arr_match.group(0))
        else:
            parsed = json.loads(raw_text)

        if not isinstance(parsed, list):
            parsed = [parsed]

        results: list[ValidationResult] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            status = item.get("status", "UNKNOWN").upper()
            if status not in ("PASS", "FAIL", "WARNING", "UNKNOWN"):
                status = "UNKNOWN"
            results.append(ValidationResult(
                chapter=item.get("chapter", "Unknown Table"),
                category="table",
                status=status,
                missing_items=item.get("missing_items", []),
                reference_section=item.get("reference_section", "Vol-I"),
                reason=item.get("reason", ""),
                confidence=float(item.get("confidence", 0.5)),
                evidence=item.get("evidence", ""),
                suggested_correction=item.get("suggested_correction", ""),
            ))
        return results

    except Exception as e:
        logger.error(f"validate_tables failed: {e}")
        return [ValidationResult(
            chapter="Table Validation",
            category="table",
            status="UNKNOWN",
            reason=f"LLM call failed: {e}",
            confidence=0.0,
        )]


def validate_section_dependencies(
    present_chapters: list[str],
    spec_chunks: list[SpecChunk],
) -> list[ValidationResult]:
    """
    Task 4: Check cross-chapter dependencies.

    Examples:
      - FIRR/Financial Analysis requires Traffic Survey + Cost Estimates
      - EIRR requires Traffic + Cost + Environmental
      - Risk Analysis requires all engineering chapters

    Args:
        present_chapters: List of chapter titles found in user DPR.
        spec_chunks: Chapter spec chunks for context.
    """
    spec_context = format_chunks_as_context(spec_chunks[:5], max_chars=2000)
    chapters_str = "\n".join(f"  - {c}" for c in present_chapters) or "(none)"

    prompt = f"""## CONTEXT from Vol-I spec:
{spec_context}

## USER DPR — Chapters present:
{chapters_str}

## TASK:
Check for CROSS-CHAPTER DEPENDENCY violations in the user DPR.

Known mandatory dependencies in Railway DPR Vol-I:
- "Financial Analysis" (FIRR) REQUIRES: "Traffic Survey" AND "Cost Estimates" to be present
- "Economic Analysis" (EIRR) REQUIRES: "Traffic Survey" AND "Cost Estimates" AND "Environmental Assessment"
- "Risk Analysis" REQUIRES: at least "Engineering Survey" AND "Cost Estimates"
- "Cost Estimates" REQUIRES: "Engineering Survey" (alignment data) AND "Permanent Way" AND "Stations & Yards"

For each dependency, return a result:
{{
  "chapter": "<dependent chapter name>",
  "status": "PASS | FAIL | WARNING",
  "missing_items": ["<prerequisite chapter that is missing>"],
  "reference_section": "Vol-I dependency requirement",
  "reason": "<explanation>",
  "confidence": <0.0-1.0>,
  "evidence": "<chapters actually present that are relevant>",
  "suggested_correction": "<what to add>"
}}

Return ONLY a JSON array of results for dependencies that have issues (skip PASS results for brevity).
If all dependencies are met, return empty array: []"""

    try:
        raw_text = _call_llm(prompt, _SYSTEM_PROMPT)
        raw_text = raw_text.strip()

        # Handle empty array
        if raw_text in ("[]", "[ ]"):
            return []

        arr_match = re.search(r"\[[\s\S]*\]", raw_text, re.DOTALL)
        if arr_match:
            parsed = json.loads(arr_match.group(0))
        else:
            parsed = []

        results: list[ValidationResult] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            status = item.get("status", "UNKNOWN").upper()
            if status not in ("PASS", "FAIL", "WARNING", "UNKNOWN"):
                status = "UNKNOWN"
            results.append(ValidationResult(
                chapter=item.get("chapter", "Dependency Check"),
                category="dependency",
                status=status,
                missing_items=item.get("missing_items", []),
                reference_section=item.get("reference_section", "Vol-I"),
                reason=item.get("reason", ""),
                confidence=float(item.get("confidence", 0.5)),
                evidence=item.get("evidence", ""),
                suggested_correction=item.get("suggested_correction", ""),
            ))
        return results

    except Exception as e:
        logger.error(f"validate_section_dependencies failed: {e}")
        return []


def validate_executive_summary(
    exec_summary_text: str,
    spec_chunks: list[SpecChunk],
) -> ValidationResult:
    """
    Task 5: Validate executive summary completeness.

    The executive summary must contain salient features including:
    project route, length, cost, FIRR, EIRR, key parameters.
    """
    spec_context = format_chunks_as_context(spec_chunks, max_chars=2000)
    text_snippet = exec_summary_text[:2500] if exec_summary_text else "(Not found)"

    prompt = f"""## DPR FORMAT SPEC — Executive Summary requirements (Vol-I):
{spec_context}

## USER DPR — Executive Summary text (first 2500 chars):
{text_snippet}

## TASK:
Assess whether the Executive Summary satisfies the Vol-I requirements.

It MUST include ALL of: project route/name, total length (km), estimated cost,
FIRR value, EIRR value, traffic data, key engineering parameters.

Return ONLY this JSON:
{{
  "chapter": "Executive Summary",
  "status": "PASS | FAIL | WARNING | UNKNOWN",
  "missing_items": ["<missing element 1>", "..."],
  "reference_section": "Vol-I, Ch.1 Executive Summary",
  "reason": "<explanation>",
  "confidence": <0.0-1.0>,
  "evidence": "<key phrase found in summary showing what IS present>",
  "suggested_correction": "<specific missing elements to add>"
}}"""

    try:
        raw_text = _call_llm(prompt, _SYSTEM_PROMPT)
        parsed = _extract_json(raw_text)
        return _safe_result("Executive Summary", "chapter", parsed, spec_chunks, text_snippet[:200])
    except Exception as e:
        logger.error(f"validate_executive_summary failed: {e}")
        return ValidationResult(
            chapter="Executive Summary",
            category="chapter",
            status="UNKNOWN",
            reason=f"LLM call failed: {e}",
            confidence=0.0,
        )
