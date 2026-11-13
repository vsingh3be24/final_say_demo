"""Bounded legacy extraction refreshes preserve official notice history."""

import hashlib

from finalsay.adapters.base import RawNotice
from finalsay.models import (
    Institution,
    Notice,
    NoticeDocumentExtraction,
)
from finalsay.services import comparison
from finalsay.services import document_extraction_backfill as backfill
from finalsay.models_iface.semantic_model import SemanticComparisonModel


def _unknown_notice(db, *, scrape_type="vtu_examination", source_url=None):
    host = "vtu.ac.in" if scrape_type == "vtu_examination" else "exam.du.ac.in"
    institution = Institution(
        name="Official Source University",
        slug=f"source-{scrape_type}",
        source_url=f"https://{host}/",
        scrape_type=scrape_type,
        scrape_enabled=True,
        active=True,
    )
    db.add(institution)
    db.flush()
    notice = Notice(
        institution_id=institution.id,
        kind="official",
        title="Revised examination schedule",
        source_url=source_url or f"https://{host}/2026/notice/1/",
        source_key="source-key-1",
        published_date="10 November 2026",
        extraction_quality="unknown",
        redacted_text="Legacy stored listing text.",
        sha256="original-official-notice-hash",
        version_no=1,
        is_current=True,
    )
    db.add(notice)
    db.flush()
    return institution, notice


def test_refresh_stores_hashed_sidecar_without_rewriting_notice_version(db_session, monkeypatch):
    _institution, notice = _unknown_notice(db_session)
    source_url = notice.source_url

    class SourceAdapter:
        allowed_hosts = {"vtu.ac.in"}

        def fetch_post(self, url, title, listing_text=""):
            assert (url, title, listing_text) == (
                source_url,
                "Revised examination schedule",
                "",
            )
            return RawNotice(
                text=(
                    "Issued by: Official Source University\n"
                    "Subject: Revised examination schedule\n"
                    "The semester examinations begin on 15 December 2026."
                ),
                source_url=url,
                institution_slug="source-vtu_examination",
                external_id=url,
                metadata={"extraction_quality": "extracted"},
            )

    monkeypatch.setattr(backfill, "create_live_adapter", lambda _institution: SourceAdapter())
    original_hash = notice.sha256
    original_text = notice.redacted_text

    result = backfill.refresh_unknown_document_extractions(
        db_session, per_institution=1
    )

    extraction_row = db_session.query(NoticeDocumentExtraction).one()
    assert result["stored"] == 1
    assert extraction_row.notice_id == notice.id
    assert extraction_row.source_url == source_url
    assert extraction_row.extraction_quality == "extracted"
    assert extraction_row.extraction_method == "official_source_adapter"
    assert extraction_row.extracted_text_sha256 == hashlib.sha256(
        extraction_row.extracted_text.encode("utf-8")
    ).hexdigest()
    assert "15 December 2026" in extraction_row.extracted_text
    assert notice.extraction_quality == "extracted"
    assert notice.sha256 == original_hash
    assert notice.redacted_text == original_text
    assert notice.version_no == 1
    assert db_session.query(Notice).filter(Notice.is_current.is_(True)).count() == 1


def test_refresh_skips_external_host_without_fetching_it(db_session, monkeypatch):
    _institution, notice = _unknown_notice(
        db_session,
        scrape_type="du_examination",
        source_url="https://drive.google.com/file/d/abc/view",
    )

    class SourceAdapter:
        allowed_hosts = {"exam.du.ac.in"}

        def _document(self, *_args, **_kwargs):
            raise AssertionError("external host must be skipped before fetch")

    monkeypatch.setattr(backfill, "create_live_adapter", lambda _institution: SourceAdapter())

    result = backfill.refresh_unknown_document_extractions(db_session, per_institution=1)

    assert result["stored"] == 0
    assert result["skipped_external"] == 1
    assert notice.extraction_quality == "unknown"
    assert db_session.query(NoticeDocumentExtraction).count() == 0


def test_refresh_returns_institution_scoped_extraction_errors(db_session, monkeypatch):
    institution, notice = _unknown_notice(db_session)

    class SourceAdapter:
        allowed_hosts = {"vtu.ac.in"}

        def fetch_post(self, *_args, **_kwargs):
            raise RuntimeError("PDF stream is corrupt")

    monkeypatch.setattr(backfill, "create_live_adapter", lambda _institution: SourceAdapter())

    result = backfill.refresh_unknown_document_extractions(
        db_session, per_institution=1
    )

    assert result["errors"] == [
        f"{institution.slug}: notice {notice.id}: RuntimeError: PDF stream is corrupt"
    ]
    assert result["institutions"][0]["errors"] == [
        f"notice {notice.id}: RuntimeError: PDF stream is corrupt"
    ]
    assert result["stored"] == 0
    assert db_session.query(NoticeDocumentExtraction).count() == 0


def test_adapter_creation_failure_is_scoped_to_its_institution(db_session, monkeypatch):
    institution, _notice = _unknown_notice(db_session)

    def fail_create(_institution):
        raise RuntimeError("configured source host unavailable")

    monkeypatch.setattr(backfill, "create_live_adapter", fail_create)

    result = backfill.refresh_unknown_document_extractions(
        db_session, per_institution=1
    )

    assert result["errors"] == [
        f"{institution.slug}: RuntimeError: configured source host unavailable"
    ]
    assert result["institutions"][0]["institution_id"] == institution.id
    assert result["institutions"][0]["errors"] == [
        "RuntimeError: configured source host unavailable"
    ]


def test_retrieval_and_comparison_text_include_extracted_sidecar(db_session):
    institution, official = _unknown_notice(db_session)
    sidecar_text = "Full extracted official PDF: examinations commence on 15 December."
    db_session.add(
        NoticeDocumentExtraction(
            notice_id=official.id,
            source_url=official.source_url,
            extracted_text=sidecar_text,
            extracted_text_sha256=hashlib.sha256(sidecar_text.encode()).hexdigest(),
            extraction_quality="extracted",
            extraction_method="official_source_adapter",
        )
    )
    db_session.flush()
    submission = Notice(
        institution_id=institution.id,
        kind="submission",
        issuer="Student",
        redacted_text="Exam schedule for December.",
    )

    class SemanticRanker:
        def rank_candidates(self, _submission, officials):
            return [(officials[0], 0.9, 0.9)]

    candidates = comparison.retrieve_candidates(
        db_session, submission, model=SemanticRanker()
    )

    assert candidates[0].notice.id == official.id
    assert sidecar_text in comparison._submission_text(candidates[0].notice)
    assert sidecar_text in SemanticComparisonModel._notice_text(candidates[0].notice)


def test_dry_run_does_not_store_or_relabel(db_session, monkeypatch):
    _institution, notice = _unknown_notice(db_session)

    class SourceAdapter:
        allowed_hosts = {"vtu.ac.in"}

        def fetch_post(self, url, title, listing_text=""):
            return RawNotice(
                text="Issued by: University\nSubject: Notice\nFull official PDF text.",
                source_url=url,
                institution_slug="source-vtu_examination",
                external_id=url,
                metadata={"extraction_quality": "extracted"},
            )

    monkeypatch.setattr(backfill, "create_live_adapter", lambda _institution: SourceAdapter())
    result = backfill.refresh_unknown_document_extractions(
        db_session, per_institution=1, dry_run=True
    )

    assert result["would_store"] == 1
    assert result["stored"] == 0
    assert notice.extraction_quality == "unknown"
    assert db_session.query(NoticeDocumentExtraction).count() == 0
