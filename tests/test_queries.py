"""La query de ADS es la definicion operativa del estudio: se prueba literal."""

from __future__ import annotations

from astroca.ads.queries import QueryBuilder


def test_clausulas_base(search_config):
    q = QueryBuilder(config=search_config).base_clauses()
    assert "database:astronomy" in q
    assert "property:refereed" in q
    assert "year:1950-2025" in q
    assert "author_count:[1 TO 10]" in q


def test_sin_keywords_no_agrega_clausula(search_config):
    builder = QueryBuilder(config=search_config)
    assert not any("abs:" in c for c in builder.base_clauses())


def test_keywords_se_agregan(search_config):
    search_config.field.keywords = ["herbig-haro", "molecular outflows"]
    builder = QueryBuilder(config=search_config)
    clausula = next(c for c in builder.base_clauses() if c.startswith("abs:"))
    assert '"herbig-haro"' in clausula
    assert '"molecular outflows"' in clausula
    assert " OR " in clausula


def test_refereed_opcional(search_config):
    search_config.field.refereed_only = False
    assert "property:refereed" not in QueryBuilder(config=search_config).base_clauses()


def test_max_authors_nulo_quita_el_corte(search_config):
    search_config.authors.max_authors = None
    assert not any("author_count" in c for c in QueryBuilder(config=search_config).base_clauses())


def test_query_por_pais_incluye_instituciones(search_config, guatemala):
    builder = QueryBuilder(
        config=search_config,
        institutions={"GTM": ["Universidad de San Carlos"]},
    )
    query = builder.for_country(guatemala)
    assert 'aff:(' in query.q
    assert '"Guatemala"' in query.q
    assert '"Universidad de San Carlos"' in query.q
    assert query.label == "GTM"


def test_cache_key_cambia_con_los_campos(search_config, guatemala):
    builder = QueryBuilder(config=search_config)
    antes = builder.for_country(guatemala).cache_key

    search_config.extraction.fields = ["bibcode", "aff", "citation_count"]
    despues = QueryBuilder(config=search_config).for_country(guatemala).cache_key

    assert antes != despues, "cambiar los campos pedidos debe invalidar la cache"
