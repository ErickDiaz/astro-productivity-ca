"""Contrato comun de los extractores."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

import pandas as pd

from astroca.storage import DataStore

logger = logging.getLogger(__name__)


class Extractor(ABC):
    """Baja datos de una fuente externa y los deja crudos en ``data/raw``.

    ``run()`` es un metodo plantilla: fija el orden de los pasos (traer,
    tabular, escribir) y deja que cada subclase defina solo ``fetch`` y
    ``to_frame``. Los extractores no transforman nada; esa es responsabilidad
    de ``astroca.transform``.
    """

    #: Nombre del dataset; da nombre al archivo en ``data/raw``.
    name: str = ""

    def __init__(self, store: DataStore) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} debe definir un atributo `name`")
        self.store = store

    @abstractmethod
    def fetch(self) -> List[dict]:
        """Trae los registros crudos de la fuente."""

    @abstractmethod
    def to_frame(self, records: List[dict]) -> pd.DataFrame:
        """Convierte los registros crudos en una tabla."""

    def run(self) -> Path:
        """Ejecuta la extraccion completa y devuelve la ruta escrita."""
        logger.info("Extractor '%s' iniciado (%s)", self.name, type(self).__name__)
        registros = self.fetch()
        df = self.to_frame(registros)
        ruta = self.store.write_raw(self.name, df)
        tamano_mb = ruta.stat().st_size / 1024 / 1024
        logger.info("Escrito: %s (%d filas, %d columnas, %.2f MB)",
                    ruta, len(df), len(df.columns), tamano_mb)
        return ruta
