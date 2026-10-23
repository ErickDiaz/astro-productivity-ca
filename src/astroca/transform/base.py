"""Contrato comun de los transformadores."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict

import pandas as pd

from astroca.storage import DataStore

logger = logging.getLogger(__name__)


class Transformer(ABC):
    """Convierte datos crudos en tablas analiticas.

    Un transformador es una funcion pura sobre DataFrames: ``transform`` no
    toca disco ni red. ``run`` se encarga de leer y escribir, de modo que la
    logica se puede probar sin montar el almacen.
    """

    #: Nombre del dataset crudo que consume.
    source: str = ""

    #: Nombre con el que se escribe el resultado en ``data/processed``.
    name: str = ""

    def __init__(self, store: DataStore) -> None:
        if not self.name or not self.source:
            raise ValueError(f"{type(self).__name__} debe definir `source` y `name`")
        self.store = store

    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Logica de transformacion, sin efectos de borde."""

    def report(self, resultado: pd.DataFrame) -> Dict[str, object]:
        """Metricas de calidad de la transformacion.

        Se imprimen al final de ``run`` y se usan en el notebook de validacion.
        """
        return {"filas": len(resultado)}

    def run(self) -> Path:
        logger.info("Transformador '%s' iniciado (%s)", self.name, type(self).__name__)

        origen = self.store.latest_raw_path(self.source)
        if origen is not None:
            logger.info("Leyendo %s (extraccion del %s)",
                        origen.name, self.store.extraction_date(origen))
        entrada = self.store.read_latest_raw(self.source)
        logger.info("Entrada: %d filas, %d columnas", len(entrada), len(entrada.columns))

        resultado = self.transform(entrada)
        ruta = self.store.write_processed(self.name, resultado)

        logger.info("")
        logger.info("--- REPORTE DE CALIDAD: %s ---", self.name)
        for clave, valor in self.report(resultado).items():
            logger.info("  %s: %s", clave, valor)
        logger.info("Escrito: %s (%d filas)", ruta, len(resultado))
        return ruta
