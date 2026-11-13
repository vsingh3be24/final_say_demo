"""SQLAlchemy ORM models — the full FinalSay data model (design.md section 3).

Temporal relations between notices are stored as edges in a relational table
(``relation_edge``), never in a graph database (GC-7).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finalsay.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Relationship taxonomy and enumerated string values (kept as plain strings
# for portability across SQLite/Postgres; validated at the application layer). ---

RELATIONSHIP_LABELS = (
    "consistent",
    "contradictory",
    "superseded",
    "corrected",
    "extended",
    "cancelled",
    "unresolved",
)
USER_ROLES = ("student", "reviewer", "admin", "issuer")
NOTICE_KINDS = ("official", "submission")
EDGE_STATUSES = ("auto", "unresolved", "confirmed", "corrected")


class Institution(Base):
    __tablename__ = "institution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    scrape_type: Mapped[str] = mapped_column(String(32), default="unconfigured", nullable=False)
    scrape_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    notices: Mapped[list["Notice"]] = relationship(back_populates="institution")


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="student", nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class IssuerMembership(Base):
    """Explicit grant allowing an issuer to publish for one institution."""

    __tablename__ = "issuer_membership"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship()
    institution: Mapped["Institution"] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "institution_id", name="uq_issuer_institution"),
    )


class Notice(Base):
    __tablename__ = "notice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institution.id"), nullable=True
    )
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # official | submission
    title: Mapped[str | None] = mapped_column(String(500))
    published_date: Mapped[str | None] = mapped_column(String(80))
    issuer: Mapped[str | None] = mapped_column(String(300))
    notice_date: Mapped[str | None] = mapped_column(String(64))
    deadline: Mapped[str | None] = mapped_column(String(64))
    audience: Mapped[str | None] = mapped_column(String(300))
    action: Mapped[str | None] = mapped_column(Text)
    redacted_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_key: Mapped[str | None] = mapped_column(String(500), index=True)
    # Hash of the exact fetched source document when an adapter exposes it.
    # Separate from ``sha256``, which commits the normalized notice text.
    source_content_sha256: Mapped[str | None] = mapped_column(String(64))
    extraction_quality: Mapped[str] = mapped_column(
        String(24), default="unknown", nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    previous_version_id: Mapped[int | None] = mapped_column(ForeignKey("notice.id"))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    institution: Mapped["Institution | None"] = relationship(back_populates="notices")
    fields: Mapped[list["NoticeField"]] = relationship(
        back_populates="notice", cascade="all, delete-orphan"
    )
    document_extractions: Mapped[list["NoticeDocumentExtraction"]] = relationship(
        back_populates="notice", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_notice_institution_id", "institution_id"),
        Index("ix_notice_kind", "kind"),
        Index(
            "uq_notice_current_official_source_key",
            "institution_id",
            "source_key",
            unique=True,
            sqlite_where=text("kind = 'official' AND is_current = TRUE AND source_key IS NOT NULL"),
            postgresql_where=text("kind = 'official' AND is_current IS TRUE AND source_key IS NOT NULL"),
        ),
    )


class NoticeField(Base):
    __tablename__ = "notice_field"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)

    notice: Mapped["Notice"] = relationship(back_populates="fields")


class NoticeDocumentExtraction(Base):
    """Redacted source-document text stored without rewriting a notice version."""

    __tablename__ = "notice_document_extraction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("notice.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    notice: Mapped["Notice"] = relationship(back_populates="document_extractions")

    __table_args__ = (
        UniqueConstraint(
            "notice_id", "source_url", name="uq_notice_document_extraction_source"
        ),
    )


class RelationEdge(Base):
    """Typed temporal relation as a relational edge (GC-7)."""

    __tablename__ = "relation_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    src_notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    dst_notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_relation_edge_status", "status"),)


class MerkleRoot(Base):
    __tablename__ = "merkle_root"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anchor_kind: Mapped[str | None] = mapped_column(String(20))
    anchor_ref: Mapped[str | None] = mapped_column(String(200))
    anchor_chain_id: Mapped[int | None] = mapped_column(Integer)
    anchor_network: Mapped[str | None] = mapped_column(String(40))
    anchor_contract_address: Mapped[str | None] = mapped_column(String(42))
    anchor_issuer_address: Mapped[str | None] = mapped_column(String(42))
    anchor_issuer_id: Mapped[str | None] = mapped_column(String(64))
    anchor_batch_id: Mapped[str | None] = mapped_column(String(64))
    anchor_block_number: Mapped[int | None] = mapped_column(Integer)
    anchor_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    anchor_submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    anchor_status: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    anchor_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class MerkleProof(Base):
    __tablename__ = "merkle_proof"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    root_id: Mapped[int] = mapped_column(ForeignKey("merkle_root.id"), nullable=False)
    proof_json: Mapped[str] = mapped_column(Text, nullable=False)
    leaf_index: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_merkle_proof_notice_id", "notice_id"),)


class AnchorBlock(Base):
    """Local append-only hash-chain block (LOCAL anchor)."""

    __tablename__ = "anchor_block"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    this_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ScrapeRun(Base):
    """Audit record for a manual source poll and its per-source outcome."""

    __tablename__ = "scrape_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institution.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    modified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ScrapeProgress(Base):
    """Persistent bounded backfill checkpoint for each configured live source."""

    __tablename__ = "scrape_progress"

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institution.id"), primary_key=True
    )
    cursor: Mapped[str | None] = mapped_column(String(1_000))
    backfill_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ReviewCase(Base):
    __tablename__ = "review_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edge_id: Mapped[int] = mapped_column(ForeignKey("relation_edge.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    assigned_role: Mapped[str | None] = mapped_column(String(20))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    resolved_label: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class BenchmarkPair(Base):
    __tablename__ = "benchmark_pair"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    official_id: Mapped[int] = mapped_column(ForeignKey("notice.id"), nullable=False)
    gold_label: Mapped[str | None] = mapped_column(String(20))
    # Diversified per-pair phrasing shown on the benchmark screen. These are
    # display strings for the labelled benchmark dataset only; they do NOT feed
    # the eval harness (which reads seed/fixtures gold data) and do NOT affect
    # kappa (computed from the annotator label columns). Kept nullable so older
    # rows / minimal seeds still validate.
    submission_text: Mapped[str | None] = mapped_column(Text)
    official_text: Mapped[str | None] = mapped_column(Text)

    annotations: Mapped[list["BenchmarkAnnotation"]] = relationship(
        back_populates="pair", cascade="all, delete-orphan"
    )


class BenchmarkAnnotation(Base):
    __tablename__ = "benchmark_annotation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("benchmark_pair.id"), nullable=False)
    annotator: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    pair: Mapped["BenchmarkPair"] = relationship(back_populates="annotations")

    __table_args__ = (
        Index(
            "uq_benchmark_annotation_reviewer_pair",
            "user_id",
            "pair_id",
            unique=True,
            sqlite_where=text("user_id IS NOT NULL"),
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )


class BenchmarkCompletion(Base):
    """Reviewer lock indicating a complete blind annotation pass.

    The corpus fingerprint prevents showing agreement for a different pair set
    after benchmark content changes. A changed corpus requires a fresh pass.
    """

    __tablename__ = "benchmark_completion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, unique=True
    )
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pair_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    user: Mapped["User"] = relationship()
