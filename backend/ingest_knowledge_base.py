#!/usr/bin/env python3
"""
ingest_knowledge_base.py — Builds the DPR validation knowledge base in ChromaDB.

SOURCE OF TRUTH:
  The DPR format Vol-I.pdf is a fully image-scanned PDF with no extractable text.
  Instead, the knowledge base is built from authoritative structured sources:

  1. backend/references/dpr_format_v1.json    — Chapter specs, table requirements, keywords
  2. backend/references/railway_aliases.json  — Accepted title variants per chapter
  3. backend/ground_truth/*.json             — Gold-standard real DPR examples
     (Adipur, Akola, ADRA, ADTP — all derived from cross-referencing Vol-I)

This gives a richer, structured, noise-free knowledge base compared to OCR'd images.

Hierarchical storage:
  Volume → Chapter → Section/Content → Table

Usage:
  python ingest_knowledge_base.py              # full ingestion
  python ingest_knowledge_base.py --dry-run    # preview chunks, no DB writes
  python ingest_knowledge_base.py --force      # re-ingest (overwrites)
  python ingest_knowledge_base.py --status     # show KB status only
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# ── Bootstrap path ─────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from core.config import settings
from rag.chroma_store import (
    chroma_store,
    COLLECTION_VOLUME,
    COLLECTION_CHAPTER,
    COLLECTION_SECTION,
    COLLECTION_TABLE,
    ALL_COLLECTIONS,
)
from rag.embedder import embed_batch, check_ollama_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Detailed per-chapter specification content
# Derived from DPR format Vol-I cross-referenced with Adipur, Akola, ADRA, ADTP
# ─────────────────────────────────────────────────────────────────────────────

CHAPTER_SPEC_DETAILS: dict[str, dict] = {
    "Executive Summary": {
        "required_fields": [
            "project name and route",
            "project justification",
            "total route length in km",
            "estimated project cost (Rs. Crores)",
            "FIRR value (Financial Internal Rate of Return percentage)",
            "EIRR value (Economic Internal Rate of Return percentage)",
            "payback period",
            "NPV (Net Present Value)",
            "traffic data summary (PCU, freight, passenger)",
            "key engineering parameters (max gradient, curve radius)",
            "land acquisition area (hectares)",
            "environmental clearance status",
            "project implementation timeline",
            "salient features table",
        ],
        "required_subsections": [
            "Introduction / Project Background",
            "Salient Features",
            "Traffic Summary",
            "Cost Summary",
            "Financial Viability Summary",
            "Economic Viability Summary",
        ],
        "min_pages": 3,
        "description": (
            "The Executive Summary must present a complete overview of the entire DPR. "
            "It must include quantified values for cost, FIRR, EIRR, route length, and "
            "traffic projections. Missing any of these key metrics renders the executive "
            "summary incomplete. The salient features table must be present."
        ),
    },
    "Traffic Survey": {
        "required_fields": [
            "base year traffic data (freight and passenger)",
            "PCU (Passenger Car Unit) calculations",
            "line capacity utilization percentage",
            "traffic projection for 30-year horizon",
            "origin-destination (OD) study results",
            "earnings projection table",
            "commodity-wise freight traffic data",
            "mode-wise traffic distribution",
            "peak hour / peak direction traffic",
        ],
        "required_subsections": [
            "Existing Traffic",
            "Traffic Projection / Forecast",
            "Line Capacity Analysis",
            "Earnings Projection",
        ],
        "required_tables": [
            "Traffic table showing line capacity utilization",
            "Earnings projection table (year-wise)",
            "PCU-wise traffic volume table",
            "Commodity-wise freight traffic table",
        ],
        "min_pages": 5,
        "description": (
            "The Traffic Survey chapter is the foundation for financial and economic analyses. "
            "It must contain actual survey data, not just assumptions. "
            "Line capacity utilization must be calculated using the approved formula. "
            "Traffic projections must extend at least 30 years from the base year. "
            "Earnings projections are mandatory to support FIRR/EIRR calculations."
        ),
    },
    "Engineering Survey": {
        "required_fields": [
            "DGPS survey details",
            "horizontal alignment details (curves, tangents)",
            "vertical alignment details (gradients, grades)",
            "soil investigation / geotechnical findings",
            "chainage of key locations",
            "benchmarks established",
            "topographical features description",
            "latitude/longitude of key points",
        ],
        "required_subsections": [
            "Survey Methodology",
            "Horizontal Alignment",
            "Vertical Alignment / Gradient",
            "Soil Investigation",
            "Geotechnical Report Summary",
        ],
        "min_pages": 5,
        "description": (
            "Engineering Survey must describe the final location survey (FLS) methodology, "
            "horizontal and vertical alignment parameters, and soil/geotechnical findings. "
            "DGPS survey data and benchmarks are mandatory. "
            "The alignment must be described in terms of curves, gradients, and chainage."
        ),
    },
    "Land Requirement": {
        "required_fields": [
            "total land required (in hectares)",
            "land type breakdown (government / private / forest)",
            "village-wise / district-wise land summary",
            "land acquisition timeline",
            "approximate number of affected families/structures",
        ],
        "required_subsections": [
            "Land Requirement Summary",
            "Land Acquisition Details",
        ],
        "required_tables": [
            "Land acquisition summary table (village/district/area/type)",
        ],
        "min_pages": 1,
        "description": (
            "Land Requirement chapter must quantify the total land needed with breakdown "
            "by type (government land, private land, forest land). "
            "A summary table organized by district/village is mandatory. "
            "Forest land involvement triggers additional statutory clearance requirements."
        ),
    },
    "Permanent Way": {
        "required_fields": [
            "track structure type (BG / MG / NG)",
            "rail section (60 kg / 52 kg)",
            "sleeper type (PSC / wooden / steel)",
            "ballast specification and depth",
            "permitted speed",
            "track renewal / maintenance plan",
        ],
        "required_subsections": [
            "Track Structure",
            "Rail Specification",
            "Sleeper Specification",
            "Ballast Specification",
        ],
        "min_pages": 1,
        "description": (
            "Permanent Way chapter specifies the complete track structure for the proposed line. "
            "Rail section, sleeper type, ballast specification, and permitted speed are mandatory. "
            "For doubling projects, the connection to existing track must be described."
        ),
    },
    "Formation, Tunnels & Bridges": {
        "required_fields": [
            "list of major bridges (span-wise)",
            "list of minor bridges",
            "list of road over bridges (ROBs)",
            "list of road under bridges (RUBs)",
            "tunnel details (if any)",
            "formation dimensions (embankment / cutting)",
            "level crossing list and category",
        ],
        "required_subsections": [
            "Formation",
            "Major Bridges",
            "Minor Bridges",
            "Road Over/Under Bridges",
            "Level Crossings",
        ],
        "required_tables": [
            "List of major bridges with chainage and span",
            "List of minor bridges",
            "ROB/RUB schedule",
            "Level crossing schedule",
        ],
        "min_pages": 2,
        "description": (
            "This chapter covers all civil structures. Lists of major bridges, minor bridges, "
            "ROBs and RUBs are mandatory with chainage and span details. "
            "Tunnel details are required if the alignment includes tunnels. "
            "Level crossings must be categorized (A/B/C/D) with proposed treatment."
        ),
    },
    "Stations & Yards": {
        "required_fields": [
            "list of proposed stations / halts",
            "loop line lengths",
            "platform lengths and heights",
            "station category",
            "yard plan description",
            "passenger amenities planned",
        ],
        "required_subsections": [
            "Proposed Stations",
            "Yard Design",
            "Platform Details",
        ],
        "required_tables": [
            "Station schedule with loop lengths and platform details",
        ],
        "min_pages": 1,
        "description": (
            "Stations & Yards chapter must list all proposed/modified stations with their "
            "loop line requirements, platform specifications, and yard layout. "
            "For doubling projects, additional loop lines at stations must be detailed."
        ),
    },
    "Service Buildings": {
        "required_fields": [
            "list of service buildings required",
            "area per building type",
            "location (station/yard) for each building",
            "estimated cost of service buildings",
        ],
        "min_pages": 1,
        "description": (
            "Service Buildings chapter covers all non-residential operational buildings: "
            "offices, workshops, locomotive sheds, crew booking offices, etc. "
            "A schedule of buildings with area and location is required."
        ),
    },
    "Residential Buildings": {
        "required_fields": [
            "staff quarters required (category-wise)",
            "running rooms / rest rooms",
            "estimated cost of residential buildings",
        ],
        "min_pages": 1,
        "description": (
            "Residential Buildings chapter covers staff accommodation requirements: "
            "quarters for different staff grades, running rooms for loco crew, "
            "and rest rooms. Category-wise schedule of quarters is mandatory."
        ),
    },
    "Shifting of Utilities": {
        "required_fields": [
            "list of utilities to be shifted",
            "type of utility (OHE, HT/LT power line, telecom, water, gas pipeline)",
            "estimated cost of shifting",
            "responsible agency for each utility",
        ],
        "min_pages": 1,
        "description": (
            "Shifting of Utilities chapter lists all existing utilities (overhead electrical "
            "lines, telecommunications cables, water pipelines) that need to be relocated "
            "due to the new railway alignment. Cost and agency responsibility must be stated."
        ),
    },
    "Electrical Traction & General": {
        "required_fields": [
            "electrification scheme (25 KV AC OHE)",
            "traction substation details",
            "OHE mast spacing and height",
            "neutral section locations",
            "general electrical works (staff quarters, station lighting)",
        ],
        "required_subsections": [
            "Traction System",
            "OHE Details",
            "Traction Sub-stations",
            "General Electrical Works",
        ],
        "min_pages": 2,
        "description": (
            "Electrical Traction & General chapter covers the 25 KV AC overhead electrification "
            "system and general electrical works. Traction substation requirements, OHE "
            "specifications, and neutral section locations are mandatory for electrified sections."
        ),
    },
    "Signal & Telecommunication": {
        "required_fields": [
            "signalling system type (panel interlocking / electronic interlocking / MACLS)",
            "number of signals to be provided",
            "block working type",
            "telecom system details (OFC, QUAD cable, radio)",
            "level crossing protection (interlocked/non-interlocked)",
        ],
        "required_subsections": [
            "Signalling System",
            "Block Working",
            "Telecommunication System",
            "Level Crossing Protection",
        ],
        "min_pages": 2,
        "description": (
            "Signal & Telecommunication chapter must describe the interlocking system type, "
            "block working method, and telecom infrastructure. For new lines, "
            "MACLS (Multi Aspect Colour Light Signalling) is typically required. "
            "OFC/telecom cable route must be described."
        ),
    },
    "Environmental Assessment and Social Impact Assessment": {
        "required_fields": [
            "environmental baseline data",
            "flora and fauna assessment",
            "forest land involvement and category",
            "water bodies affected",
            "air quality and noise impact assessment",
            "social impact assessment (affected families, displacement)",
            "resettlement and rehabilitation plan",
            "mitigation measures",
            "environmental management plan (EMP)",
        ],
        "required_subsections": [
            "Baseline Environmental Status",
            "Environmental Impact",
            "Social Impact Assessment",
            "Mitigation Measures",
            "Environmental Management Plan",
        ],
        "min_pages": 3,
        "description": (
            "Environmental and Social Impact Assessment is mandatory. It must cover "
            "both EIA (Environmental Impact Assessment) and SIA (Social Impact Assessment). "
            "Forest land involvement requires detailed forest clearance documentation. "
            "An Environmental Management Plan (EMP) is mandatory."
        ),
    },
    "Statutory Clearances": {
        "required_fields": [
            "forest clearance status (if forest land involved)",
            "environmental clearance status",
            "wildlife board clearance (if wildlife sanctuary nearby)",
            "coastal regulation zone clearance (if applicable)",
            "list of all required clearances with status",
        ],
        "min_pages": 1,
        "description": (
            "Statutory Clearances chapter must list all regulatory approvals required "
            "for the project. Forest clearance under Forest Conservation Act, "
            "environmental clearance under EIA Notification, and wildlife clearances "
            "must be identified. Status of each clearance (obtained/pending/not required) "
            "must be stated."
        ),
    },
    "Cost Estimates": {
        "required_fields": [
            "abstract of estimated cost (department-wise breakdown)",
            "civil engineering cost",
            "track/permanent way cost",
            "electrical traction cost",
            "signal and telecommunication cost",
            "land acquisition cost",
            "contingencies percentage",
            "total project cost in Rs. Crores",
            "cost per km",
        ],
        "required_subsections": [
            "Abstract of Cost",
            "Department-wise Cost",
            "Land Acquisition Cost",
            "Contingencies",
        ],
        "required_tables": [
            "Abstract of cost (department-wise)",
            "Bill of quantities (BoQ) summary",
        ],
        "min_pages": 2,
        "description": (
            "Cost Estimates chapter must provide a complete department-wise breakdown of the "
            "estimated project cost. The abstract of cost must include civil, track, electrical, "
            "S&T, and land acquisition components separately. Total cost and cost per km are "
            "mandatory. BoQ or schedule of rates must support the estimates."
        ),
    },
    "Financial Analysis": {
        "required_fields": [
            "FIRR (Financial Internal Rate of Return) percentage",
            "NPV (Net Present Value) at 12% discount rate",
            "payback period (years)",
            "revenue projections (year-wise for 30 years)",
            "operating cost assumptions",
            "project cost phasing",
            "sensitivity analysis",
        ],
        "required_subsections": [
            "Financial Model Assumptions",
            "Revenue Projections",
            "Operating Cost",
            "FIRR Calculation",
            "NPV Calculation",
            "Sensitivity Analysis",
        ],
        "required_tables": [
            "FIRR calculation table (30-year cash flow)",
            "NPV calculation table",
            "Sensitivity analysis table",
        ],
        "min_pages": 2,
        "description": (
            "Financial Analysis chapter computes the FIRR for the project. "
            "FIRR must be computed over a 30-year horizon based on traffic/revenue projections "
            "from the Traffic Survey chapter and costs from Cost Estimates chapter. "
            "Both NPV and FIRR values must be explicitly stated. "
            "Sensitivity analysis on traffic growth rate and cost overrun is mandatory."
        ),
    },
    "Economic Analysis": {
        "required_fields": [
            "EIRR (Economic Internal Rate of Return) percentage",
            "economic benefits (time savings, accident reduction, resource cost savings)",
            "benefit-cost ratio (BCR)",
            "30-year economic cash flow",
            "shadow pricing methodology",
        ],
        "required_subsections": [
            "Economic Benefits",
            "EIRR Calculation",
            "Benefit-Cost Ratio",
        ],
        "required_tables": [
            "EIRR calculation table (30-year economic cash flow)",
            "Economic benefits summary table",
        ],
        "min_pages": 2,
        "description": (
            "Economic Analysis chapter computes the EIRR for the project from a national "
            "economic perspective. Economic benefits include resource cost savings, "
            "time savings, accident cost reduction, and externality benefits. "
            "EIRR and BCR values must be explicitly stated."
        ),
    },
    "Risk Analysis": {
        "required_fields": [
            "risk register (list of identified risks)",
            "risk probability assessment",
            "risk impact assessment",
            "risk mitigation measures",
            "residual risk rating",
        ],
        "required_subsections": [
            "Risk Identification",
            "Risk Assessment Matrix",
            "Risk Mitigation",
            "Risk Register",
        ],
        "required_tables": [
            "Risk register table (risk, probability, impact, mitigation, residual risk)",
        ],
        "min_pages": 1,
        "description": (
            "Risk Analysis chapter must identify, assess, and propose mitigation for all "
            "significant project risks. A risk register table with probability and impact "
            "ratings is mandatory. Risks must include construction risks, traffic risks, "
            "financial risks, and environmental/social risks."
        ),
    },
}

# Mandatory tables per the Vol-I spec
MANDATORY_TABLES_SPEC: list[dict] = [
    {
        "name": "Traffic table (line capacity utilization)",
        "chapter": "Traffic Survey",
        "chapter_number": 2,
        "description": (
            "Must show line capacity utilization percentage for existing and proposed sections. "
            "Columns: section, existing capacity, utilized capacity, utilization %, "
            "proposed additional capacity. Required to justify the project need."
        ),
    },
    {
        "name": "Earnings projection table",
        "chapter": "Traffic Survey",
        "chapter_number": 2,
        "description": (
            "Must show year-wise earnings projections for at least 30 years. "
            "Separate rows for freight earnings, passenger earnings, and sundry earnings. "
            "Base year traffic must be stated. Required for FIRR computation."
        ),
    },
    {
        "name": "Land acquisition summary table",
        "chapter": "Land Requirement",
        "chapter_number": 4,
        "description": (
            "Must show district/village-wise land area required, categorized by type "
            "(government land, private land, forest land). "
            "Total area in hectares must be stated clearly."
        ),
    },
    {
        "name": "List of major bridges",
        "chapter": "Formation, Tunnels & Bridges",
        "chapter_number": 6,
        "description": (
            "Must list all major bridges (span > 18m typically) with chainage, span, "
            "type (PSC girder, steel truss, etc.), and estimated cost. "
            "Each bridge needs separate entry with location and hydraulic data."
        ),
    },
    {
        "name": "List of minor bridges / culverts",
        "chapter": "Formation, Tunnels & Bridges",
        "chapter_number": 6,
        "description": (
            "Must list all minor bridges and culverts with chainage and span. "
            "Count and estimated cost are mandatory."
        ),
    },
    {
        "name": "Abstract of cost (department-wise)",
        "chapter": "Cost Estimates",
        "chapter_number": 15,
        "description": (
            "Must show estimated cost broken down by department: Civil, Track, Electrical/OHE, "
            "S&T, Telecom, Land acquisition, Misc/Contingencies. "
            "Total in Rs. Crores and cost per km are mandatory."
        ),
    },
    {
        "name": "FIRR calculation table",
        "chapter": "Financial Analysis",
        "chapter_number": 16,
        "description": (
            "30-year cash flow table for FIRR computation. "
            "Must show year, project cost outflow, revenue inflow, O&M cost, net cash flow. "
            "FIRR percentage must be explicitly computed from this table."
        ),
    },
    {
        "name": "EIRR calculation table",
        "chapter": "Economic Analysis",
        "chapter_number": 17,
        "description": (
            "30-year economic cash flow table for EIRR computation. "
            "Must show economic costs and economic benefits year-wise. "
            "EIRR percentage and BCR must be explicitly computed."
        ),
    },
    {
        "name": "Risk register table",
        "chapter": "Risk Analysis",
        "chapter_number": 18,
        "description": (
            "Must list identified risks with: risk description, probability (H/M/L), "
            "impact (H/M/L), mitigation measure, and residual risk rating. "
            "Both project-level and financial risks must be included."
        ),
    },
]

# Volume-level overview content
VOLUME_SPEC_TEXT = """
DPR Format Volume-I — Railway Detailed Project Report Format Specification

OVERVIEW:
A Detailed Project Report (DPR) Volume-I for Indian Railways must contain 18 mandatory 
chapters in the following order. Each chapter has specific mandatory content, subsections, 
tables, and minimum page requirements.

MANDATORY CHAPTER ORDER (Vol-I):
1.  Executive Summary
2.  Traffic Survey
3.  Engineering Survey
4.  Land Requirement
5.  Permanent Way
6.  Formation, Tunnels & Bridges
7.  Stations & Yards
8.  Service Buildings
9.  Residential Buildings
10. Shifting of Utilities
11. Electrical Traction & General
12. Signal & Telecommunication
13. Environmental Assessment and Social Impact Assessment
14. Statutory Clearances
15. Cost Estimates
16. Financial Analysis
17. Economic Analysis
18. Risk Analysis

GENERAL REQUIREMENTS:
- All 18 chapters must be present in the correct order
- Each chapter must have substantive content, not just headings
- Quantified data and tables are mandatory for financial/traffic chapters
- Technical specifications must meet Railway Board guidelines
- Environmental compliance chapters (13, 14) are legally mandatory
- Financial analysis (chapters 16, 17) requires supporting Traffic and Cost data
- DPR must be self-contained and comprehensive

GRADING CRITERIA:
- Gold (95-100): All 18 chapters present, all mandatory tables, complete content
- Acceptable (85-94): Minor gaps in optional content, all critical chapters present
- Partial (70-84): Some mandatory chapters missing or incomplete
- Legacy (50-69): Significant gaps, older format, key chapters missing
- Invalid (<50): Major mandatory chapters or financial analysis missing

VALIDATION APPROACH:
Chapter presence is necessary but not sufficient. Content completeness matters.
A chapter with only headings and no substantive data fails completeness check.
Cross-chapter dependencies: Financial Analysis requires Traffic + Cost data.
Economic Analysis requires Traffic + Cost + Environmental data.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Build chunks from structured spec
# ─────────────────────────────────────────────────────────────────────────────

def build_all_chunks(
    format_spec: dict,
    aliases: dict,
) -> list[tuple[str, str, dict]]:
    """
    Build all (collection, text, metadata) triples from structured sources.
    Returns list ready for embedding and upsertion.
    """
    triples: list[tuple[str, str, dict]] = []

    # ── Volume-level overview ──────────────────────────────────────────────
    triples.append((
        COLLECTION_VOLUME,
        VOLUME_SPEC_TEXT.strip(),
        {
            "volume": "I",
            "chapter_number": 0,
            "chapter_title": "Volume Overview",
            "section_number": "",
            "section_title": "Complete Format Specification",
            "is_table": False,
            "page": 1,
            "node_type": "VOLUME",
            "source": "vol1_spec",
        }
    ))

    # ── Chapter-level chunks ───────────────────────────────────────────────
    mandatory_chapters = format_spec["volumes"]["I"]["mandatory_chapters"]
    alias_map = aliases.get("aliases", {})

    for ch in mandatory_chapters:
        ch_num = ch["number"]
        ch_title = ch["canonical_title"]
        ch_aliases = alias_map.get(ch_title, [ch_title])
        ch_detail = CHAPTER_SPEC_DETAILS.get(ch_title, {})
        keywords = ch.get("keywords", [])
        min_pages = ch.get("min_pages", 1)

        # Build rich chapter spec text
        lines = [
            f"[Vol-I, Chapter {ch_num}: {ch_title}]",
            f"",
            f"MANDATORY: Yes (required in all Railway DPRs)",
            f"CHAPTER ORDER: {ch_num} of 18",
            f"MINIMUM PAGES: {min_pages}",
            f"",
            f"ACCEPTED TITLE VARIANTS: {', '.join(ch_aliases)}",
            f"",
            f"KEY CONTENT REQUIREMENTS (keywords): {', '.join(keywords)}",
            f"",
        ]

        if ch_detail.get("description"):
            lines += [
                "SPECIFICATION DESCRIPTION:",
                ch_detail["description"],
                "",
            ]

        if ch_detail.get("required_fields"):
            lines += ["MANDATORY FIELDS/DATA (all must be present):"]
            for field in ch_detail["required_fields"]:
                lines.append(f"  - {field}")
            lines.append("")

        if ch_detail.get("required_subsections"):
            lines += ["REQUIRED SUBSECTIONS:"]
            for sub in ch_detail["required_subsections"]:
                lines.append(f"  - {sub}")
            lines.append("")

        if ch_detail.get("required_tables"):
            lines += ["MANDATORY TABLES WITHIN THIS CHAPTER:"]
            for tbl in ch_detail["required_tables"]:
                lines.append(f"  - {tbl}")
            lines.append("")

        chapter_text = "\n".join(lines)

        triples.append((
            COLLECTION_CHAPTER,
            chapter_text,
            {
                "volume": "I",
                "chapter_number": ch_num,
                "chapter_title": ch_title,
                "section_number": "",
                "section_title": "",
                "is_table": False,
                "page": 0,
                "node_type": "CHAPTER",
                "source": "vol1_spec",
                "required": ch.get("required", True),
                "min_pages": min_pages,
            }
        ))

        # ── Section-level chunks (one per key content area) ────────────────
        if ch_detail.get("required_fields"):
            # Pack required fields as a section chunk
            section_text = (
                f"[Vol-I, Ch.{ch_num}: {ch_title} — Required Content Details]\n\n"
                f"The following data/fields are MANDATORY in the '{ch_title}' chapter:\n"
                + "\n".join(f"• {f}" for f in ch_detail["required_fields"])
                + f"\n\nThis chapter must have at least {min_pages} page(s) of substantive content."
            )
            triples.append((
                COLLECTION_SECTION,
                section_text,
                {
                    "volume": "I",
                    "chapter_number": ch_num,
                    "chapter_title": ch_title,
                    "section_number": f"{ch_num}.req",
                    "section_title": "Required Fields",
                    "is_table": False,
                    "page": 0,
                    "node_type": "SECTION",
                    "source": "vol1_spec",
                }
            ))

        # Also embed aliases as a section chunk for better alias retrieval
        if ch_aliases and len(ch_aliases) > 1:
            alias_text = (
                f"[Vol-I, Ch.{ch_num}: {ch_title} — Title Variants]\n\n"
                f"Chapter '{ch_title}' may also appear in DPRs under these equivalent titles:\n"
                + "\n".join(f"• {a}" for a in ch_aliases)
                + f"\n\nAll these titles are acceptable variations for Chapter {ch_num} of the DPR."
            )
            triples.append((
                COLLECTION_SECTION,
                alias_text,
                {
                    "volume": "I",
                    "chapter_number": ch_num,
                    "chapter_title": ch_title,
                    "section_number": f"{ch_num}.alias",
                    "section_title": "Title Variants",
                    "is_table": False,
                    "page": 0,
                    "node_type": "SECTION",
                    "source": "aliases",
                }
            ))

    # ── Table-level chunks ────────────────────────────────────────────────
    mandatory_tables = format_spec["volumes"]["I"].get("mandatory_tables", [])
    # Use detailed table specs
    for tbl_spec in MANDATORY_TABLES_SPEC:
        table_text = (
            f"[Vol-I — Mandatory Table: {tbl_spec['name']}]\n\n"
            f"REQUIRED IN CHAPTER: {tbl_spec['chapter']} (Chapter {tbl_spec['chapter_number']})\n\n"
            f"DESCRIPTION:\n{tbl_spec['description']}\n\n"
            f"STATUS: MANDATORY — absence of this table is a FAIL finding."
        )
        triples.append((
            COLLECTION_TABLE,
            table_text,
            {
                "volume": "I",
                "chapter_number": tbl_spec["chapter_number"],
                "chapter_title": tbl_spec["chapter"],
                "section_number": "",
                "section_title": tbl_spec["name"],
                "is_table": True,
                "page": 0,
                "node_type": "TABLE",
                "source": "vol1_spec",
                "table_name": tbl_spec["name"],
            }
        ))

    # Also add a combined mandatory tables summary chunk
    tables_summary = (
        "[Vol-I — Mandatory Tables Summary]\n\n"
        "The following tables are MANDATORY in a complete DPR:\n\n"
        + "\n".join(
            f"• {t['name']} (Chapter {t['chapter_number']}: {t['chapter']})"
            for t in MANDATORY_TABLES_SPEC
        )
        + "\n\nAbsence of any of these tables is a MAJOR finding."
    )
    triples.append((
        COLLECTION_TABLE,
        tables_summary,
        {
            "volume": "I",
            "chapter_number": 0,
            "chapter_title": "All Chapters",
            "section_number": "",
            "section_title": "Mandatory Tables Summary",
            "is_table": True,
            "page": 0,
            "node_type": "TABLE",
            "source": "vol1_spec",
        }
    ))

    return triples


def build_ground_truth_chunks(gt_dir: Path) -> list[tuple[str, str, dict]]:
    """
    Build additional knowledge chunks from gold-standard ground truth JSONs.
    These serve as real-world examples of compliant DPR structure.
    """
    triples: list[tuple[str, str, dict]] = []

    gt_files = list(gt_dir.glob("*.json"))
    if not gt_files:
        logger.warning(f"No ground truth JSON files found in {gt_dir}")
        return triples

    for gt_file in gt_files:
        if gt_file.name == "dpr_format_truth.json":
            continue  # Skip the spec itself

        try:
            with open(gt_file, encoding="utf-8") as f:
                gt = json.load(f)

            project_name = gt.get("name", gt_file.stem)
            classification = gt.get("classification", "reference")
            chapters = gt.get("chapters_present", [])

            if not chapters:
                continue

            # Build a description of this real DPR as a training example
            ch_list = "\n".join(
                f"  Ch.{c['number']}: '{c['title']}' (page {c.get('page','?')})"
                for c in chapters
            )

            gt_text = (
                f"[Real DPR Example: {project_name}]\n\n"
                f"Classification: {classification.upper()}\n"
                f"Project: {project_name}\n"
                f"Division: {gt.get('division', 'N/A')}\n"
                f"Route Length: {gt.get('length_km', 'N/A')} km\n"
                f"Pages: {gt.get('pages', 'N/A')}\n"
                f"Expected Grade: {gt.get('expected_grade', 'N/A')}\n\n"
                f"CHAPTERS PRESENT ({len(chapters)}/18):\n{ch_list}\n\n"
                f"Capabilities: traffic={gt.get('traffic')}, cost={gt.get('cost')}, "
                f"financial={gt.get('financial')}, risk={gt.get('risk')}, "
                f"environmental={gt.get('environmental')}\n"
            )
            if gt.get("notes"):
                gt_text += f"\nNOTES: {gt['notes']}\n"

            triples.append((
                COLLECTION_VOLUME,
                gt_text,
                {
                    "volume": "I",
                    "chapter_number": 0,
                    "chapter_title": f"Example: {project_name}",
                    "section_number": "",
                    "section_title": classification,
                    "is_table": False,
                    "page": 0,
                    "node_type": "VOLUME",
                    "source": f"ground_truth_{gt_file.stem}",
                }
            ))

            # Per-chapter chunks for each real example chapter
            for c in chapters:
                ch_example_text = (
                    f"[Real DPR Example: {project_name} — Chapter {c['number']}]\n\n"
                    f"In the {classification} DPR '{project_name}':\n"
                    f"Chapter {c['number']} is titled: \"{c['title']}\"\n"
                    f"Located at page: {c.get('page', 'N/A')}\n\n"
                    f"This confirms that Chapter {c['number']} can be titled '{c['title']}' "
                    f"and is acceptable in a {classification} grade DPR."
                )
                triples.append((
                    COLLECTION_CHAPTER,
                    ch_example_text,
                    {
                        "volume": "I",
                        "chapter_number": c["number"],
                        "chapter_title": c["title"],
                        "section_number": "",
                        "section_title": f"Example from {project_name}",
                        "is_table": False,
                        "page": c.get("page", 0),
                        "node_type": "CHAPTER",
                        "source": f"ground_truth_{gt_file.stem}",
                    }
                ))

        except Exception as e:
            logger.warning(f"Failed to load {gt_file}: {e}")

    logger.info(f"Built {len(triples)} chunks from {len(gt_files)-1} ground truth files.")
    return triples


# ─────────────────────────────────────────────────────────────────────────────
# Main Ingestion
# ─────────────────────────────────────────────────────────────────────────────

def ingest(
    references_dir: Path,
    ground_truth_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    batch_size: int = 20,
) -> dict:
    """
    Full ingestion pipeline. Returns KB status dict.
    """
    # Check if already ingested
    if not force and chroma_store.is_knowledge_base_ready():
        status = chroma_store.get_kb_status()
        logger.info("Knowledge base already populated. Use --force to re-ingest.")
        return status

    # Clear if force
    if force:
        logger.info("Force re-ingestion: clearing existing collections...")
        from rag.chroma_store import ALL_COLLECTIONS
        for col_name in ALL_COLLECTIONS:
            chroma_store.delete_collection(col_name)

    # Load source files
    format_spec_path = references_dir / "dpr_format_v1.json"
    aliases_path = references_dir / "railway_aliases.json"

    if not format_spec_path.exists():
        raise FileNotFoundError(f"Format spec not found: {format_spec_path}")
    if not aliases_path.exists():
        raise FileNotFoundError(f"Aliases not found: {aliases_path}")

    with open(format_spec_path, encoding="utf-8") as f:
        format_spec = json.load(f)
    with open(aliases_path, encoding="utf-8") as f:
        aliases = json.load(f)

    logger.info("=" * 62)
    logger.info("DPR Knowledge Base Ingestion")
    logger.info("Source: dpr_format_v1.json + railway_aliases.json + ground_truth/")
    logger.info("=" * 62)

    # Build spec chunks
    logger.info("Step 1: Building spec chunks from references...")
    triples = build_all_chunks(format_spec, aliases)
    logger.info(f"  Spec chunks: {len(triples)}")

    # Build ground truth chunks
    logger.info("Step 2: Building chunks from ground truth examples...")
    gt_triples = build_ground_truth_chunks(ground_truth_dir)
    triples.extend(gt_triples)
    logger.info(f"  Total chunks: {len(triples)}")

    # Count per collection
    col_counts: dict[str, int] = {}
    for col, _, _ in triples:
        col_counts[col] = col_counts.get(col, 0) + 1
    logger.info(f"  Per collection: {col_counts}")

    if dry_run:
        logger.info("[DRY RUN] Skipping embedding and DB writes.")
        logger.info("\nSample chunks:")
        for i, (col, text, meta) in enumerate(triples[:4]):
            logger.info(f"\n--- Chunk {i+1} → {col} ---")
            logger.info(f"  meta: ch={meta.get('chapter_number')} title={meta.get('chapter_title')!r}")
            logger.info(f"  text: {text[:250]}...")
        return col_counts

    # Embed + upsert
    logger.info("Step 3: Embedding and upserting into ChromaDB...")
    total = len(triples)
    start_time = time.time()

    for batch_start in range(0, total, batch_size):
        batch = triples[batch_start:batch_start + batch_size]
        batch_texts = [t[1] for t in batch]
        batch_metas = [t[2] for t in batch]
        batch_cols  = [t[0] for t in batch]

        # Build unique IDs
        batch_ids = []
        for i, (col, text, meta) in enumerate(batch):
            uid = (
                f"{col}"
                f"_ch{meta.get('chapter_number', 0)}"
                f"_src{meta.get('source', 'spec')}"
                f"_{batch_start + i}"
            )
            batch_ids.append(uid)

        try:
            embeddings = embed_batch(batch_texts)
        except Exception as e:
            logger.error(f"Embedding batch {batch_start//batch_size + 1} failed: {e}")
            raise

        # Group by collection and upsert
        by_collection: dict[str, list] = {}
        for i, col in enumerate(batch_cols):
            by_collection.setdefault(col, []).append(
                (batch_ids[i], embeddings[i], batch_texts[i], batch_metas[i])
            )

        for col, items in by_collection.items():
            ids, vecs, docs, metas_list = zip(*items)
            chroma_store.upsert(col, list(ids), list(vecs), list(docs), list(metas_list))

        done = min(batch_start + batch_size, total)
        elapsed = time.time() - start_time
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        logger.info(
            f"  Progress: {done}/{total} ({done/total*100:.0f}%) | "
            f"{rate:.1f} chunks/s | ETA: {eta:.0f}s"
        )

    elapsed = time.time() - start_time
    final_status = chroma_store.get_kb_status()
    logger.info("=" * 62)
    logger.info(f"✅ Ingestion complete in {elapsed:.1f}s")
    for col, info in final_status.items():
        count = info.get("count", 0) if isinstance(info, dict) else info
        logger.info(f"  {col}: {count} chunks")
    logger.info("=" * 62)

    return final_status


def main():
    parser = argparse.ArgumentParser(
        description="Build DPR validation knowledge base from structured spec sources.",
    )
    parser.add_argument("--dry-run",  action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--force",    action="store_true", help="Re-ingest even if KB exists")
    parser.add_argument("--status",   action="store_true", help="Show KB status and exit")
    args = parser.parse_args()

    if args.status:
        status = chroma_store.get_kb_status()
        ready = chroma_store.is_knowledge_base_ready()
        print(f"\nKnowledge Base Ready: {ready}")
        for col, info in status.items():
            count = info.get("count", 0) if isinstance(info, dict) else info
            print(f"  {col}: {count} chunks")
        return 0

    if not args.dry_run:
        logger.info("Checking Ollama connectivity...")
        ok, msg = check_ollama_connection()
        if not ok:
            logger.error(f"Ollama not reachable: {msg}")
            logger.error(
                f"Start Ollama and pull embed model:\n"
                f"  ollama pull {settings.EMBED_MODEL}"
            )
            return 1
        logger.info(msg)

    try:
        result = ingest(
            references_dir=settings.REFERENCES_DIR,
            ground_truth_dir=settings.GROUND_TRUTH_DIR,
            dry_run=args.dry_run,
            force=args.force,
        )
        if not args.dry_run:
            print("\n✅ Knowledge base ready.")
            for col, info in result.items():
                count = info.get("count", 0) if isinstance(info, dict) else info
                print(f"  {col}: {count} chunks")
        return 0
    except Exception as e:
        logger.exception(f"Ingestion failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
