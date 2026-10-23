"""Construccion de queries para el endpoint de busqueda de ADS.

Toda la sintaxis de ADS vive aqui. El resto del modulo trabaja con objetos
``SearchQuery`` y no necesita saber como se escribe una query.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional

from astroca.config import Country, SearchConfig


@dataclass(frozen=True)
class SearchQuery:
    """Una busqueda concreta, lista para enviarse a ADS."""

    q: str
    fl: List[str]
    rows: int = 200

    #: ADS exige que el `sort` incluya `id` como desempate al paginar con
    #: cursorMark; sin el, la API responde 400. `bibcode` no sirve: la clave
    #: unica del indice es `id`.
    sort: str = "date asc,id asc"
    label: str = ""
    max_records: Optional[int] = None

    def as_params(self) -> dict:
        return {"q": self.q, "fl": ",".join(self.fl), "rows": self.rows, "sort": self.sort}

    @property
    def cache_key(self) -> str:
        """Huella estable de la query.

        Incluye los campos pedidos: si cambian, la cache queda invalidada,
        que es justo lo que se quiere.
        """
        payload = json.dumps(
            {"q": self.q, "fl": sorted(self.fl), "sort": self.sort, "max": self.max_records},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class QueryBuilder:
    """Arma queries de ADS a partir de ``config/search.yml``.

    La query final tiene la forma::

        database:astronomy AND property:refereed AND year:1950-2025
        AND author_count:[1 TO 10] AND abs:("..." OR "...")
        AND aff:("Guatemala" OR "Guatemala City" OR "Universidad de San Carlos")
    """

    config: SearchConfig
    institutions: dict = field(default_factory=dict)

    # -- clausulas comunes -------------------------------------------------- #
    def base_clauses(self) -> List[str]:
        """Filtros que comparten todas las busquedas del estudio."""
        campo = self.config.field
        clausulas = [f"database:{campo.database}"]

        if campo.refereed_only:
            clausulas.append("property:refereed")

        periodo = self.config.period
        clausulas.append(f"year:{periodo.start_year}-{periodo.end_year}")

        tope = self.config.authors.max_authors
        if tope is not None:
            clausulas.append(f"author_count:[1 TO {tope}]")

        clausula_kw = self._keyword_clause()
        if clausula_kw:
            clausulas.append(clausula_kw)

        return clausulas

    def _keyword_clause(self) -> Optional[str]:
        """Keywords de ``search.yml``, vacio = todo el campo."""
        campo = self.config.field
        if not campo.keywords:
            return None

        terminos = " OR ".join(_quote(k) for k in campo.keywords)
        por_campo = [f"{nombre}:({terminos})" for nombre in campo.keyword_fields]
        union = f" {campo.keyword_logic} ".join(por_campo)
        return union if len(por_campo) == 1 else f"({union})"

    # -- queries concretas -------------------------------------------------- #
    def for_country(self, country: Country) -> SearchQuery:
        """Publicaciones con al menos una afiliacion en ``country``.

        Busca por nombre de pais, ciudades y las instituciones semilla, porque
        muchas afiliaciones centroamericanas no nombran al pais.
        """
        terminos = list(country.search_terms) + list(self.institutions.get(country.iso3, []))
        clausula_aff = " OR ".join(_quote(t) for t in terminos)

        clausulas = self.base_clauses() + [f"aff:({clausula_aff})"]
        return SearchQuery(
            q=" AND ".join(clausulas),
            fl=self.config.extraction.fields,
            rows=self.config.extraction.rows_per_page,
            label=country.iso3,
            max_records=self.config.extraction.max_records_per_country,
        )

    def for_world_totals(self, year: int) -> SearchQuery:
        """Total mundial de un anio, para la serie de produccion relativa."""
        clausulas = self.base_clauses()
        clausulas = [c for c in clausulas if not c.startswith("year:")]
        clausulas.append(f"year:{year}")
        return SearchQuery(
            q=" AND ".join(clausulas),
            fl=["bibcode"],
            rows=1,
            label=f"mundo-{year}",
        )


def _quote(termino: str) -> str:
    """Entrecomilla un termino para ADS, escapando comillas internas."""
    return '"{}"'.format(termino.replace('"', '\\"'))
