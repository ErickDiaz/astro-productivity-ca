"""La resolucion afiliacion -> pais es el punto critico del estudio.

Si estas pruebas pasan pero el mapeo falla en datos reales, el problema esta
en los patrones de `config/`, no en la cascada. El notebook 01 mide eso.
"""

from __future__ import annotations

import pandas as pd
import pytest

from astroca.storage import DataStore
from astroca.transform.affiliations import (
    AffiliationResolver,
    AffiliationTransformer,
    CityStrategy,
    CountryNameStrategy,
    EmailDomainStrategy,
    ForeignAffiliationDetector,
    InstitutionStrategy,
    normalizar,
)


# --------------------------------------------------------------------------- #
#  normalizacion
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("Panamá", "panama"),
        ("UNIVERSIDAD  DE   SAN CARLOS", "universidad de san carlos"),
        ("Observatorio   Astronómico\n", "observatorio astronomico"),
        ("", ""),
    ],
)
def test_normalizar(entrada, esperado):
    assert normalizar(entrada) == esperado


# --------------------------------------------------------------------------- #
#  estrategias individuales
# --------------------------------------------------------------------------- #
def test_nombre_de_pais(paises):
    estrategia = CountryNameStrategy(paises)
    assert estrategia.resolve("Universidad de San Carlos, Guatemala") == "GTM"
    assert estrategia.resolve("Escuela de Física, Costa Rica") == "CRI"
    assert estrategia.resolve("Harvard University, Cambridge MA") is None


def test_nombre_de_pais_con_acentos(paises):
    assert CountryNameStrategy(paises).resolve("Universidad, Ciudad de Guatemalá") == "GTM"


def test_institucion(paises):
    estrategia = InstitutionStrategy([("Universidad de San Carlos", "GTM")])
    assert estrategia.resolve("Universidad de San Carlos") == "GTM"
    assert estrategia.resolve("MIT") is None


def test_ciudad_ambigua_requiere_pais(paises):
    """'San Jose' solo debe resolver cuando viene calificado con el pais."""
    estrategia = CityStrategy(paises)
    assert estrategia.resolve("Observatorio, San Jose, Costa Rica") == "CRI"
    assert estrategia.resolve("San Jose State University, California") is None


def test_dominio_de_correo(paises):
    estrategia = EmailDomainStrategy(paises)
    assert estrategia.resolve("Depto. de Fisica (autor@usac.edu.gt)") == "GTM"
    assert estrategia.resolve("Depto. de Fisica (autor@ucr.ac.cr)") == "CRI"
    assert estrategia.resolve("autor@mit.edu") is None


def test_patron_mas_largo_gana(paises):
    """El patron mas especifico debe imponerse sobre el mas corto."""
    estrategia = CountryNameStrategy(paises)
    assert estrategia.resolve("Universidad Nacional, Costa Rica") == "CRI"


# --------------------------------------------------------------------------- #
#  cascada
# --------------------------------------------------------------------------- #
def test_cascada_prefiere_la_estrategia_mas_confiable(paises):
    resolver = AffiliationResolver.from_config(
        countries=paises,
        institutions=[("Universidad de San Carlos", "GTM")],
    )
    # La institucion (0.95) debe ganarle al dominio de correo (0.6).
    resultado = resolver.resolve("Universidad de San Carlos (autor@ucr.ac.cr)")
    assert resultado.iso3 == "GTM"
    assert resultado.strategy == "institution"


def test_afiliacion_vacia_o_marcador(paises):
    resolver = AffiliationResolver.from_config(paises, [])
    assert not resolver.resolve("").resolved
    assert not resolver.resolve("-").resolved


def test_no_resuelta_queda_registrada(paises):
    resolver = AffiliationResolver.from_config(paises, [])
    resultado = resolver.resolve("Institute of Astronomy, Cambridge, UK")
    assert resultado.iso3 is None
    assert resultado.strategy is None


def test_memoizacion(paises):
    resolver = AffiliationResolver.from_config(paises, [])
    texto = "Universidad de Panama, Panama"
    primera = resolver.resolve(texto)
    assert resolver.resolve(texto) is primera


# --------------------------------------------------------------------------- #
#  transformador
# --------------------------------------------------------------------------- #
def test_transformador_explota_autores(tmp_path, paises):
    publicaciones = pd.DataFrame(
        [
            {
                "bibcode": "2020ApJ...1....1X",
                "year": 2020,
                "author": ["Perez, A.", "Lopez, B."],
                "aff": ["Universidad de San Carlos, Guatemala", "Harvard University"],
                "aff_id": [None, None],
                "citation_count": 5,
            }
        ]
    )

    resolver = AffiliationResolver.from_config(paises, [])
    transformador = AffiliationTransformer(DataStore(tmp_path), resolver)
    resultado = transformador.transform(publicaciones)

    assert len(resultado) == 2
    assert resultado.loc[0, "iso3"] == "GTM"
    assert pd.isna(resultado.loc[1, "iso3"])
    assert list(resultado["author_position"]) == [1, 2]


def test_transformador_con_mas_afiliaciones_que_autores(tmp_path, paises):
    """ADS no siempre devuelve las listas alineadas; no debe perderse nada."""
    publicaciones = pd.DataFrame(
        [
            {
                "bibcode": "2021ApJ...2....2Y",
                "year": 2021,
                "author": ["Solo, A."],
                "aff": ["Universidad de Costa Rica", "Universidad de Panama, Panama"],
                "aff_id": [None, None],
                "citation_count": 0,
            }
        ]
    )
    resolver = AffiliationResolver.from_config(paises, [])
    resultado = AffiliationTransformer(DataStore(tmp_path), resolver).transform(publicaciones)
    assert len(resultado) == 2
    assert pd.isna(resultado.loc[1, "author"])  # pandas convierte None a NaN


def test_reporte_separa_extranjeros_de_sin_clasificar(tmp_path, paises):
    """Un coautor de Harvard no es un fallo del mapeo; no debe contarse como tal."""
    publicaciones = pd.DataFrame(
        [
            {
                "bibcode": "2020ApJ...1....1X",
                "year": 2020,
                "author": ["A", "B", "C"],
                "aff": [
                    "Universidad de San Carlos, Guatemala",
                    "Harvard University, Cambridge, MA, USA",
                    "Instituto Raro sin pistas",
                ],
                "aff_id": [None, None, None],
                "citation_count": 1,
            }
        ]
    )
    resolver = AffiliationResolver.from_config(paises, [])
    detector = ForeignAffiliationDetector(["usa", "united states"])
    transformador = AffiliationTransformer(DataStore(tmp_path), resolver, detector)
    reporte = transformador.report(transformador.transform(publicaciones))

    assert reporte["  afiliaciones de la region"] == 1
    assert reporte["  coautores en el extranjero"] == 1
    assert reporte["  SIN CLASIFICAR (revisar)"] == 1
    assert reporte["con >=1 autor de la region"] == "1/1 (100.0%)"


def test_publicacion_sin_autor_de_la_region_se_detecta(tmp_path, paises):
    """Si una publicacion no trae ningun autor de la region, la query fallo."""
    publicaciones = pd.DataFrame(
        [
            {
                "bibcode": "2020ApJ...9....9Z",
                "year": 2020,
                "author": ["A"],
                "aff": ["Harvard University, Cambridge, MA, USA"],
                "aff_id": [None],
                "citation_count": 0,
            }
        ]
    )
    resolver = AffiliationResolver.from_config(paises, [])
    transformador = AffiliationTransformer(
        DataStore(tmp_path), resolver, ForeignAffiliationDetector(["usa"])
    )
    reporte = transformador.report(transformador.transform(publicaciones))
    assert reporte["con >=1 autor de la region"] == "0/1 (0.0%)"
