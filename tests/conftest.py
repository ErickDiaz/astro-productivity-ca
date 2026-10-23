from __future__ import annotations

import pytest

from astroca.config import Country, SearchConfig


@pytest.fixture
def guatemala() -> Country:
    return Country(
        iso3="GTM",
        name="Guatemala",
        name_en="Guatemala",
        region="centroamerica",
        tld=".gt",
        aff_patterns=["guatemala", "guatemalan"],
        cities=["guatemala city"],
    )


@pytest.fixture
def costa_rica() -> Country:
    return Country(
        iso3="CRI",
        name="Costa Rica",
        name_en="Costa Rica",
        region="centroamerica",
        tld=".cr",
        aff_patterns=["costa rica", "costarricense"],
        cities=["san jose, costa rica"],
    )


@pytest.fixture
def paises(guatemala, costa_rica):
    return [guatemala, costa_rica]


@pytest.fixture
def search_config() -> SearchConfig:
    return SearchConfig(
        **{
            "field": {"database": "astronomy", "refereed_only": True, "keywords": []},
            "period": {"start_year": 1950, "end_year": 2025},
            "authors": {"max_authors": 10},
            "extraction": {"rows_per_page": 200, "fields": ["bibcode", "aff"]},
        }
    )
