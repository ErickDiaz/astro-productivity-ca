"""Extraccion de publicaciones de NASA ADS, pais por pais."""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Dict, List

import pandas as pd

from astroca.ads.client import ADSClient
from astroca.ads.queries import QueryBuilder
from astroca.config import Country
from astroca.extract.base import Extractor
from astroca.storage import DataStore

logger = logging.getLogger(__name__)


class PublicationExtractor(Extractor):
    """Descarga las publicaciones con afiliacion en los paises del estudio.

    Se consulta un pais a la vez porque ADS limita el tamano de la query y
    porque asi se sabe que termino de busqueda trajo cada registro, dato que
    la fase de transformacion usa como pista para resolver el pais.

    Una publicacion puede aparecer en varias busquedas (coautoria entre paises
    de la region). Se deduplica por ``bibcode`` y se conserva la lista de
    busquedas que la trajeron en ``query_countries``.
    """

    name = "publications"

    def __init__(
        self,
        store: DataStore,
        client: ADSClient,
        builder: QueryBuilder,
        countries: List[Country],
    ) -> None:
        super().__init__(store)
        self.client = client
        self.builder = builder
        self.countries = countries

    # -- pasos de la plantilla --------------------------------------------- #
    def fetch(self) -> List[dict]:
        por_bibcode: Dict[str, dict] = {}
        total_paises = len(self.countries)
        inicio = time.monotonic()
        sin_bibcode = 0

        logger.info("=" * 70)
        logger.info("EXTRACCION: %d paises en scope", total_paises)
        logger.info("=" * 70)

        for indice, pais in enumerate(self.countries, start=1):
            query = self.builder.for_country(pais)
            logger.info("")
            logger.info("--- [%d/%d] %s (%s) ---", indice, total_paises, pais.name, pais.iso3)

            docs = self.client.search(query)

            nuevos = 0
            repetidos = 0
            for doc in docs:
                bibcode = doc.get("bibcode")
                if not bibcode:
                    sin_bibcode += 1
                    continue
                if bibcode in por_bibcode:
                    por_bibcode[bibcode]["query_countries"].append(pais.iso3)
                    repetidos += 1
                else:
                    registro = dict(doc)
                    registro["query_countries"] = [pais.iso3]
                    por_bibcode[bibcode] = registro
                    nuevos += 1

            logger.info(
                "[%s] %d docs: %d nuevos, %d ya vistos (coautoria regional)",
                pais.iso3, len(docs), nuevos, repetidos,
            )
            logger.info(
                "[%s] acumulado: %d publicaciones unicas | %s",
                pais.iso3, len(por_bibcode), self.client.rate_limit,
            )

        transcurrido = time.monotonic() - inicio
        logger.info("")
        logger.info("=" * 70)
        logger.info("EXTRACCION TERMINADA en %.1fs", transcurrido)
        logger.info("  publicaciones unicas: %d", len(por_bibcode))
        if sin_bibcode:
            logger.warning("  registros descartados por no traer bibcode: %d", sin_bibcode)
        self._log_resumen_por_pais(por_bibcode)
        logger.info("=" * 70)

        return list(por_bibcode.values())

    @staticmethod
    def _log_resumen_por_pais(por_bibcode: Dict[str, dict]) -> None:
        """Cuantas publicaciones trajo la busqueda de cada pais."""
        conteo: Dict[str, int] = {}
        compartidas = 0
        for registro in por_bibcode.values():
            paises = registro["query_countries"]
            if len(paises) > 1:
                compartidas += 1
            for iso3 in paises:
                conteo[iso3] = conteo.get(iso3, 0) + 1

        logger.info("  publicaciones con mas de un pais en la busqueda: %d", compartidas)
        for iso3, n in sorted(conteo.items(), key=lambda par: par[1], reverse=True):
            logger.info("    %s: %d", iso3, n)

    def to_frame(self, records: List[dict]) -> pd.DataFrame:
        logger.info("Tabulando %d registros...", len(records))
        columnas = list(self.builder.config.extraction.fields) + ["query_countries"]
        df = pd.DataFrame(records)

        faltantes = [c for c in columnas if c not in df.columns]
        if faltantes:
            logger.warning("ADS no devolvio estos campos: %s", ", ".join(faltantes))

        # Una columna por campo pedido, aunque ADS no la haya devuelto nunca.
        for columna in columnas:
            if columna not in df.columns:
                df[columna] = None
        df = df[columnas]

        # `title` llega como lista de un elemento; aplanarla simplifica todo
        # el analisis posterior.
        if "title" in df.columns:
            df["title"] = df["title"].apply(_primer_elemento)

        if "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

        df["extraction_date"] = date.today().isoformat()

        if "year" in df.columns and df["year"].notna().any():
            logger.info("  rango de anios: %s-%s", int(df["year"].min()), int(df["year"].max()))
            sin_anio = int(df["year"].isna().sum())
            if sin_anio:
                logger.warning("  publicaciones sin anio: %d", sin_anio)
        if "citation_count" in df.columns:
            citas = pd.to_numeric(df["citation_count"], errors="coerce")
            logger.info("  citas totales: %s", int(citas.fillna(0).sum()))

        return df.sort_values("bibcode", ignore_index=True)


def _primer_elemento(valor):
    if isinstance(valor, (list, tuple)):
        return valor[0] if valor else None
    return valor
