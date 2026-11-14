from datetime import date, datetime, timezone

import pytest

from finalsay.services.notice_dates import parse_publication_date


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-01", date(2026, 11, 1)),
        ("01 Nov 2026", date(2026, 11, 1)),
        ("10 November 2026", date(2026, 11, 10)),
        ("01/11/2026", date(2026, 11, 1)),
        ("Dated: 01.11.2026", date(2026, 11, 1)),
        ("Nov 1, 2026 10:30 AM", date(2026, 11, 1)),
    ],
)
def test_parse_publication_date_supported_full_dates(value, expected):
    assert parse_publication_date(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "Examination will begin on 15 December 2026",
        "November 2026",
        "01/13/2026",
    ],
)
def test_parse_publication_date_does_not_guess_from_text_or_partial_dates(value):
    assert parse_publication_date(value) is None


def test_parse_publication_date_accepts_date_objects():
    expected = date(2026, 11, 1)
    assert parse_publication_date(expected) == expected
    assert parse_publication_date(datetime(2026, 11, 1, 22, tzinfo=timezone.utc)) == expected
