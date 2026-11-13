from finalsay.services.backfill_vtu_publication_dates import date_from_official_listing


def test_publication_date_backfill_reads_only_date_at_official_listing_prefix():
    text = (
        "Issued by: VTU\nSubject: Examination scheduled for 12 Dec 2026\n"
        "Official listing: 01 Nov 2026 CIRCULAR – Revised examination schedule"
    )

    assert date_from_official_listing(text) == "01 Nov 2026"


def test_publication_date_backfill_does_not_guess_from_event_dates():
    text = "Subject: Examination scheduled for 12 Dec 2026\nNo dated official listing."

    assert date_from_official_listing(text) is None


def test_publication_date_backfill_returns_none_for_listing_without_date():
    text = "Official listing: Revised examination schedule — notice from the Registrar"

    assert date_from_official_listing(text) is None
