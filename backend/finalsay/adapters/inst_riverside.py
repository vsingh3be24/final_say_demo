"""Riverside Institute adapter (fixtures)."""

from __future__ import annotations

from finalsay.adapters.fixture_sources import FixtureAdapter


class RiversideAdapter(FixtureAdapter):
    slug = "riverside"
    name = "Riverside Institute"
    base_url = "https://notices.riverside.edu"
