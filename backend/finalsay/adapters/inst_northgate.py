"""Northgate University adapter (fixtures)."""

from __future__ import annotations

from finalsay.adapters.fixture_sources import FixtureAdapter


class NorthgateAdapter(FixtureAdapter):
    slug = "northgate"
    name = "Northgate University"
    base_url = "https://notices.northgate.edu"
