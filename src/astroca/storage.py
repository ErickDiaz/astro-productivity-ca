"""Acceso al almacen de datos en disco.

El pipeline respeta tres capas, en un solo sentido:

    data/raw/        respuestas de ADS tal como llegaron, fechadas e inmutables
    data/interim/    resultados intermedios de la transformacion
    data/processed/  tablas analiticas, lo unico que leen los notebooks

Fechar el raw (``publications_20261023.csv``) permite repetir un analisis
exactamente como se corrio, y hace que una extraccion nueva no pise la anterior.

**Sobre el formato.** Se usa CSV para que los archivos se puedan abrir en Excel
o Google Sheets sin herramientas extra. El costo es que CSV no tiene tipos: ADS
devuelve listas (autores, afiliaciones) y una lista escrita tal cual en un CSV
no se puede volver a leer de forma fiable. Por eso las columnas de lista se
guardan como JSON y se reconstruyen al leer; el archivo sigue siendo legible y
el ida y vuelta no pierde datos.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

#: Sufijo de fecha de las extracciones: publications_20261023.csv
FORMATO_FECHA = "%Y%m%d"
_PATRON_FECHA = re.compile(r"_(\d{8})\.csv$")

#: Columnas que ADS devuelve como lista y que se serializan a JSON.
COLUMNAS_LISTA = (
    "author",
    "aff",
    "aff_id",
    "property",
    "orcid_pub",
    "keyword",
    "query_countries",
)


def _codificar_listas(df: pd.DataFrame, columnas: Sequence[str]) -> pd.DataFrame:
    """Convierte las columnas de lista a texto JSON para escribirlas en CSV."""
    salida = df.copy()
    for columna in columnas:
        if columna in salida.columns:
            salida[columna] = salida[columna].apply(_a_json)
    return salida


def _a_json(valor):
    if valor is None:
        return None
    if isinstance(valor, (list, tuple)):
        return json.dumps(list(valor), ensure_ascii=False)
    if hasattr(valor, "tolist"):
        return json.dumps(valor.tolist(), ensure_ascii=False)
    return valor


def _decodificar_listas(df: pd.DataFrame, columnas: Sequence[str]) -> pd.DataFrame:
    """Reconstruye las listas a partir del JSON guardado en el CSV."""
    for columna in columnas:
        if columna in df.columns:
            df[columna] = df[columna].apply(_desde_json)
    return df


def _desde_json(valor):
    if not isinstance(valor, str):
        return valor
    texto = valor.strip()
    if not texto.startswith("["):
        return valor
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return valor


class DataStore:
    """Lectura y escritura de las tres capas de datos, en CSV."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- rutas ------------------------------------------------------------- #
    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def interim(self) -> Path:
        return self.root / "interim"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    # -- escritura --------------------------------------------------------- #
    def write_raw(self, name: str, df: pd.DataFrame, run_date: Optional[date] = None) -> Path:
        """Escribe una extraccion cruda con la fecha en el nombre.

        Ejemplo: ``data/raw/publications_20261023.csv``.
        """
        fecha = (run_date or date.today()).strftime(FORMATO_FECHA)
        return self._write(self.raw / f"{name}_{fecha}.csv", df)

    def write_interim(self, name: str, df: pd.DataFrame) -> Path:
        return self._write(self.interim / f"{name}.csv", df)

    def write_processed(
        self, name: str, df: pd.DataFrame, run_date: Optional[date] = None
    ) -> Path:
        """Escribe una tabla analitica, tambien fechada."""
        fecha = (run_date or date.today()).strftime(FORMATO_FECHA)
        return self._write(self.processed / f"{name}_{fecha}.csv", df)

    def _write(self, ruta: Path, df: pd.DataFrame) -> Path:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        codificado = _codificar_listas(df, COLUMNAS_LISTA)
        codificado.to_csv(ruta, index=False, encoding="utf-8")
        logger.debug("Escritas %d filas en %s", len(df), ruta)
        return ruta

    # -- lectura ----------------------------------------------------------- #
    def read_latest_raw(self, name: str) -> pd.DataFrame:
        """Lee la extraccion cruda mas reciente de ``name``."""
        ruta = self.latest_raw_path(name)
        if ruta is None:
            raise FileNotFoundError(
                f"No hay extracciones de '{name}' en {self.raw}. Corre `make extract` primero."
            )
        return self.read_csv(ruta)

    def read_latest_processed(self, name: str) -> pd.DataFrame:
        """Lee la tabla analitica mas reciente. Es lo que usan los notebooks."""
        rutas = self._listar(self.processed, name)
        if not rutas:
            raise FileNotFoundError(
                f"No hay tablas '{name}' en {self.processed}. Corre `make transform` primero."
            )
        return self.read_csv(rutas[-1])

    @staticmethod
    def read_csv(ruta: Path) -> pd.DataFrame:
        """Lee un CSV del proyecto reconstruyendo las columnas de lista."""
        df = pd.read_csv(ruta, encoding="utf-8")
        return _decodificar_listas(df, COLUMNAS_LISTA)

    def latest_raw_path(self, name: str) -> Optional[Path]:
        rutas = self.list_raw(name)
        return rutas[-1] if rutas else None

    def list_raw(self, name: str) -> List[Path]:
        """Extracciones de ``name``, de la mas vieja a la mas nueva."""
        return self._listar(self.raw, name)

    @staticmethod
    def _listar(directorio: Path, name: str) -> List[Path]:
        if not directorio.exists():
            return []
        archivos = [p for p in directorio.glob(f"{name}_*.csv") if _PATRON_FECHA.search(p.name)]
        return sorted(archivos, key=lambda p: _PATRON_FECHA.search(p.name).group(1))

    @staticmethod
    def extraction_date(ruta: Path) -> Optional[str]:
        """Fecha de extraccion codificada en el nombre, como ``2026-10-23``."""
        m = _PATRON_FECHA.search(ruta.name)
        if not m:
            return None
        return datetime.strptime(m.group(1), FORMATO_FECHA).date().isoformat()
