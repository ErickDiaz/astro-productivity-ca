"""Resolucion de afiliacion -> pais.

Es la pieza de la que depende la credibilidad de todo el estudio: si una
afiliacion se asigna al pais equivocado, todas las metricas heredan el error.

Se aplica una cascada de estrategias ordenadas de mayor a menor confianza. La
primera que responde gana, y se registra cual fue, para poder auditar despues
que proporcion de los datos se resolvio por que via.

    1. CanonicalIdStrategy  identificadores curados de ADS (``aff_id``)
    2. InstitutionStrategy  instituciones semilla de ``config/institutions.yml``
    3. CountryNameStrategy  nombre del pais o gentilicio en el texto
    4. CityStrategy         ciudades conocidas
    5. EmailDomainStrategy  dominio de correo (.gt, .hn, .cr, ...)

Lo que ninguna resuelve queda con ``iso3 = None`` y se revisa a mano en el
notebook ``01_cobertura_y_afiliaciones``.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import pandas as pd

from astroca.config import Country
from astroca.storage import DataStore
from astroca.transform.base import Transformer

logger = logging.getLogger(__name__)

#: ADS usa este marcador cuando no hay afiliacion para un autor.
SIN_AFILIACION = "-"


def normalizar(texto: str) -> str:
    """Minusculas, sin acentos y con espacios colapsados.

    Permite que "Panamá", "PANAMA" y "Panama" se comparen igual.
    """
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos.lower()).strip()


@dataclass(frozen=True)
class Resolution:
    """Resultado de resolver una afiliacion."""

    iso3: Optional[str]
    strategy: Optional[str] = None
    confidence: float = 0.0

    @property
    def resolved(self) -> bool:
        return self.iso3 is not None


#: Lo que se devuelve cuando ninguna estrategia reconoce la afiliacion.
NO_RESUELTO = Resolution(iso3=None)


# --------------------------------------------------------------------------- #
#  Estrategias
# --------------------------------------------------------------------------- #
class ResolutionStrategy(ABC):
    """Una forma de deducir el pais de una afiliacion."""

    #: Etiqueta con la que se audita la estrategia en la tabla de salida.
    name: str = ""

    #: Confianza nominal, usada para ordenar la cascada y para filtrar.
    confidence: float = 0.0

    @abstractmethod
    def resolve(self, aff_text: str, aff_id: Optional[str] = None) -> Optional[str]:
        """Devuelve el ISO3 del pais, o ``None`` si no reconoce la afiliacion."""


class CanonicalIdStrategy(ResolutionStrategy):
    """Usa los identificadores curados de ADS (``aff_id``).

    Es la senal mas confiable porque no depende de como el editor escribio la
    afiliacion. Requiere un mapa ``aff_id -> iso3``, que se construye en el
    notebook de validacion y se guarda en ``config/aff_ids.yml``.
    """

    name = "aff_id"
    confidence = 0.99

    def __init__(self, mapping: Optional[Dict[str, str]] = None) -> None:
        self.mapping = mapping or {}

    def resolve(self, aff_text: str, aff_id: Optional[str] = None) -> Optional[str]:
        if not aff_id:
            return None
        return self.mapping.get(str(aff_id).strip())


class _PatronesPorPaisStrategy(ResolutionStrategy):
    """Base para las estrategias que buscan literales en el texto.

    Ordena los patrones de mas largo a mas corto para que el mas especifico
    gane: "saint augustine, trinidad" antes que "trinidad".
    """

    def __init__(self, countries: Sequence[Country]) -> None:
        patrones: List[tuple] = []
        for pais in countries:
            for patron in self._patrones_de(pais):
                normalizado = normalizar(patron)
                if normalizado:
                    patrones.append((normalizado, pais.iso3))
        self._patrones = sorted(patrones, key=lambda par: len(par[0]), reverse=True)

    @abstractmethod
    def _patrones_de(self, country: Country) -> Sequence[str]:
        """Literales que identifican a ``country``."""

    def resolve(self, aff_text: str, aff_id: Optional[str] = None) -> Optional[str]:
        texto = normalizar(aff_text)
        if not texto:
            return None
        for patron, iso3 in self._patrones:
            if patron in texto:
                return iso3
        return None


class CountryNameStrategy(_PatronesPorPaisStrategy):
    """Busca el nombre del pais o su gentilicio."""

    name = "country_name"
    confidence = 0.9

    def _patrones_de(self, country: Country) -> Sequence[str]:
        return [country.name, country.name_en, *country.aff_patterns]


class CityStrategy(_PatronesPorPaisStrategy):
    """Busca ciudades conocidas.

    Solo se listan ciudades poco ambiguas en ``config/countries.yml``: por eso
    "San Jose" aparece siempre calificado con el pais.
    """

    name = "city"
    confidence = 0.7

    def _patrones_de(self, country: Country) -> Sequence[str]:
        return country.cities


class InstitutionStrategy(ResolutionStrategy):
    """Busca instituciones semilla de ``config/institutions.yml``."""

    name = "institution"
    confidence = 0.95

    def __init__(self, institutions: Sequence[tuple]) -> None:
        patrones = [(normalizar(nombre), iso3) for nombre, iso3 in institutions]
        self._patrones = sorted(
            (par for par in patrones if par[0]), key=lambda par: len(par[0]), reverse=True
        )

    def resolve(self, aff_text: str, aff_id: Optional[str] = None) -> Optional[str]:
        texto = normalizar(aff_text)
        if not texto:
            return None
        for patron, iso3 in self._patrones:
            if patron in texto:
                return iso3
        return None


class EmailDomainStrategy(ResolutionStrategy):
    """Usa el dominio de nivel superior del correo en la afiliacion.

    Ultimo recurso: un correo ``.gt`` es buena pista del pais, pero un
    investigador puede conservar un correo institucional tras mudarse.
    """

    name = "email_tld"
    confidence = 0.6

    _CORREO = re.compile(r"[\w.+-]+@([\w.-]+)")

    def __init__(self, countries: Sequence[Country]) -> None:
        self._por_tld = {normalizar(p.tld): p.iso3 for p in countries if p.tld}

    def resolve(self, aff_text: str, aff_id: Optional[str] = None) -> Optional[str]:
        texto = normalizar(aff_text)
        for dominio in self._CORREO.findall(texto):
            for tld, iso3 in self._por_tld.items():
                if dominio.endswith(tld):
                    return iso3
        return None


# --------------------------------------------------------------------------- #
#  Resolvedor
# --------------------------------------------------------------------------- #
class AffiliationResolver:
    """Aplica la cascada de estrategias sobre una afiliacion."""

    def __init__(self, strategies: Sequence[ResolutionStrategy]) -> None:
        self.strategies = sorted(strategies, key=lambda e: e.confidence, reverse=True)
        self._cache: Dict[tuple, Resolution] = {}

    @classmethod
    def from_config(
        cls,
        countries: Sequence[Country],
        institutions: Sequence[tuple],
        aff_id_mapping: Optional[Dict[str, str]] = None,
    ) -> "AffiliationResolver":
        """Arma la cascada por defecto a partir de la configuracion."""
        return cls(
            [
                CanonicalIdStrategy(aff_id_mapping),
                InstitutionStrategy(institutions),
                CountryNameStrategy(countries),
                CityStrategy(countries),
                EmailDomainStrategy(countries),
            ]
        )

    def resolve(self, aff_text: str, aff_id: Optional[str] = None) -> Resolution:
        """Primera estrategia que reconoce la afiliacion.

        Las afiliaciones se repiten muchisimo entre publicaciones de una misma
        institucion, asi que el resultado se memoiza.
        """
        if not aff_text or aff_text == SIN_AFILIACION:
            return NO_RESUELTO

        clave = (aff_text, aff_id)
        if clave in self._cache:
            return self._cache[clave]

        resultado = NO_RESUELTO
        for estrategia in self.strategies:
            iso3 = estrategia.resolve(aff_text, aff_id)
            if iso3:
                resultado = Resolution(iso3, estrategia.name, estrategia.confidence)
                break

        self._cache[clave] = resultado
        return resultado


class ForeignAffiliationDetector:
    """Reconoce afiliaciones de fuera de la region.

    Existe solo para que el reporte de calidad sea interpretable. Una
    afiliacion de Oxford no es un fallo del mapeo: es un coautor
    internacional, que es justamente lo que el estudio quiere medir. Mezclarla
    con las afiliaciones que no se pudieron clasificar hunde artificialmente
    la cobertura y oculta la lista de trabajo real.
    """

    def __init__(self, markers: Sequence[str]) -> None:
        self._markers = [normalizar(m) for m in markers if normalizar(m)]

    def is_foreign(self, aff_text: str) -> bool:
        texto = normalizar(aff_text)
        if not texto:
            return False
        return any(marcador in texto for marcador in self._markers)


# --------------------------------------------------------------------------- #
#  Transformador
# --------------------------------------------------------------------------- #
class AffiliationTransformer(Transformer):
    """Convierte publicaciones en una tabla larga autor x afiliacion x pais.

    Cada fila es un autor de una publicacion con su afiliacion y el pais que se
    le asigno. Es la tabla base de la que salen todas las metricas: conteos por
    pais, coautoria y, mas adelante, genero.
    """

    source = "publications"
    name = "author_affiliations"

    def __init__(
        self,
        store: DataStore,
        resolver: AffiliationResolver,
        foreign_detector: Optional[ForeignAffiliationDetector] = None,
    ) -> None:
        super().__init__(store)
        self.resolver = resolver
        self.foreign_detector = foreign_detector or ForeignAffiliationDetector([])

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        filas: List[dict] = []
        total = len(df)
        intervalo = max(1, total // 20)  # ~20 avisos de progreso
        inicio = time.monotonic()

        logger.info("=" * 70)
        logger.info("TRANSFORMACION: %d publicaciones -> tabla autor x afiliacion", total)
        logger.info("Cascada de estrategias: %s",
                    " > ".join(e.name for e in self.resolver.strategies))
        logger.info("=" * 70)

        for procesadas, publicacion in enumerate(df.itertuples(index=False), start=1):
            autores = _como_lista(getattr(publicacion, "author", None))
            afiliaciones = _como_lista(getattr(publicacion, "aff", None))
            aff_ids = _como_lista(getattr(publicacion, "aff_id", None))

            # `author` y `aff` vienen alineados por posicion; si no, se rellena.
            total = max(len(autores), len(afiliaciones))
            for i in range(total):
                aff = afiliaciones[i] if i < len(afiliaciones) else None
                aff_id = aff_ids[i] if i < len(aff_ids) else None
                resolucion = self.resolver.resolve(aff or "", aff_id)

                filas.append(
                    {
                        "bibcode": publicacion.bibcode,
                        "year": getattr(publicacion, "year", None),
                        "author_position": i + 1,
                        "author": autores[i] if i < len(autores) else None,
                        "aff": aff,
                        "aff_id": aff_id,
                        "iso3": resolucion.iso3,
                        "resolution_strategy": resolucion.strategy,
                        "resolution_confidence": resolucion.confidence,
                        "is_foreign": (
                            False
                            if resolucion.resolved
                            else self.foreign_detector.is_foreign(aff or "")
                        ),
                        "citation_count": getattr(publicacion, "citation_count", None),
                    }
                )

            if procesadas % intervalo == 0 or procesadas == total:
                porcentaje = procesadas / total * 100 if total else 100.0
                logger.info(
                    "  %d/%d publicaciones (%.0f%%) | %d filas autor-afiliacion | "
                    "%d afiliaciones distintas en cache",
                    procesadas, total, porcentaje, len(filas), len(self.resolver._cache),
                )

        resultado = pd.DataFrame(filas)
        if not resultado.empty:
            resultado["year"] = pd.to_numeric(resultado["year"], errors="coerce").astype("Int64")

        transcurrido = time.monotonic() - inicio
        logger.info("Transformacion terminada en %.1fs", transcurrido)
        self._log_sin_resolver(resultado)
        return resultado

    def _log_sin_resolver(self, resultado: pd.DataFrame, muestra: int = 15) -> None:
        """Muestra las afiliaciones no resueltas mas frecuentes.

        Es la lista de trabajo para ampliar ``config/institutions.yml``.
        """
        if resultado.empty:
            return

        sin_resolver = resultado[
            resultado["iso3"].isna()
            & ~resultado["is_foreign"]
            & resultado["aff"].notna()
            & (resultado["aff"] != SIN_AFILIACION)
        ]
        if sin_resolver.empty:
            logger.info("No quedaron afiliaciones sin clasificar.")
            return

        frecuentes = sin_resolver["aff"].value_counts().head(muestra)
        logger.warning("")
        logger.warning(
            "AFILIACIONES SIN CLASIFICAR mas frecuentes "
            "(%d distintas; excluye coautores extranjeros ya reconocidos):",
            sin_resolver["aff"].nunique(),
        )
        for texto, n in frecuentes.items():
            logger.warning("  %4d x  %s", n, str(texto)[:110])
        logger.warning(
            "Si alguna es de la region, agregala a config/institutions.yml; "
            "si es extranjera, a config/foreign.yml."
        )

    def report(self, resultado: pd.DataFrame) -> Dict[str, object]:
        """Calidad del mapeo.

        La medida que importa no es "que porcentaje de afiliaciones se
        resolvio" —la mayoria son coautores extranjeros y nunca van a
        resolverse a un pais del estudio— sino:

        * que **toda** publicacion traiga al menos un autor de la region
          (si no, la query trajo algo que no corresponde), y
        * cuantas afiliaciones quedaron **sin clasificar**, que es la lista de
          trabajo para ampliar ``config/institutions.yml``.
        """
        if resultado.empty:
            return {"filas": 0}

        con_afiliacion = resultado[
            resultado["aff"].notna() & (resultado["aff"] != SIN_AFILIACION)
        ]
        region = con_afiliacion["iso3"].notna()
        extranjeras = (~region) & con_afiliacion["is_foreign"]
        sin_clasificar = (~region) & (~con_afiliacion["is_foreign"])

        publicaciones = resultado["bibcode"].nunique()
        con_region = resultado.loc[resultado["iso3"].notna(), "bibcode"].nunique()
        validacion = con_region / publicaciones if publicaciones else 0.0

        return {
            "publicaciones": publicaciones,
            "con >=1 autor de la region": f"{con_region}/{publicaciones} ({validacion:.1%})",
            "filas autor-afiliacion": len(resultado),
            "  afiliaciones de la region": int(region.sum()),
            "  coautores en el extranjero": int(extranjeras.sum()),
            "  SIN CLASIFICAR (revisar)": int(sin_clasificar.sum()),
            "por estrategia": resultado["resolution_strategy"].value_counts(dropna=True).to_dict(),
            "paises distintos": int(resultado["iso3"].nunique()),
        }


def _como_lista(valor) -> List:
    """Normaliza a lista los campos que ADS devuelve como lista o escalar.

    Tolera tambien el JSON crudo, por si el CSV se leyo con ``pd.read_csv``
    directo en vez de ``DataStore.read_csv``.
    """
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        return list(valor)
    if hasattr(valor, "tolist"):
        return list(valor.tolist())
    if isinstance(valor, str):
        texto = valor.strip()
        if texto.startswith("["):
            try:
                return list(json.loads(texto))
            except json.JSONDecodeError:
                return [valor]
        return [valor]
    if pd.isna(valor):
        return []
    return [valor]
