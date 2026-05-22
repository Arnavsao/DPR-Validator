"""
SQLAlchemy ORM models for the DPR Validator.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime,
    ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentState(str, enum.Enum):
    UPLOADED   = "UPLOADED"
    PARSING    = "PARSING"
    OCR        = "OCR"
    TABLES     = "TABLES"
    STRUCTURED = "STRUCTURED"
    VALIDATED  = "VALIDATED"
    FAILED     = "FAILED"


class NodeType(str, enum.Enum):
    DOCUMENT   = "DOCUMENT"
    VOLUME     = "VOLUME"
    CHAPTER    = "CHAPTER"
    SECTION    = "SECTION"
    SUBSECTION = "SUBSECTION"
    ANNEXURE   = "ANNEXURE"
    TABLE      = "TABLE"
    FIGURE     = "FIGURE"


class TableCategory(str, enum.Enum):
    TRAFFIC    = "TRAFFIC"
    COST       = "COST"
    BOQ        = "BOQ"
    BRIDGE     = "BRIDGE"
    LAND       = "LAND"
    FIRR       = "FIRR"
    EIRR       = "EIRR"
    EARNINGS   = "EARNINGS"
    RISK       = "RISK"
    GENERAL    = "GENERAL"
    UNKNOWN    = "UNKNOWN"


class MatchType(str, enum.Enum):
    EXACT   = "exact"
    ALIAS   = "alias"
    FUZZY   = "fuzzy"
    MISSING = "missing"


class FindingSeverity(str, enum.Enum):
    CRITICAL = "critical"
    MAJOR    = "major"
    MINOR    = "minor"
    INFO     = "info"


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class Document(Base):
    __tablename__ = "documents"

    id:            Mapped[int]  = mapped_column(Integer, primary_key=True, index=True)
    filename:      Mapped[str]  = mapped_column(String(512))
    original_name: Mapped[str]  = mapped_column(String(512))
    file_path:     Mapped[str]  = mapped_column(String(1024))
    file_size:     Mapped[int]  = mapped_column(Integer, default=0)
    page_count:    Mapped[int]  = mapped_column(Integer, default=0)
    state:         Mapped[str]  = mapped_column(
        SAEnum(DocumentState), default=DocumentState.UPLOADED
    )

    # Extracted metadata
    project_name:  Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    project_route: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    division:      Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    length_km:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    report_date:   Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_reference:  Mapped[bool]  = mapped_column(Boolean, default=False)
    reference_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Timestamps
    uploaded_at:   Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    parsed_at:     Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]]      = mapped_column(Text, nullable=True)

    # Relationships
    pages:           Mapped[list["Page"]]           = relationship(back_populates="document", cascade="all, delete-orphan")
    nodes:           Mapped[list["DocumentNode"]]   = relationship(back_populates="document", cascade="all, delete-orphan")
    tables:          Mapped[list["ExtractedTable"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    validation_runs: Mapped[list["ValidationRun"]]  = relationship(back_populates="document", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

class Page(Base):
    __tablename__ = "pages"

    id:          Mapped[int]  = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int]  = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int]  = mapped_column(Integer)
    text:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    word_count:  Mapped[int]  = mapped_column(Integer, default=0)
    has_images:  Mapped[bool] = mapped_column(Boolean, default=False)
    is_ocr:      Mapped[bool] = mapped_column(Boolean, default=False)  # True if OCR was used

    document: Mapped["Document"] = relationship(back_populates="pages")


# ---------------------------------------------------------------------------
# Document Nodes (Hierarchy Tree)
# ---------------------------------------------------------------------------

class DocumentNode(Base):
    __tablename__ = "document_nodes"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int]           = mapped_column(ForeignKey("documents.id"), index=True)
    parent_id:   Mapped[Optional[int]] = mapped_column(ForeignKey("document_nodes.id"), nullable=True)
    node_type:   Mapped[str]           = mapped_column(SAEnum(NodeType))
    level:       Mapped[int]           = mapped_column(Integer, default=0)
    number:      Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # "1", "1.1", "1.1.1"
    title:       Mapped[str]           = mapped_column(String(512))
    page_start:  Mapped[int]           = mapped_column(Integer, default=1)
    page_end:    Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sequence:    Mapped[int]           = mapped_column(Integer, default=0)  # order within parent

    document: Mapped["Document"]           = relationship(back_populates="nodes")
    children: Mapped[list["DocumentNode"]] = relationship(
        "DocumentNode",
        foreign_keys=[parent_id],
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Extracted Tables
# ---------------------------------------------------------------------------

class ExtractedTable(Base):
    __tablename__ = "extracted_tables"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int]           = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int]           = mapped_column(Integer)
    table_index: Mapped[int]           = mapped_column(Integer, default=0)  # table # on that page
    category:    Mapped[str]           = mapped_column(SAEnum(TableCategory), default=TableCategory.UNKNOWN)
    title:       Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    rows:        Mapped[int]           = mapped_column(Integer, default=0)
    cols:        Mapped[int]           = mapped_column(Integer, default=0)
    content_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized
    extractor:   Mapped[str]           = mapped_column(String(64), default="pdfplumber")

    document: Mapped["Document"] = relationship(back_populates="tables")


# ---------------------------------------------------------------------------
# Validation Runs
# ---------------------------------------------------------------------------

class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int]      = mapped_column(ForeignKey("documents.id"), index=True)
    run_at:      Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Scores (0-100)
    overall_score:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    chapter_score:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    subchapter_score:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    traffic_score:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engineering_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_score:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_score:        Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    table_score:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    grade:         Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    chapters_found: Mapped[int]          = mapped_column(Integer, default=0)
    chapters_total: Mapped[int]          = mapped_column(Integer, default=18)
    tables_found:   Mapped[int]          = mapped_column(Integer, default=0)

    # RAG validation mode identifier: "rag" | "heuristic"
    validation_mode: Mapped[str]         = mapped_column(String(16), default="heuristic")

    # Relationships
    document: Mapped["Document"]  = relationship(back_populates="validation_runs")
    findings: Mapped[list["Finding"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    report:   Mapped[Optional["Report"]] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Findings (Evidence)
# ---------------------------------------------------------------------------

class Finding(Base):
    __tablename__ = "findings"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, index=True)
    run_id:      Mapped[int]           = mapped_column(ForeignKey("validation_runs.id"), index=True)
    category:    Mapped[str]           = mapped_column(String(64))   # e.g. "chapter", "table", "metadata"
    severity:    Mapped[str]           = mapped_column(SAEnum(FindingSeverity), default=FindingSeverity.MAJOR)
    issue:       Mapped[str]           = mapped_column(String(512))  # human-readable issue
    detail:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_type:  Mapped[Optional[str]] = mapped_column(SAEnum(MatchType), nullable=True)
    confidence:  Mapped[float]         = mapped_column(Float, default=1.0)
    page:        Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snippet:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # text excerpt from PDF

    # RAG-specific: grounded evidence fields
    reference_section:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Vol-I section cited
    evidence:             Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # text from user DPR
    suggested_correction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # fix guidance

    run: Mapped["ValidationRun"] = relationship(back_populates="findings")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class Report(Base):
    __tablename__ = "reports"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    run_id:      Mapped[int]      = mapped_column(ForeignKey("validation_runs.id"), index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    report_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["ValidationRun"] = relationship(back_populates="report")
