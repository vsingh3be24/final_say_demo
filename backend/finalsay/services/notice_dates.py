"""Conservative parsing for official notice publication dates.

Portal dates are stored in their original display form for evidence. This
module produces a normalized date only when the complete value is a supported
date format; it deliberately does not search notice text for a plausible event
date or use the retrieval timestamp as a publication date.
"""

from __future__ import annotations

import re
from datetime import date, datetime


_FORMATS = (
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b. %d, %Y",
    "%B %d, %Y",
)
_DATE_TIME_SUFFIX = re.compile(r"\s+(?:\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]M)?|\d{1,2}\s+[AP]M)$", re.I)
_LABEL_PREFIX = re.compile(r"^(?:published(?:\s+date)?|publication\s+date|date|dated)\s*[:\-]\s*", re.I)


def parse_publication_date(value: str | date | datetime | None) -> date | None:
    """Parse a complete, conventional date string without guessing from prose."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    candidate = " ".join(str(value).strip().split())
    candidate = _LABEL_PREFIX.sub("", candidate).strip().rstrip(".,")
    candidate = _DATE_TIME_SUFFIX.sub("", candidate).strip().rstrip(".,")
    if not candidate:
        return None

    for fmt in _FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None
