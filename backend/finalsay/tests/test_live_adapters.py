"""Offline fixtures for allow-listed official live notice sources."""

from pathlib import Path
from threading import Event

import pytest

from finalsay.adapters.base import RawNotice
from finalsay.adapters.live import (
    NitjAcademicAdapter,
    IitbAcademicAdapter,
    PublicSiteClient,
    SourceFetchError,
    ThaparNoticeAdapter,
    VtuExaminationAdapter,
    DuExaminationAdapter,
    MumbaiCircularAdapter,
    _CatalogRows,
    _read_bounded_response,
    _listing_date,
    _MumbaiCircularRows,
    _ThaparNoticeLinks,
    validate_source_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeClient:
    def __init__(self, page_url, page_body):
        self.page_url = page_url
        self.page_body = page_body
        self.calls = []

    def get(self, url, max_bytes, **_kwargs):
        self.calls.append((url, max_bytes))
        if url == self.page_url:
            content_type = "application/json" if ".json" in url or "get/all" in url else "text/html"
            return url, {"Content-Type": content_type}, self.page_body
        return url, {"Content-Type": "application/pdf"}, b"fixture-pdf"


def test_thapar_page_parser_only_selects_notice_list_links():
    parser = _ThaparNoticeLinks()
    parser.feed((FIXTURES / "thapar-notice-board.html").read_text())
    assert [title for _href, title in parser.links] == [
        "Auxiliary Examination (August, 2026)",
        "AC ODDSEM 2026-27 (UG-II, III, IV, PG)",
    ]


def test_thapar_adapter_extracts_pdf_text_and_metadata(monkeypatch):
    import finalsay.adapters.live as live

    page_url = "https://www.thapar.edu/students/pages/dean-academics-notice-board"
    adapter = ThaparNoticeAdapter("thapar", "Thapar Institute", page_url, {"www.thapar.edu"})
    adapter.client = _FakeClient(page_url, (FIXTURES / "thapar-notice-board.html").read_bytes())
    monkeypatch.setattr(
        live,
        "_pdf_text",
        lambda _data: "Notice dated: 12 October 2026. The examination timetable is available in this notice.",
    )
    notices = adapter.fetch()

    assert len(notices) == 2
    assert notices[0].metadata["title"] == "Auxiliary Examination (August, 2026)"
    assert notices[0].source_url.endswith("Auxiliary%20Examinations%20Aug.2026.pdf")
    assert "The examination timetable" in notices[0].text
    assert notices[0].metadata["source_date"] == "12 October 2026"


def test_nitj_feed_decodes_entity_and_extracts_pdf(monkeypatch):
    import finalsay.adapters.live as live

    feed_url = "https://www.nitj.ac.in/api/academicnotices/get/all"
    adapter = NitjAcademicAdapter("nitj", "NIT Jalandhar", feed_url, {"www.nitj.ac.in"})
    adapter.client = _FakeClient(feed_url, (FIXTURES / "nitj-academic-notices.json").read_bytes())
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Scholarship application notice body.")
    notices = adapter.fetch()

    assert len(notices) == 1
    assert notices[0].external_id == "NITJ/ACAD/59"
    assert "Scholarship for J&K Students" in notices[0].text
    assert notices[0].metadata["source_date"] == "27/01/2016"
    assert "J&Kstudents.pdf" in notices[0].source_url


def test_iitb_notice_page_extracts_same_site_circular_pdf(monkeypatch):
    import finalsay.adapters.live as live

    page_url = "https://acad.iitb.ac.in/node/440"
    adapter = IitbAcademicAdapter("iitb", "IIT Bombay", page_url, {"acad.iitb.ac.in"})
    adapter.client = _FakeClient(page_url, (FIXTURES / "iitb-academic-notice.html").read_bytes())
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Circular body from the official academic office.")
    notices = adapter.fetch()

    assert len(notices) == 1
    assert notices[0].metadata["title"] == "Submission of Convocation Form for 64th Convocation."
    assert notices[0].source_url.endswith("64th-Convocation-Circular.pdf")
    assert "Circular body" in notices[0].text


@pytest.mark.parametrize(
    ("adapter_type", "slug", "host", "url"),
    [
        (VtuExaminationAdapter, "vtu", "vtu.ac.in", "https://vtu.ac.in/category/examination/"),
        (DuExaminationAdapter, "university-of-delhi", "exam.du.ac.in", "https://exam.du.ac.in/exam/index.php/notifications"),
    ],
)
def test_selected_university_catalog_adapters_extract_notices_and_pages(
    adapter_type, slug, host, url, monkeypatch
):
    import finalsay.adapters.live as live

    page_two = url + ("&page=2" if "?" in url else "?page=2")
    html_one = (
        "<table><tr><td>Revised Examination Schedule</td><td>Date: 01 November 2026</td>"
        f'<td><a href="/files/first.pdf">Revised Examination Schedule</a></td></tr></table>'
        f'<a href="{page_two}">2</a>'
    ).encode()
    html_two = (
        '<table><tr><td>Examination timetable</td>'
        '<td><a href="/files/second.pdf">Examination timetable</a></td></tr></table>'
    ).encode()

    class CatalogClient:
        def get(self, target, _limit, **_kwargs):
            if target == url:
                return target, {"Content-Type": "text/html"}, html_one
            if target == page_two:
                return target, {"Content-Type": "text/html"}, html_two
            return target, {"Content-Type": "application/pdf"}, b"fixture"

    adapter = adapter_type(slug, slug, url, {host, "www." + host})
    adapter.catalog_page_limit = 2
    adapter.client = CatalogClient()
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Official examination notice body.")

    notices = adapter.fetch()

    assert len(notices) == 2
    assert notices[0].institution_slug == slug
    assert notices[0].metadata["source_date"] == "01 November 2026"
    assert all(notice.source_url.endswith(".pdf") for notice in notices)


def test_delhi_backfill_fetches_five_bounded_pages_and_keeps_next_cursor():
    source_url = "https://exam.du.ac.in/exam/index.php/notifications"
    page_url = lambda offset: f"{source_url}?offset={offset}"

    def page_html(offset):
        next_link = (
            f'<a href="{page_url(offset + 20)}">Next</a>'
            if offset <= 100
            else ""
        )
        return f"<html>{next_link}</html>".encode()

    class OffsetClient:
        def __init__(self):
            self.calls = []

        def get(self, target, _limit, **_kwargs):
            self.calls.append(target)
            offset = int(target.rsplit("=", 1)[1])
            return target, {"Content-Type": "text/html"}, page_html(offset)

    adapter = DuExaminationAdapter(
        "university-of-delhi", "University of Delhi Examination", source_url,
        {"exam.du.ac.in"},
    )
    client = OffsetClient()
    adapter.client = client

    pages = adapter._catalog_urls(source_url, page_html(0))

    assert len(pages) == 6  # current plus five historical pages
    assert client.calls == [page_url(offset) for offset in (20, 40, 60, 80, 100)]
    assert adapter.backfill_next_cursor == page_url(120)
    assert adapter.backfill_complete is False
    assert adapter.notice_limit == 120


def test_delhi_sparse_pagination_advances_by_offset_without_skipping_to_last():
    source_url = "https://exam.du.ac.in/exam/notifications?offset=40"
    candidates = [
        "https://exam.du.ac.in/exam/notifications?offset=20",
        "https://exam.du.ac.in/exam/notifications?offset=40",
        "https://exam.du.ac.in/exam/notifications?offset=20",
        "https://exam.du.ac.in/exam/notifications?offset=420",
    ]
    adapter = DuExaminationAdapter(
        "university-of-delhi", "University of Delhi Examination",
        "https://exam.du.ac.in/exam/index.php/notifications", {"exam.du.ac.in"},
    )

    assert adapter._next_page(source_url, candidates) == (
        "https://exam.du.ac.in/exam/notifications?offset=60"
    )
    assert adapter._next_page(
        "https://exam.du.ac.in/exam/notifications?offset=400", candidates
    ) == "https://exam.du.ac.in/exam/notifications?offset=420"
    assert adapter._next_page(
        "https://exam.du.ac.in/exam/notifications?offset=420", candidates
    ) is None


def test_delhi_catalog_keeps_notice_rows_with_non_document_links():
    source_url = "https://exam.du.ac.in/exam/index.php/notifications"
    listing = (
        "<table>"
        '<tr><td>Notice dated 01 November 2026</td>'
        '<td><a href="/exam/notice/revised-exam-form">Revised examination form deadline</a></td></tr>'
        "</table>"
    ).encode()

    class DelhiCatalogClient:
        def get(self, target, _limit, **_kwargs):
            assert target == source_url
            return target, {"Content-Type": "text/html"}, listing

    adapter = DuExaminationAdapter(
        "university-of-delhi", "University of Delhi Examination", source_url,
        {"exam.du.ac.in"},
    )
    adapter.client = DelhiCatalogClient()

    notices = adapter.fetch()

    assert len(notices) == 1
    assert notices[0].source_url == "https://exam.du.ac.in/exam/notice/revised-exam-form"
    assert notices[0].metadata["title"] == "Revised examination form deadline"
    assert notices[0].metadata["extraction_quality"] == "listing_only"


def test_http_response_read_has_an_overall_time_limit():
    class EndlessResponse:
        headers = {}
        fp = None

        def read(self, size):
            return b"x" * size

    times = iter((0.0, 0.0, 46.0))
    with pytest.raises(SourceFetchError, match="45-second time limit"):
        _read_bounded_response(EndlessResponse(), 200_000, clock=lambda: next(times))


def test_http_response_rejects_oversized_content_length():
    class OversizedResponse:
        headers = {"Content-Length": "1001"}
        fp = None

        def read(self, _size):
            raise AssertionError("must reject size before reading the response")

    with pytest.raises(SourceFetchError, match="exceeded 1000 bytes"):
        _read_bounded_response(OversizedResponse(), 1000)


def test_vtu_comment_anchor_does_not_create_duplicate_notice(monkeypatch):
    import finalsay.adapters.live as live

    source_url = "https://vtu.ac.in/category/examination/"
    post_url = "https://vtu.ac.in/2026/11/41981/"
    listing = (
        '<article><a href="/2026/11/41981/">Revised exam timetable</a>'
        '<a href="/2026/11/41981/#respond">No Comment</a></article>'
    ).encode()
    detail = (
        '<ul class="post-attachments"><li><a href="/files/timetable.pdf">PDF</a></li></ul>'
    ).encode()

    class VtuClient:
        def get(self, target, _limit, **_kwargs):
            if target == source_url:
                return target, {"Content-Type": "text/html"}, listing
            if target == post_url:
                return target, {"Content-Type": "text/html"}, detail
            return target, {"Content-Type": "application/pdf"}, b"fixture"

    adapter = VtuExaminationAdapter("vtu", "VTU", source_url, {"vtu.ac.in"})
    adapter.client = VtuClient()
    adapter.backfill_complete = True
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Actual examination timetable text.")

    notices = adapter.fetch()

    assert len(notices) == 1
    assert notices[0].external_id == post_url
    assert notices[0].source_url == post_url


def test_catalog_parser_keeps_third_party_pdf_links_as_listing_metadata():
    parser = _CatalogRows()
    parser.feed(
        '<table><tr><td>Notice dated: 2 Nov 2026</td>'
        '<td><a href="https://drive.google.com/file/d/abc/view">PDF Download</a></td></tr></table>'
    )
    assert len(parser.items) == 1
    assert parser.items[0][0].startswith("https://drive.google.com/")


def test_dns_validation_times_out_without_blocking_scrape(monkeypatch):
    import finalsay.adapters.live as live

    release = Event()
    monkeypatch.setattr(live, "DNS_LOOKUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(live.socket, "getaddrinfo", lambda *_args, **_kwargs: release.wait())
    try:
        with pytest.raises(SourceFetchError, match="DNS lookup timed out"):
            live.validate_source_url("https://vtu.ac.in/category/examination/", {"vtu.ac.in"})
    finally:
        release.set()


def test_dns_validation_retries_temporary_resolution_errors(monkeypatch):
    import finalsay.adapters.live as live

    calls = []
    sleeps = []

    def resolve(host, port, *, type):
        calls.append((host, port, type))
        if len(calls) == 1:
            raise live.socket.gaierror(live.socket.EAI_AGAIN, "temporary DNS failure")
        return [(None, None, None, None, ("8.8.8.8", 443))]

    monkeypatch.setattr(live.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(live.time, "sleep", sleeps.append)

    assert (
        live.validate_source_url(
            "https://vtu.ac.in/category/examination/", {"vtu.ac.in"}
        )
        == "vtu.ac.in"
    )
    assert len(calls) == 2
    assert sleeps == [0.25]


def test_catalog_parser_captures_delhi_cards_and_offset_pagination():
    parser = _CatalogRows()
    parser.feed(
        '<a class="list-group-item list-group-item-action" '
        'href="https://drive.google.com/file/d/abc/view">'
        '<h6>STUDENT NOTIFICATION 2701-2800</h6><small>04 Nov 2026, 07:43 AM</small>'
        '<small class="badge">STUDENT</small></a>'
        '<a href="https://exam.du.ac.in/exam/notifications?offset=20" rel="next">Next</a>'
    )
    assert len(parser.items) == 1
    assert "2701-2800" in parser.items[0][1]
    assert parser.pages == ["https://exam.du.ac.in/exam/notifications?offset=20"]


def test_catalog_backfill_ignores_backward_numeric_pagination_links():
    adapter = DuExaminationAdapter(
        "university-of-delhi",
        "University of Delhi Examination",
        "https://exam.du.ac.in/exam/notifications",
        {"exam.du.ac.in"},
    )

    current = "https://exam.du.ac.in/exam/notifications?offset=400"
    assert adapter._next_page(
        current,
        [
            "https://exam.du.ac.in/exam/notifications?offset=380",
            "https://exam.du.ac.in/exam/notifications?offset=420",
        ],
    ) == "https://exam.du.ac.in/exam/notifications?offset=420"
    assert adapter._next_page(
        current,
        ["https://exam.du.ac.in/exam/notifications?offset=380"],
    ) is None


def test_catalog_parser_includes_machine_readable_publication_date():
    parser = _CatalogRows()
    parser.feed(
        '<article><a href="/2026/11/41981/">Examination notification</a>'
        '<time datetime="2026-11-06">Nov 6, 2026</time></article>'
    )

    assert len(parser.items) == 1
    assert _listing_date(parser.items[0][2]) == "2026-11-06"


def test_mumbai_parser_extracts_unique_code_title_publication_date_and_pdf():
    parser = _MumbaiCircularRows()
    parser.feed(
        '<table><tr><td>1</td><td>Department of Law</td>'
        '<td><div>Notice - Office Closure on Diwali</div></td><td>211633609200</td>'
        '<td>07/11/2026</td><td><a href="admin/upload/circular/123.pdf">View</a></td></tr></table>'
    )
    assert parser.items == [
        ("admin/upload/circular/123.pdf", "Notice - Office Closure on Diwali", "211633609200", "07/11/2026", "Department of Law")
    ]


def test_mumbai_adapter_extracts_pdf_and_preserves_circular_code(monkeypatch):
    import finalsay.adapters.live as live

    url = "https://mu.ac.in/circular.php"
    body = (
        '<table><tr><td>1</td><td>Department of Law</td>'
        '<td><div>Notice - Office Closure on Diwali</div></td><td>211633609200</td>'
        '<td>07/11/2026</td><td><a href="admin/upload/circular/123.pdf">View</a></td></tr></table>'
    ).encode()

    class MumbaiClient:
        def get(self, target, _limit, **_kwargs):
            if target == url:
                return target, {"Content-Type": "text/html"}, body
            return target, {"Content-Type": "application/pdf"}, b"fixture"

    adapter = MumbaiCircularAdapter("university-of-mumbai", "Mumbai University", url, {"mu.ac.in"})
    adapter.client = MumbaiClient()
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Examination closure notice content.")
    notices = adapter.fetch()
    assert len(notices) == 1
    assert notices[0].external_id == "mumbai:211633609200"
    assert notices[0].metadata["source_date"] == "07/11/2026"
    assert "Department of Law" in notices[0].text
    assert "Examination closure notice content." in notices[0].text


def test_mumbai_backfill_cursor_tracks_circular_code_when_new_rows_are_added(monkeypatch):
    import finalsay.adapters.live as live

    url = "https://mu.ac.in/circular.php"

    def register(codes):
        rows = []
        for index, code in enumerate(codes):
            rows.append(
                f'<tr><td>{index + 1}</td><td>Examinations</td>'
                f'<td>Notice {code}</td><td>{code}</td><td>07/11/2026</td>'
                f'<td><a href="admin/upload/circular/{code}.pdf">View</a></td></tr>'
            )
        return ("<table>" + "".join(rows) + "</table>").encode()

    codes = [f"code-{index}" for index in range(6)]

    class MutableMumbaiClient:
        body = register(codes)

        def get(self, target, _limit, **_kwargs):
            if target == url:
                return target, {"Content-Type": "text/html"}, self.body
            return target, {"Content-Type": "application/pdf"}, b"fixture"

    adapter = MumbaiCircularAdapter("university-of-mumbai", "Mumbai", url, {"mu.ac.in"})
    adapter.notice_limit = 2
    adapter.backfill_cursor = "2"  # persisted pre-fix row-offset checkpoint
    adapter.client = MutableMumbaiClient()
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Official circular text.")

    first_batch = adapter.fetch()
    assert adapter.backfill_next_cursor == "mumbai-code:code-3"
    assert {notice.external_id for notice in first_batch} == {
        "mumbai:code-0", "mumbai:code-1", "mumbai:code-2", "mumbai:code-3"
    }

    # A new circular at the front shifts every numeric row offset. The stable
    # cursor must still resume after code-3 and ingest code-4/code-5 next.
    adapter.backfill_cursor = adapter.backfill_next_cursor
    adapter.client.body = register(["new-code", *codes])
    second_batch = adapter.fetch()
    assert {notice.external_id for notice in second_batch} == {
        "mumbai:new-code", "mumbai:code-0", "mumbai:code-4", "mumbai:code-5"
    }
    assert adapter.backfill_complete is True
    assert adapter.backfill_next_cursor is None


def test_mumbai_missing_stable_backfill_cursor_does_not_skip_history(monkeypatch):
    import finalsay.adapters.live as live

    url = "https://mu.ac.in/circular.php"
    body = (
        '<table><tr><td>1</td><td>Examinations</td><td>Notice A</td>'
        '<td>code-a</td><td>07/11/2026</td><td><a href="a.pdf">PDF</a></td></tr>'
        '<tr><td>2</td><td>Examinations</td><td>Notice B</td>'
        '<td>code-b</td><td>07/11/2026</td><td><a href="b.pdf">PDF</a></td></tr></table>'
    ).encode()

    class MumbaiClient:
        def get(self, target, _limit, **_kwargs):
            return target, {"Content-Type": "text/html"}, body

    adapter = MumbaiCircularAdapter("university-of-mumbai", "Mumbai", url, {"mu.ac.in"})
    adapter.notice_limit = 1
    adapter.backfill_cursor = "mumbai-code:deleted-code"
    adapter.client = MumbaiClient()
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Official circular text.")

    notices = adapter.fetch()

    assert len(notices) == 1  # current row only; no guessed historical offset
    assert adapter.backfill_complete is False
    assert adapter.backfill_next_cursor == "mumbai-code:deleted-code"
    assert any("no longer in the source listing" in error for error in adapter.errors)


def test_mumbai_adapter_ocr_images_and_skips_suspicious_uploads(monkeypatch):
    import finalsay.adapters.live as live

    url = "https://mu.ac.in/circular.php"
    body = (
        "<table>"
        '<tr><td>1</td><td>Examination</td><td>End semester timetable</td>'
        "<td>211633609200</td><td>07/11/2026</td>"
        '<td><a href="admin/upload/circular/notice.pdf">View</a></td></tr>'
        '<tr><td>2</td><td>Examination</td><td>zocext_zocext_phtml_phtml</td>'
        "<td>822714377999</td><td>29/10/2026</td>"
        '<td><a href="admin/upload/circular/38031zocext_phtml.phtml">View</a></td></tr>'
        '<tr><td>3</td><td>Examination</td><td>Selection Letter - West Zone Inter-University Kabaddi</td>'
        "<td>822714377998</td><td>29/10/2026</td>"
        '<td><a href="admin/upload/circular/selection.jpg">View</a></td></tr>'
        '<tr><td>4</td><td>Examination</td><td>txt9f2c_yjpg</td>'
        "<td>822714377997</td><td>29/10/2026</td>"
        '<td><a href="admin/upload/circular/31196t9f2c_y.jpg">View</a></td></tr>'
        "</table>"
    ).encode()

    class MumbaiClient:
        def get(self, target, _limit, **_kwargs):
            if target == url:
                return target, {"Content-Type": "text/html"}, body
            if target.endswith(".jpg"):
                return target, {"Content-Type": "image/jpeg"}, b"fixture-image"
            return target, {"Content-Type": "application/pdf"}, b"fixture"

    adapter = MumbaiCircularAdapter("university-of-mumbai", "Mumbai University", url, {"mu.ac.in"})
    adapter.client = MumbaiClient()
    monkeypatch.setattr(live, "_pdf_text", lambda _data: "Official examination notice text.")
    monkeypatch.setattr(
        "finalsay.services.extraction.text_from_image",
        lambda _data, *, timeout=None: "OCR text from official selection letter.",
    )

    notices = adapter.fetch()

    assert len(notices) == 2
    assert any(notice.source_url.endswith("notice.pdf") for notice in notices)
    image_notice = next(notice for notice in notices if notice.source_url.endswith("selection.jpg"))
    assert "OCR text from official selection letter" in image_notice.text
    assert any("skipped unsupported or suspicious Mumbai attachment" in error for error in adapter.errors)


def test_document_fetch_error_log_includes_attachment_url():
    url = "https://mu.ac.in/admin/upload/circular/large-notice.pdf"
    adapter = MumbaiCircularAdapter(
        "university-of-mumbai", "Mumbai University", "https://mu.ac.in/circular.php", {"mu.ac.in"}
    )

    class FailedClient:
        def get(self, _target, _limit, **_kwargs):
            raise SourceFetchError("response exceeded 20000000 bytes")

    adapter.client = FailedClient()

    assert adapter._document(url, "Large official circular") is None
    assert url in adapter.errors[0]
    assert "response exceeded" in adapter.errors[0]


def test_vtu_adapter_follows_post_and_extracts_only_its_attachments(monkeypatch):
    import finalsay.adapters.live as live

    listing_url = "https://vtu.ac.in/category/examination/"
    post_url = "https://vtu.ac.in/2026/11/41981/"
    pdf_url = "https://vtu.ac.in/wp-content/uploads/2026/11/notice.pdf"
    listing = (
        '<article><div class="entry-day">06</div><div class="entry-month">Nov 2026</div>'
        f'<h2><a href="{post_url}">Examination Schedule Revised</a></h2></article>'
    ).encode()
    detail = (
        '<ul class="post-attachments"><li><a href="/wp-content/uploads/2026/11/notice.pdf"></a>'
        '<a href="/wp-content/uploads/2026/11/notice.pdf">Revised examination schedule</a></li></ul>'
        '<a href="/wp-content/uploads/2020/10/vtu_logo.pdf">site menu decoy</a>'
    ).encode()

    class VtuClient:
        def get(self, url, _limit, **_kwargs):
            if url == listing_url:
                return url, {"Content-Type": "text/html"}, listing
            if url == post_url:
                return url, {"Content-Type": "text/html"}, detail
            return url, {"Content-Type": "application/pdf"}, b"%PDF-fake"

    adapter = VtuExaminationAdapter("vtu", "VTU", listing_url, {"vtu.ac.in", "www.vtu.ac.in"})
    adapter.client = VtuClient()
    downloaded = []

    def fake_document(url, title, date=None, external_id=None):
        downloaded.append((url, title, date, external_id))
        return RawNotice(
            text="Official extracted examination timetable PDF content.",
            source_url=url,
            institution_slug="vtu",
            external_id=external_id,
            metadata={"title": title, "source_date": date},
        )

    monkeypatch.setattr(adapter, "_document", fake_document)
    notices = adapter.fetch()
    assert len(notices) == 1
    assert notices[0].source_url == post_url
    assert notices[0].metadata["source_date"] == "06 Nov 2026"
    assert "Official extracted examination timetable PDF content." in notices[0].text
    assert downloaded == [(pdf_url, "Revised examination schedule", "06 Nov 2026", post_url)]


def test_scrape_url_allowlist_rejects_unapproved_hosts_and_non_https():
    with pytest.raises(SourceFetchError):
        validate_source_url("https://127.0.0.1/admin", {"www.thapar.edu"})
    with pytest.raises(SourceFetchError):
        validate_source_url("http://www.thapar.edu/notices", {"www.thapar.edu"})


def test_fixture_scraper_type_is_not_available_for_live_sources():
    from finalsay.adapters.live import validate_scrape_config

    with pytest.raises(SourceFetchError, match="unsupported scraper type"):
        validate_scrape_config("fixture", None, resolve_host=False)


def test_public_host_validation_rejects_private_dns(monkeypatch):
    import finalsay.adapters.live as live

    monkeypatch.setattr(
        live.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(SourceFetchError, match="public IP"):
        validate_source_url("https://www.thapar.edu/notices", {"www.thapar.edu"})


def test_html_404_page_at_robots_path_is_not_parsed_as_robot_rules(monkeypatch):
    client = PublicSiteClient({"www.nitj.ac.in"})
    monkeypatch.setattr(
        client,
        "_single_get",
        lambda *_args, **_kwargs: (200, {"Content-Type": "text/plain"}, b"<!doctype html><html>not found</html>"),
    )
    assert client._robots_allows("https://www.nitj.ac.in/notices", "www.nitj.ac.in") is True


def test_canonical_robots_redirect_to_site_home_is_treated_as_no_policy(monkeypatch):
    client = PublicSiteClient({"www.nitj.ac.in"})
    monkeypatch.setattr(
        client,
        "_single_get",
        lambda *_args, **_kwargs: (301, {"Location": "https://nitj.ac.in/"}, b""),
    )
    assert client._robots_allows("https://www.nitj.ac.in/notices", "www.nitj.ac.in") is True


def test_public_client_retries_transient_status_then_returns_success(monkeypatch):
    client = PublicSiteClient({"www.thapar.edu"})
    responses = [
        (503, {"Retry-After": "0"}, b"temporarily unavailable"),
        (200, {"Content-Type": "text/html"}, b"<html>notices</html>"),
    ]
    calls = []
    monkeypatch.setattr(client, "_single_get", lambda url, limit: (calls.append(url), *responses.pop(0))[1:])
    monkeypatch.setattr(client, "_wait_for_host", lambda _host: None)
    monkeypatch.setattr("finalsay.adapters.live.time.sleep", lambda _delay: None)

    status, _headers, body = client._get_with_retries(
        "https://www.thapar.edu/notices", 1000, "www.thapar.edu"
    )
    assert status == 200
    assert body == b"<html>notices</html>"
    assert len(calls) == 2


def test_public_client_stops_after_bounded_transient_failures(monkeypatch):
    client = PublicSiteClient({"www.thapar.edu"})
    calls = []
    monkeypatch.setattr(
        client,
        "_single_get",
        lambda *_args: (calls.append(1), (503, {}, b"busy"))[1],
    )
    monkeypatch.setattr(client, "_wait_for_host", lambda _host: None)
    monkeypatch.setattr("finalsay.adapters.live.time.sleep", lambda _delay: None)

    status, _headers, _body = client._get_with_retries(
        "https://www.thapar.edu/notices", 1000, "www.thapar.edu"
    )
    assert status == 503
    assert len(calls) == 3
