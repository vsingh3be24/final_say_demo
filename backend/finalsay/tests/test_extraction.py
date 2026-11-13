"""Extraction tests: field extraction, redaction, and OCR graceful degradation."""

from __future__ import annotations

import pytest

from finalsay.services import extraction
from finalsay.services.extraction import OcrUnavailable

SAMPLE = (
    "Office of the Registrar\n"
    "Attention: all first-year students\n"
    "The mid-term exam is postponed to 22 Sept 2024.\n"
    "Deadline: submit forms by 20 Sept 2024.\n"
    "Contact Dr. Jane Smith at jane.smith@northgate.edu or +1 415 555 2671.\n"
    "Roll number 21CS0456 must re-register.\n"
    "Name: Robert Brown\n"
)


def test_fields_extracted():
    result = extraction.extract(text=SAMPLE)
    fields = result.fields
    assert set(["issuer", "date", "deadline", "audience", "action"]).issubset(
        fields.keys()
    )
    # issuer picked up from the "Office of" marker.
    assert fields["issuer"][0] is not None
    # a date is recognized.
    assert fields["date"][0] is not None
    # action clause mentions the postponement.
    assert "postpon" in (fields["action"][0] or "").lower()
    # confidences are in [0, 1].
    for value, conf in fields.values():
        assert 0.0 <= conf <= 1.0


def test_body_text_does_not_get_misidentified_as_issuer():
    fields = extraction.extract_fields(
        "The End-Semester Examinations will commence from 20 December 2026."
    )
    assert fields["issuer"] == (None, 0.0)


def test_explicit_issuer_marker_is_extracted():
    fields = extraction.extract_fields(
        "Issued by: Thapar Institute of Engineering and Technology\n"
        "Examinations will commence from 20 December 2026."
    )
    assert fields["issuer"][0] == "Thapar Institute of Engineering and Technology"


def test_redaction_masks_pii():
    redacted = extraction.redact(SAMPLE)
    # Email removed.
    assert "jane.smith@northgate.edu" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    # Phone removed.
    assert "555 2671" not in redacted
    assert "[REDACTED_PHONE]" in redacted
    # Roll number removed.
    assert "21CS0456" not in redacted
    assert "[REDACTED_ID]" in redacted
    # Names removed.
    assert "Jane Smith" not in redacted
    assert "Robert Brown" not in redacted
    assert "[REDACTED_NAME]" in redacted


def test_redaction_preserves_dates_academic_years_and_times():
    text = (
        "Autumn 2026-2027; date 12 October 2026; ISO date 2026-10-12; "
        "event 12/10/2026 at 10:00. Office phone: 0175-2393022."
    )
    redacted = extraction.redact(text)
    assert "2026-2027" in redacted
    assert "12 October 2026" in redacted
    assert "2026-10-12" in redacted
    assert "12/10/2026" in redacted
    assert "10:00" in redacted
    assert "0175-2393022" not in redacted
    assert "[REDACTED_PHONE]" in redacted


def test_extract_returns_only_redacted_text():
    result = extraction.extract(text=SAMPLE)
    # The returned text must not contain any original PII.
    assert "jane.smith@northgate.edu" not in result.redacted_text
    assert "21CS0456" not in result.redacted_text
    assert "Robert Brown" not in result.redacted_text
    # Fields extracted from redacted text must not leak PII either.
    for value, _conf in result.fields.values():
        if value:
            assert "jane.smith@northgate.edu" not in value
            assert "21CS0456" not in value


def test_ocr_unavailable_raises_typed_error(monkeypatch):
    # Force "no tesseract engine available".
    monkeypatch.setattr(extraction, "_tesseract_available", lambda: None)
    with pytest.raises(OcrUnavailable):
        extraction.acquire_text(image_bytes=b"\x89PNG\r\n\x1a\n fake image bytes")


def test_pasted_text_path_works_without_ocr(monkeypatch):
    monkeypatch.setattr(extraction, "_tesseract_available", lambda: None)
    # Pasted text must work even when no OCR engine exists.
    result = extraction.extract(text="Exam on 15 Sept.")
    assert "15 Sept" in result.redacted_text


def test_extraction_repairs_lone_utf16_surrogates_and_preserves_unicode():
    result = extraction.extract(
        text="Exam notice 🎓 includes malformed PDF text: \ud83c"
    )

    assert "🎓" in result.redacted_text
    assert "\ufffd" in result.redacted_text
    assert "\ud83c" not in result.redacted_text


def test_blank_pdf_uses_ocr_fallback_when_available(monkeypatch):
    from io import BytesIO
    from pypdf import PdfWriter

    payload = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(payload)
    monkeypatch.setattr(
        extraction,
        "_ocr_pdf",
        lambda _data: "Official examination notice with a revised examination date.",
    )

    assert extraction.text_from_pdf(payload.getvalue()).startswith("Official examination notice")
