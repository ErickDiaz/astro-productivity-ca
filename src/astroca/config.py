"""Carga y validacion de la configuracion del proyecto.

Dos fuentes, con responsabilidades separadas:

* ``config/*.yml`` describe *que* se estudia (campo, periodo, paises). Es
  versionable y es lo que se toca para ampliar el estudio.
* ``.env`` describe *como* se ejecuta (token, rutas, ritmo de llamadas). Es
  secreto y especifico de cada maquina.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


# --------------------------------------------------------------------------- #
#  config/search.yml
# --------------------------------------------------------------------------- #
class FieldConfig(BaseModel):
    """Filtros que definen el campo cientifico bajo estudio."""

    database: str = "astronomy"
    refereed_only: bool = True
    keywords: List[str] = Field(default_factory=list)
    keyword_logic: str = "OR"
    keyword_fields: List[str] = Field(default_factory=lambda: ["abs"])

    @field_validator("keyword_logic")
    @classmethod
    def _validar_logica(cls, v: str) -> str:
        logica = v.upper()
        if logica not in {"OR", "AND"}:
            raise ValueError("keyword_logic debe ser 'OR' o 'AND'")
        return logica


class PeriodConfig(BaseModel):
    start_year: int = 1950
    end_year: int = 2025

    @field_validator("end_year")
    @classmethod
    def _validar_rango(cls, v: int, info) -> int:
        inicio = info.data.get("start_year")
        if inicio is not None and v < inicio:
            raise ValueError("end_year no puede ser menor que start_year")
        return v


class AuthorsConfig(BaseModel):
    """Corte anti hiper-autoria. ``None`` desactiva el filtro."""

    max_authors: Optional[int] = 10


class ExtractionConfig(BaseModel):
    rows_per_page: int = 200
    max_records_per_country: Optional[int] = None
    fields: List[str] = Field(default_factory=list)

    @field_validator("rows_per_page")
    @classmethod
    def _validar_filas(cls, v: int) -> int:
        if not 1 <= v <= 2000:
            raise ValueError("rows_per_page debe estar entre 1 y 2000 (limite de ADS)")
        return v


class SearchConfig(BaseModel):
    field: FieldConfig = Field(default_factory=FieldConfig)
    period: PeriodConfig = Field(default_factory=PeriodConfig)
    authors: AuthorsConfig = Field(default_factory=AuthorsConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)


# --------------------------------------------------------------------------- #
#  config/countries.yml
# --------------------------------------------------------------------------- #
class Country(BaseModel):
    """Un pais del estudio y las pistas para reconocerlo en una afiliacion."""

    iso3: str
    name: str
    name_en: str
    region: str
    tld: str
    aff_patterns: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)

    @property
    def search_terms(self) -> List[str]:
        """Terminos con los que se consulta el campo ``aff`` de ADS."""
        return [self.name_en, *self.cities]


class CountriesConfig(BaseModel):
    scope: str = "centroamerica"
    countries: List[Country] = Field(default_factory=list)

    @field_validator("scope")
    @classmethod
    def _validar_scope(cls, v: str) -> str:
        if v not in {"centroamerica", "caribe", "all"}:
            raise ValueError("scope debe ser 'centroamerica', 'caribe' o 'all'")
        return v

    def in_scope(self) -> List[Country]:
        """Paises activos segun ``scope``."""
        if self.scope == "all":
            return list(self.countries)
        return [c for c in self.countries if c.region == self.scope]

    def by_iso3(self, iso3: str) -> Optional[Country]:
        return next((c for c in self.countries if c.iso3 == iso3), None)


# --------------------------------------------------------------------------- #
#  config/institutions.yml
# --------------------------------------------------------------------------- #
class InstitutionsConfig(BaseModel):
    institutions: Dict[str, List[str]] = Field(default_factory=dict)

    def flatten(self) -> List[tuple]:
        """Lista de ``(nombre_institucion, iso3)`` para el resolvedor."""
        return [(nombre, iso3) for iso3, nombres in self.institutions.items() for nombre in nombres]


class ForeignConfig(BaseModel):
    """Marcadores de paises de fuera de la region.

    Solo se usan para clasificar el reporte de calidad, nunca para asignar
    pais a una publicacion del estudio.
    """

    foreign_markers: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
#  .env
# --------------------------------------------------------------------------- #
class Settings(BaseSettings):
    """Parametros de ejecucion. Se leen de variables de entorno o de ``.env``."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ads_dev_key: str = ""
    astroca_data_dir: Path = Path("data")
    astroca_cache_dir: Path = Path(".cache/ads")
    astroca_request_delay: float = 0.5

    @property
    def data_dir(self) -> Path:
        return self._absolutizar(self.astroca_data_dir)

    @property
    def cache_dir(self) -> Path:
        return self._absolutizar(self.astroca_cache_dir)

    @staticmethod
    def _absolutizar(ruta: Path) -> Path:
        return ruta if ruta.is_absolute() else PROJECT_ROOT / ruta

    def require_token(self) -> str:
        """Devuelve el token o explica como obtenerlo."""
        if not self.ads_dev_key:
            raise RuntimeError(
                "Falta ADS_DEV_KEY.\n"
                "  1. Consiguelo en https://ui.adsabs.harvard.edu/user/settings/token\n"
                "  2. Corre `make env` y pegalo en el archivo .env"
            )
        return self.ads_dev_key


# --------------------------------------------------------------------------- #
#  Carga
# --------------------------------------------------------------------------- #
def _leer_yaml(ruta: Path) -> dict:
    if not ruta.exists():
        raise FileNotFoundError(f"No encuentro el archivo de configuracion: {ruta}")
    with ruta.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class ConfigLoader:
    """Punto unico de acceso a la configuracion.

    Cachea las lecturas para que extractores, transformadores y notebooks
    compartan exactamente la misma configuracion dentro de una corrida.
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self.config_dir = config_dir or CONFIG_DIR
        self._memo: Dict[str, object] = {}

    def _cargar(self, clave: str, constructor):
        """Memoiza por instancia (no con lru_cache, que retendria el loader)."""
        if clave not in self._memo:
            self._memo[clave] = constructor()
        return self._memo[clave]

    def search(self) -> SearchConfig:
        return self._cargar(
            "search", lambda: SearchConfig(**_leer_yaml(self.config_dir / "search.yml"))
        )

    def countries(self) -> CountriesConfig:
        return self._cargar(
            "countries", lambda: CountriesConfig(**_leer_yaml(self.config_dir / "countries.yml"))
        )

    def institutions(self) -> InstitutionsConfig:
        return self._cargar(
            "institutions",
            lambda: InstitutionsConfig(**_leer_yaml(self.config_dir / "institutions.yml")),
        )

    def foreign(self) -> ForeignConfig:
        return self._cargar(
            "foreign", lambda: ForeignConfig(**_leer_yaml(self.config_dir / "foreign.yml"))
        )

    def settings(self) -> Settings:
        return self._cargar("settings", Settings)


@lru_cache(maxsize=1)
def get_loader() -> ConfigLoader:
    """Loader compartido por todo el proceso."""
    return ConfigLoader()
