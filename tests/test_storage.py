"""El almacen fecha las extracciones y guarda CSV legibles sin perder las listas."""

from __future__ import annotations

from datetime import date

import pandas as pd

from astroca.storage import DataStore


def test_escribe_y_lee_la_mas_reciente(tmp_path):
    store = DataStore(tmp_path)
    store.write_raw("publications", pd.DataFrame({"bibcode": ["vieja"]}), date(2026, 1, 1))
    store.write_raw("publications", pd.DataFrame({"bibcode": ["nueva"]}), date(2026, 6, 1))

    assert store.read_latest_raw("publications").loc[0, "bibcode"] == "nueva"
    assert len(store.list_raw("publications")) == 2


def test_nombre_del_archivo(tmp_path):
    ruta = DataStore(tmp_path).write_raw(
        "publications", pd.DataFrame({"a": [1]}), date(2026, 10, 23)
    )
    assert ruta.name == "publications_20261023.csv"


def test_listas_sobreviven_el_ida_y_vuelta(tmp_path):
    """Las listas de ADS deben volver siendo listas, no texto."""
    store = DataStore(tmp_path)
    original = pd.DataFrame(
        [
            {
                "bibcode": "2020ApJ...1....1X",
                "author": ["Pérez, A.", "López, B."],
                "aff": ["Universidad de San Carlos, Guatemala", "-"],
                "query_countries": ["GTM"],
            }
        ]
    )
    store.write_raw("publications", original, date(2026, 10, 23))
    recuperado = store.read_latest_raw("publications")

    assert recuperado.loc[0, "author"] == ["Pérez, A.", "López, B."]
    assert recuperado.loc[0, "aff"][0].endswith("Guatemala")
    assert recuperado.loc[0, "query_countries"] == ["GTM"]


def test_el_csv_es_legible_como_texto(tmp_path):
    """Debe poder abrirse en Excel: encabezados y valores planos."""
    store = DataStore(tmp_path)
    store.write_raw(
        "publications", pd.DataFrame({"bibcode": ["x"], "year": [2020]}), date(2026, 10, 23)
    )
    texto = (tmp_path / "raw" / "publications_20261023.csv").read_text(encoding="utf-8")
    assert texto.splitlines()[0] == "bibcode,year"
    assert "x,2020" in texto


def test_sin_extracciones_da_mensaje_util(tmp_path):
    store = DataStore(tmp_path)
    try:
        store.read_latest_raw("publications")
    except FileNotFoundError as exc:
        assert "make extract" in str(exc)
    else:
        raise AssertionError("deberia haber fallado")


def test_fecha_de_extraccion(tmp_path):
    store = DataStore(tmp_path)
    ruta = store.write_raw("publications", pd.DataFrame({"a": [1]}), date(2026, 3, 15))
    assert DataStore.extraction_date(ruta) == "2026-03-15"


def test_processed_tambien_va_fechado(tmp_path):
    store = DataStore(tmp_path)
    store.write_processed("author_affiliations", pd.DataFrame({"a": [1]}), date(2026, 10, 23))
    assert store.read_latest_processed("author_affiliations").loc[0, "a"] == 1
