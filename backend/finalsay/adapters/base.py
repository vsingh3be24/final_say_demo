"""Common adapter types for live and test-only notice sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RawNotice:
    """A raw (un-extracted) notice as returned by an adapter.

    ``text`` is the raw notice body (before redaction); ``source_url`` records
    where the notice was fetched from. Extraction/redaction runs downstream in
    the ingestion service, so the raw text is never persisted directly.
    """

    text: str
    source_url: str
    institution_slug: str
    external_id: str | None = None
    metadata: dict = field(default_factory=dict)


class InstitutionAdapter(ABC):
    """Interface for fetching an institution's official notices."""

    slug: str = "abstract"
    name: str = "Abstract Institution"
    base_url: str = "https://example.edu"

    @abstractmethod
    def fetch(self) -> list[RawNotice]:
        """Return the institution's current official notices as raw notices."""
        raise NotImplementedError


