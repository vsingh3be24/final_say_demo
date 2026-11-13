"""Synthetic adapters used only by isolated tests and seed data.

This module and its fictional source classes are excluded from the production
container. Live ingestion imports them only when ``include_fixtures=True``.
"""

from __future__ import annotations

import json
import os

from finalsay.adapters.base import InstitutionAdapter, RawNotice

_FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seed", "fixtures")


class FixtureAdapter(InstitutionAdapter):
    """Load one synthetic source fixture for isolated tests or seed data."""

    def fetch(self) -> list[RawNotice]:
        path = os.path.join(_FIXTURES_DIR, f"{self.slug}_official.json")
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as handle:
            records = json.load(handle)

        notices: list[RawNotice] = []
        for record in records:
            external_id = record.get("external_id")
            source_url = record.get("source_url") or (
                f"{self.base_url.rstrip('/')}/notices/{external_id or ''}"
            )
            notices.append(
                RawNotice(
                    text=record["text"],
                    source_url=source_url,
                    institution_slug=self.slug,
                    external_id=external_id,
                    metadata={
                        key: value
                        for key, value in record.items()
                        if key not in {"text", "source_url", "external_id"}
                    },
                )
            )
        return notices


def get_fixture_adapters() -> list[InstitutionAdapter]:
    """Return fictional source adapters for isolated tests and seed data."""
    from finalsay.adapters.inst_northgate import NorthgateAdapter
    from finalsay.adapters.inst_riverside import RiversideAdapter
    from finalsay.adapters.inst_summit import SummitAdapter

    return [NorthgateAdapter(), RiversideAdapter(), SummitAdapter()]
